using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.Runtime;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Lane B: HoMM3 lab bundles (<c>tools/homm3_import/</c>) — UI spawner, <c>dzk.bath</c> battle pool,
/// <c>UnitViewConfig.rtd</c> map, and <c>ResManager.Get&lt;GameObject&gt;</c> for adventure-map prefabs (same path as esquire map).
/// Does not patch esquire paths.
/// </summary>
internal static class Homm3ImportVisuals
{
	private const int MapArrayBridgeFailureLogLimit = 16;
	private static readonly HashSet<string> LoggedMapArrayBridgeFailures = new(StringComparer.Ordinal);
	private static int _loggedMapArrayBridgeFailureCount;

	internal sealed class Entry
	{
		internal string BattleResPath;
		internal string MapResPath;
		internal bool SwapAdventureMap;
		internal string BundleName;
		internal string BattlePrefabAssetPath;
		internal string MapPrefabAssetPath;
		internal string BattleNorm;
		internal string MapNorm;
		/// <summary>Optional real vanilla battle path used for presentation/layer fallback; never used as a swap key.</summary>
		internal string BattlePresentationResPath;
		internal string BattlePresentationNorm;
		/// <summary>Optional real vanilla map path used as the native shell for synthetic map entries; never used as a swap key.</summary>
		internal string MapShellResPath;
		internal string MapShellNorm;
		/// <summary>
		/// Optional native <c>UnitViewConfig.id</c> the unit detail preview factory builds its rig from, for an
		/// owned skinned unit with no custom-faction registry donor (neutrals). Preview-only: it never aliases HUD,
		/// law or icon lookups the way the registry donor does. The validator pins it to the leaf of
		/// <c>battlePresentationResPath</c>.
		/// </summary>
		internal string PreviewDonorSid;
		/// <summary>Optional override for <see cref="Homm3LabBattleAudioPlayer"/> clip stems (must end with <c>_</c> or one is appended), e.g. <c>HOMM3_temple_griffon_</c>.</summary>
		internal string AudioStemPrefix;
		/// <summary>
		/// Optional in-game unit config SIDs (e.g. <c>h3_goblin</c>) that reuse this entry's HoMM3 battle prefab for
		/// <see cref="TryGetBattleTemplateForUnitSid"/> — tooltip portrait texture and preview hooks. Does not change
		/// <c>dzk.bath</c> / <c>rtd</c> matching (still keyed by shipped <c>units/…</c> paths from Core).
		/// </summary>
		internal List<string> GameUnitSids;
		/// <summary>
		/// Optional HoMM3 battle height of this unit in HoMM3 battlefield hexes (idle plate body height / 42 px).
		/// When present, the owned skinned battle mesh is fit to <c>BattleHeightHexes * battleWorldHeightPerHex</c>
		/// instead of the donor's renderer height (donor bounds vary arbitrarily: a troglodyte donor made the goblin
		/// taller than the orc). Requires the table-level <c>battleWorldHeightPerHex</c>.
		/// </summary>
		internal float? BattleHeightHexes;
		// Battle ground speed is the Core view row's moveSpeed (normalized to vanilla references by the Core overlay);
		// the Move stride is matched to it offline (stride_match_glb.py). The runtime never rewrites moveSpeed.
	}

	/// <summary>World units per HoMM3 battlefield hex-height; the single scale tuning knob for hex-sized units. Null when the table does not declare it.</summary>
	static float? _battleWorldHeightPerHex;

	/// <summary>
	/// Native adventure-map / battle size convention: stock <c>&lt;unit&gt;_map</c> prefabs reuse the battle
	/// skinned mesh under a smaller scale node (troglodyte 32/44). Table value is the median over every
	/// stock pair, measured by <c>tools/homm3_import/measure_native_map_battle_scale.py</c>
	/// (<c>native_map_battle_scale.json</c>). Map squads fit to battle hex target times this ratio.
	/// </summary>
	static float? _adventureMapToBattleHeightRatio;

	private sealed class TemplateLookup
	{
		internal Entry Entry;
		internal bool UseMapTemplate;
	}

	private readonly struct OwnedSkinnedMapFitCacheKey : IEquatable<OwnedSkinnedMapFitCacheKey>
	{
		readonly int _templateInstanceId;
		readonly string _bundleName;
		readonly string _mapPrefabAssetPath;
		readonly float _battleHeightHexes;
		readonly float _battleWorldHeightPerHex;
		readonly float _adventureMapToBattleHeightRatio;
		readonly SkinWeights _initialSkinWeights;
		readonly Vector3 _parentRight;
		readonly Vector3 _parentUp;
		readonly Vector3 _parentForward;
		readonly Quaternion _visualLocalRotation;

		internal OwnedSkinnedMapFitCacheKey(
			int templateInstanceId,
			Entry entry,
			float battleWorldHeightPerHex,
			float adventureMapToBattleHeightRatio,
			SkinWeights initialSkinWeights,
			Transform shell,
			Transform visual)
		{
			_templateInstanceId = templateInstanceId;
			_bundleName = entry.BundleName ?? string.Empty;
			_mapPrefabAssetPath = entry.MapPrefabAssetPath ?? string.Empty;
			_battleHeightHexes = entry.BattleHeightHexes.GetValueOrDefault();
			_battleWorldHeightPerHex = battleWorldHeightPerHex;
			_adventureMapToBattleHeightRatio = adventureMapToBattleHeightRatio;
			_initialSkinWeights = initialSkinWeights;
			_parentRight = shell.TransformVector(Vector3.right);
			_parentUp = shell.TransformVector(Vector3.up);
			_parentForward = shell.TransformVector(Vector3.forward);
			_visualLocalRotation = visual.localRotation;
		}

		public bool Equals(OwnedSkinnedMapFitCacheKey other)
		{
			return _templateInstanceId == other._templateInstanceId
			       && string.Equals(_bundleName, other._bundleName, StringComparison.Ordinal)
			       && string.Equals(_mapPrefabAssetPath, other._mapPrefabAssetPath, StringComparison.Ordinal)
			       && _battleHeightHexes.Equals(other._battleHeightHexes)
			       && _battleWorldHeightPerHex.Equals(other._battleWorldHeightPerHex)
			       && _adventureMapToBattleHeightRatio.Equals(other._adventureMapToBattleHeightRatio)
			       && _initialSkinWeights == other._initialSkinWeights
			       && _parentRight.Equals(other._parentRight)
			       && _parentUp.Equals(other._parentUp)
			       && _parentForward.Equals(other._parentForward)
			       && _visualLocalRotation.Equals(other._visualLocalRotation);
		}

		public override bool Equals(object obj) => obj is OwnedSkinnedMapFitCacheKey other && Equals(other);

		public override int GetHashCode()
		{
			unchecked
			{
				var hash = _templateInstanceId;
				hash = (hash * 397) ^ StringComparer.Ordinal.GetHashCode(_bundleName);
				hash = (hash * 397) ^ StringComparer.Ordinal.GetHashCode(_mapPrefabAssetPath);
				hash = (hash * 397) ^ _battleHeightHexes.GetHashCode();
				hash = (hash * 397) ^ _battleWorldHeightPerHex.GetHashCode();
				hash = (hash * 397) ^ _adventureMapToBattleHeightRatio.GetHashCode();
				hash = (hash * 397) ^ _initialSkinWeights.GetHashCode();
				hash = (hash * 397) ^ _parentRight.GetHashCode();
				hash = (hash * 397) ^ _parentUp.GetHashCode();
				hash = (hash * 397) ^ _parentForward.GetHashCode();
				hash = (hash * 397) ^ _visualLocalRotation.GetHashCode();
				return hash;
			}
		}
	}

	// Reuse only for fresh clones of one immutable map prefab; capture the final fit/plant after compatibility, never animated world bounds.
	private readonly struct OwnedSkinnedMapFit
	{
		internal readonly GameObject Template;
		internal readonly Vector3 LocalScale;
		internal readonly float FeetOffsetFromFloor;

		internal OwnedSkinnedMapFit(GameObject template, Vector3 localScale, float feetOffsetFromFloor)
		{
			Template = template;
			LocalScale = localScale;
			FeetOffsetFromFloor = feetOffsetFromFloor;
		}
	}

	static readonly List<Entry> Entries = new();
	static readonly Dictionary<string, TemplateLookup> TemplateLookupByUnitsPath = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Entry> BattleEntriesByUnitsPath = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Entry> MapEntriesByUnitsPath = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Entry> SwappableMapEntriesByUnitsPath = new(StringComparer.Ordinal);
	static readonly Dictionary<string, List<Entry>> EntriesByLeafSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Entry> EntriesByGameUnitSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, AssetBundle> Bundles = new(StringComparer.Ordinal);
	static readonly Dictionary<string, GameObject> BattleTemplates = new(StringComparer.Ordinal);
	static readonly Dictionary<string, GameObject> MapTemplates = new(StringComparer.Ordinal);
	static readonly Dictionary<OwnedSkinnedMapFitCacheKey, OwnedSkinnedMapFit> OwnedSkinnedMapFitCache = new();
	static readonly Dictionary<string, GameObject> ProjectileTemplates = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Material> MapArrayMaterialsByBundle = new(StringComparer.Ordinal);
	static readonly Dictionary<string, SortedDictionary<int, Texture2DArray>> MapArrayTexturesByBundle = new(StringComparer.Ordinal);
	static readonly Dictionary<int, HashSet<string>> ProjectileVisualsAttachedByShellId = new();
	static int _projectileVisualPresentationDiagRemaining = 12;
	static readonly Dictionary<int, Entry> MapTemplateEntriesByInstanceId = new();
	static readonly Dictionary<string, List<Material>> MapFrameMaterialsByTemplateKey = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Texture2D[]> BundleFrameTexturesByKey = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Texture2D[]> MapFrameTexturesByBundleName = new(StringComparer.Ordinal);
	static readonly HashSet<int> MapFrameBundleHydratedInstanceIds = new();
	static readonly HashSet<string> BundleFrameTextureMissesByKey = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Texture2D> DiskFrameTexturesByLabSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Texture2D[]> DiskIdleFrameTexturesByLabSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, List<string>> DiskIdleFramePathsByLabSid = new(StringComparer.Ordinal);
	static readonly HashSet<string> DiskIdleFrameTextureMissesByLabSid = new(StringComparer.Ordinal);
	static readonly HashSet<string> TownStyleUnitBillboardPostconditionWarnings = new(StringComparer.Ordinal);
	static readonly HashSet<string> DirectMapArrayDonorMisses = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Material> DirectMapArrayDonorMaterialsByShell = new(StringComparer.Ordinal);
	static readonly object Homm3LabAudioIndexGate = new();
	static readonly HashSet<string> Homm3LabAudioIndexedBundles = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Dictionary<string, AudioClip>> Homm3LabAudioClipsByBundle = new(StringComparer.Ordinal);
	static bool Homm3LabBattleAudioPlayerRegistered;
	static bool Homm3LabClipDriverRegistered;
	static bool Homm3MapIdleAnimatorRegistered;
	static bool Homm3MapNativeShellTemplateGuardRegistered;
	static bool Homm3MapIdleAnimatorHostAttached;
	static GameObject Homm3MapIdleAnimatorHostObject;
	static bool Homm3MapSquadRuntimeAttachEnabled;
	static MethodInfo _resManagerGetGameObject;
	static bool _resManagerGetGameObjectIsStatic;
	static IntPtr _resManagerGetNativeMethodPtr;
	static Type _resManagerType;
	static object _resManagerInstanceFromHook;
	static readonly HashSet<string> NativeResManagerCacheInterest =
		new(StringComparer.Ordinal);
	static int _loggedResManagerLoadFail;
	static int _loggedResManagerNoInstance;
	static int _loggedResManagerNullResult;
	static string _bundleSubdir = "homm3_bundles";
	static bool _loaded;
	static bool _loggedMapFinishSignature;
	static int _mapRendererFlagDiagRemaining = 8;
	static int _nativeShellDiagRemaining = 12;
	static int _townStyleUnitBillboardDiagRemaining = 12;
	static int _townStyleUnitIdleAnimDiagRemaining = 12;
	static int _townStyleUnitIdleAnimMissDiagRemaining = 12;
	static int _unitMapFrameCacheRefreshDiagRemaining = 12;
	static int _mapLoadProfileShells;
	static int _mapLoadProfileTownBillboardAttempts;
	static int _mapLoadProfileTownBillboardSuccesses;
	static int _mapLoadProfileDiskFrameLoads;
	static int _mapLoadProfileIdleFrameLoads;
	static int _mapLoadProfileIdleFrameScans;
	static int _mapLoadProfilePostconditionChecks;
	static int _mapLoadProfileLastReportShells;
	static int _mapPrefabScaleLogRemaining = 8;
	static long _mapLoadProfileShellTicks;
	static long _mapLoadProfileTownBillboardTicks;
	static long _mapLoadProfileDiskFrameTicks;
	static long _mapLoadProfileIdleFrameLoadTicks;
	static long _mapLoadProfileIdleFrameScanTicks;
	static long _mapLoadProfilePostconditionTicks;
	static Mesh _townStyleUnitBillboardQuadMesh;
	/// <summary>Unified adventure-map visual root (pre-1c1bbda6): town-style + map.prefab share one quad for Hex/Lit fog + MapIdle.</summary>
	const string TownStyleUnitBillboardRootName = "homm3_map_visual";
	internal const string MapPrefabVisualChildName = "homm3_map_visual";
	const float TownStyleUnitBillboardScale = 0.125f;
	/// <summary>Map prefab quads are authored at 16x/8x; shrink when local scale exceeds vanilla footprint.</summary>
	const float AuthoredMapQuadOversizeThreshold = 4f;
	static readonly HashSet<int> MapPrefabScaleNormalizedRootIds = new();
	const float BattleSpriteRuntimeScale = 0.8f;
	/// <summary>Fallback town-style texture tick when no RIFE map metadata is deployed.</summary>
	const float TownStyleUnitIdleFrameMs = 120f;
	const string MapAdventureWalkClipName = "MapIdle";
	const float MapAdventurePlaybackSpeedMin = 0.05f;
	const float MapAdventurePlaybackSpeedMax = 24f;
	static int _mapAdventurePlaybackTimingDiagRemaining = 12;
	static bool LooseHomm3LabFramePngFallbackEnabled => false;
	const int MapLoadProfileReportEveryShells = 25;
	static readonly Dictionary<string, string> ProjectileBundleByResourcePath = new(StringComparer.Ordinal)
	{
		{ "effects/projectiles/homm3_h3_orc_projectile", "custom_units_h3_orc" },
		{ "effects/projectiles/homm3_h3_orc_chieftain_projectile", "custom_units_h3_orc_chieftain" },
		{ "effects/projectiles/homm3_h3_cyclops_projectile", "custom_units_h3_cyclops" },
		{ "effects/projectiles/homm3_h3_cyclops_king_projectile", "custom_units_h3_cyclops_king" },
		{ "effects/projectiles/homm3_toa_blood_eyed_cyclops_projectile", "custom_units_toa_blood_eyed_cyclops" }
	};

	static readonly Dictionary<string, string> ProjectileAssetByResourcePath = new(StringComparer.Ordinal)
	{
		{ "effects/projectiles/homm3_h3_orc_projectile", "Assets/CustomUnits/homm3_lab/h3_orc/projectiles/homm3_h3_orc_projectile.prefab" },
		{ "effects/projectiles/homm3_h3_orc_chieftain_projectile", "Assets/CustomUnits/homm3_lab/h3_orc_chieftain/projectiles/homm3_h3_orc_chieftain_projectile.prefab" },
		{ "effects/projectiles/homm3_h3_cyclops_projectile", "Assets/CustomUnits/homm3_lab/h3_cyclops/projectiles/homm3_h3_cyclops_projectile.prefab" },
		{ "effects/projectiles/homm3_h3_cyclops_king_projectile", "Assets/CustomUnits/homm3_lab/h3_cyclops_king/projectiles/homm3_h3_cyclops_king_projectile.prefab" },
		{ "effects/projectiles/homm3_toa_blood_eyed_cyclops_projectile", "Assets/CustomUnits/homm3_lab/toa_blood_eyed_cyclops/projectiles/homm3_toa_blood_eyed_cyclops_projectile.prefab" }
	};

	private struct TownStyleUnitBillboardSource
	{
		internal Texture Texture;
		internal Vector2 Size;
		internal string RendererName;
		internal Vector3 RootLocalPosition;
		internal Quaternion RootLocalRotation;
		internal Vector3 RootLocalScale;
		internal Vector3 QuadLocalPosition;
		internal Quaternion QuadLocalRotation;
		internal Vector3 QuadLocalScale;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log, bool registerPreviewHooks)
	{
		// Always register — not gated on Entries; needed for any custom unit SID not in vanilla dicts.
		Homm3ImportBhSelectedUnitHudFix.TryRegister(harmony, log);

		TryLoadTable(log);
		if (Entries.Count == 0)
			return;
		ResManagerGameObjectLaneHooks.TryRegister(harmony, log);
		Homm3ImportBattlePoolHook.TryRegister(harmony, log);
		Homm3ImportUnitViewHook.TryRegister(harmony, log);
		Homm3ProjectileConfigHook.TryRegister(harmony, log);
		Homm3ImportNarrowSpawnerHook.TryRegister(harmony, log);
		Homm3MapObjectUnitVisualHook.TryRegister(harmony, log);
		Homm3ImportTooltipPortraitHook.TryRegister(harmony, log);
		Homm3ImportArmyStripPortraitHook.TryRegister(harmony, log);
		if (registerPreviewHooks)
		{
			Homm3ImportPreviewWindowHook.TryRegister(harmony, log);
			Homm3ImportPreviewSyntheticMeshHook.TryRegister(harmony, log);
			Homm3ImportUnitPreviewModelHook.TryRegister(harmony, log);
			if (Homm3DiagnosticFlags.IsEnabled("homm3_preview_probe.flag"))
				Homm3ImportPreviewProbe.TryRun(log);
		}
		else
		{
			log?.LogInfo(
				"Homm3Import: preview hooks skipped (homm3ImportPreviewHooks=false). Battle/map/spawner/tooltip still apply when homm3_import.json has entries."
			);
		}
	}

	internal static void TryRegisterReleaseSafeMapSlice(Harmony harmony, ManualLogSource log)
	{
		TryLoadTable(log);
		if (Entries.Count == 0)
		{
			log?.LogInfo("Homm3Import release map slice: no homm3_import.json entries; map swap disabled.");
			return;
		}

		Homm3ImportUnitViewHook.TryRegister(harmony, log);
		Homm3ImportReleaseBattleVisualHook.TryRegister(harmony, log);
		Homm3ImportReleaseBattleUiHook.TryRegister(harmony, log);
		log?.LogInfo("Homm3Import release visual slice: registered UnitViewConfig map swap, ecd.Init battle visual swap, and narrow battle UI portrait swaps only; preview, ResManager, projectile, spawner, squad-controller, and death-fade hooks remain quarantined.");
	}

	internal static void TryRegisterReleaseFullFeatureSlice(Harmony harmony, ManualLogSource log, LauncherConfig cfg)
	{
		var registerPreviewHooks = cfg?.Homm3ImportPreviewHooks == true;
		TryRegisterReleaseFeature(log, "selected-unit HUD softlock suppressor", cfg?.Homm3ReleaseSelectedHud != false, () => Homm3ImportBhSelectedUnitHudFix.TryRegisterRelease(harmony, log));

		TryLoadTable(log);
		if (Entries.Count == 0)
		{
			log?.LogInfo("Homm3Import release full feature slice: no homm3_import.json entries; custom mesh features disabled.");
			return;
		}

		TryRegisterReleaseFeature(log, "ResManager GameObject lane", cfg?.Homm3ReleaseResManager != false, () => ResManagerGameObjectLaneHooks.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "battle pool", cfg?.Homm3ReleaseBattlePool != false, () => Homm3ImportBattlePoolHook.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "UnitView map swap", cfg?.Homm3ReleaseUnitView != false, () => Homm3ImportUnitViewHook.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "release battle visual", cfg?.Homm3ReleaseBattlePool != false, () => Homm3ImportReleaseBattleVisualHook.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "battle attack facing", cfg?.Homm3ReleaseBattlePool != false, () => Homm3BattleAttackFacingHook.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "release battle UI", cfg?.Homm3ReleaseBattleUi != false, () => Homm3ImportReleaseBattleUiHook.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "projectile config", cfg?.Homm3ReleaseProjectile != false, () => Homm3ProjectileConfigHook.RegisterRequiredReleaseSafeSlice(harmony, log));
		TryRegisterReleaseFeature(log, "narrow spawner", cfg?.Homm3ReleaseNarrowSpawner != false, () => Homm3ImportNarrowSpawnerHook.TryRegister(harmony, log));
		TryRegisterReleaseFeature(log, "map-object unit visual", cfg?.Homm3ReleaseMapObjectUnitVisual != false, () => Homm3MapObjectUnitVisualHook.RegisterRequiredReleaseSafeSlice(harmony, log));
		SetMapSquadRuntimeAttachEnabled(cfg?.Homm3ReleaseMapSquadVisualController == true, log);
		TryRegisterReleaseFeature(log, "map squad visual controller/runtime attach", cfg?.Homm3ReleaseMapSquadVisualController == true, () => Homm3MapSquadVisualControllerHook.RegisterRequiredReleaseSafeSlice(harmony, log));
		TryRegisterReleaseFeature(log, "tooltip portrait", cfg?.Homm3ReleaseTooltipPortrait != false, () => Homm3ImportTooltipPortraitHook.RegisterRequiredReleaseSafeSlice(harmony, log));
		TryRegisterReleaseFeature(log, "unit detail preview model", cfg?.Homm3ReleaseDetailPreview != false, () => Homm3ImportUnitPreviewModelHook.RegisterRequiredDetailWindowOnly(harmony, log));
		if (registerPreviewHooks)
		{
			TryRegisterReleaseFeature(log, "preview window", () => Homm3ImportPreviewWindowHook.TryRegister(harmony, log));
			TryRegisterReleaseFeature(log, "preview synthetic mesh", () => Homm3ImportPreviewSyntheticMeshHook.TryRegister(harmony, log));
			if (Homm3DiagnosticFlags.IsEnabled("homm3_preview_probe.flag"))
				Homm3ImportPreviewProbe.TryRun(log);
		}
		else
		{
			log?.LogInfo("Homm3Import release full feature slice: preview hooks skipped.");
		}

		log?.LogInfo("Homm3Import release full feature slice: registered custom mesh, battle, projectile, spawner, map-object, tooltip, and preview surfaces. Army-strip portraits stay on the release-safe remap.");
	}

	private static void TryRegisterReleaseFeature(ManualLogSource log, string featureName, bool enabled, Action register)
	{
		if (!enabled)
		{
			log?.LogInfo("Homm3Import release full feature slice: " + featureName + " skipped by bisection gate.");
			return;
		}

		TryRegisterReleaseFeature(log, featureName, register);
	}

	private static void TryRegisterReleaseFeature(ManualLogSource log, string featureName, Action register)
	{
		try
		{
			register();
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release full feature slice: " + featureName + " registration failed; continuing with remaining surfaces. " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static void SetMapSquadRuntimeAttachEnabled(bool enabled, ManualLogSource log)
	{
		Homm3MapSquadRuntimeAttachEnabled = enabled;
		log?.LogInfo(
			"Homm3Import release full feature slice: map squad runtime attach "
			+ (enabled ? "enabled by homm3ReleaseMapSquadVisualController." : "quarantined by homm3ReleaseMapSquadVisualController=false.")
		);
	}

	static void TryLoadTable(ManualLogSource log)
	{
		if (_loaded)
			return;
		_loaded = true;
		var path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "homm3_import.json");
		if (!File.Exists(path))
		{
			log?.LogInfo("Homm3Import: no homm3_import.json — lane B table swap disabled.");
			return;
		}

		try
		{
			var root = JObject.Parse(File.ReadAllText(path));
			var sub = TokenString(root["bundleSubdir"]);
			if (!string.IsNullOrWhiteSpace(sub))
				_bundleSubdir = sub.Trim().Replace('\\', '/').Trim('/');
			_battleWorldHeightPerHex = TokenPositiveFloat(root["battleWorldHeightPerHex"]);
			_adventureMapToBattleHeightRatio = TokenPositiveFloat(root["adventureMapToBattleHeightRatio"]);
			if (_battleWorldHeightPerHex.HasValue && !_adventureMapToBattleHeightRatio.HasValue)
				log?.LogError("Homm3Import: homm3_import.json declares battleWorldHeightPerHex but no adventureMapToBattleHeightRatio; owned-skinned map squads will refuse the hex fit and use the donor height.");
			// Il2Cpp: `token as JArray` is often null even for JSON arrays — use Type and enumerate JToken.
			var entriesToken = root["entries"];
			if (entriesToken == null || entriesToken.Type != JTokenType.Array)
			{
				log?.LogWarning("Homm3Import: homm3_import.json has no entries array.");
				return;
			}

			JArray arr;
			try
			{
				arr = JArray.Parse(entriesToken.ToString());
			}
			catch (Exception ex)
			{
				log?.LogError("Homm3Import: could not parse entries: " + ex.Message);
				return;
			}

			for (var i = 0; i < arr.Count; i++)
			{
				var t = arr[i];
				if (t == null || t.Type != JTokenType.Object)
					continue;
				var battle = NormUnits(TokenString(t["battleResPath"]));
				var map = NormUnits(TokenString(t["mapResPath"]));
				if (string.IsNullOrEmpty(battle) || string.IsNullOrEmpty(map))
				{
					log?.LogWarning("Homm3Import: skipping entry " + i + " because battleResPath/mapResPath is missing.");
					continue;
				}
				var bundle = TokenString(t["bundleName"])?.Trim();
				var bPrefab = TokenString(t["battlePrefabAssetPath"])?.Trim();
				var mPrefab = TokenString(t["mapPrefabAssetPath"])?.Trim();
				var battlePresentation = NormUnits(TokenString(t["battlePresentationResPath"]));
				var mapShell = NormUnits(TokenString(t["mapShellResPath"]));
				if (string.IsNullOrEmpty(bundle) || string.IsNullOrEmpty(bPrefab) || string.IsNullOrEmpty(mPrefab))
				{
					log?.LogWarning("Homm3Import: skipping entry " + i + " because bundleName/prefab path is missing.");
					continue;
				}
				List<string> gameSids = null;
				var gus = t["gameUnitSids"];
				if (gus != null && gus.Type == JTokenType.Array)
				{
					JArray ga = null;
					try
					{
						ga = JArray.Parse(gus.ToString());
					}
					catch (Exception ex)
					{
						log?.LogWarning("Homm3Import: entry " + i + " has unparseable gameUnitSids: " + ex.Message);
					}

					if (ga != null && ga.Count > 0)
					{
						gameSids = new List<string>();
						for (var j = 0; j < ga.Count; j++)
						{
							var x = ga[j];
							if (x == null || x.Type != JTokenType.String)
								continue;
							var s = TokenString(x);
							if (string.IsNullOrWhiteSpace(s))
								continue;
							gameSids.Add(s.Trim());
						}

						if (gameSids.Count == 0)
							gameSids = null;
					}
				}

				var entry = new Entry
				{
					BattleResPath = battle,
					MapResPath = map,
					BattleNorm = battle,
					MapNorm = map,
					BattlePresentationResPath = battlePresentation,
					BattlePresentationNorm = battlePresentation,
					MapShellResPath = mapShell,
					MapShellNorm = mapShell,
					PreviewDonorSid = TokenString(t["previewDonorSid"])?.Trim(),
					SwapAdventureMap = TokenBool(t["swapAdventureMap"], true),
					BundleName = bundle,
					BattlePrefabAssetPath = bPrefab.Replace('\\', '/'),
					MapPrefabAssetPath = mPrefab.Replace('\\', '/'),
					AudioStemPrefix = TokenString(t["audioStemPrefix"])?.Trim(),
					GameUnitSids = gameSids,
					BattleHeightHexes = TokenPositiveFloat(t["battleHeightHexes"])
				};
				if (entry.BattleHeightHexes.HasValue && !_battleWorldHeightPerHex.HasValue)
					log?.LogError("Homm3Import: entry " + i + " declares battleHeightHexes but the table has no battleWorldHeightPerHex; its battle fit will fall back to the donor height.");
				if (t["battleMoveStrideBindUnits"] != null || t["battleMoveCycleSeconds"] != null || t["battleStrideMatch"] != null)
					log?.LogError("Homm3Import: entry " + i + " carries retired battleMoveStrideBindUnits/battleMoveCycleSeconds/battleStrideMatch; the runtime no longer rewrites moveSpeed (see docs/homm3_stride_match.md) and ignores them.");
				Entries.Add(entry);
				IndexEntry(entry);
			}

			log?.LogInfo("Homm3Import: loaded " + Entries.Count + " entr(y/ies) from homm3_import.json.");
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3Import: failed to parse homm3_import.json: " + ex.Message);
		}
	}

	static void IndexEntry(Entry entry)
	{
		if (entry == null)
			return;
		AddTemplateLookup(entry.BattleNorm, entry, useMapTemplate: false);
		if (entry.SwapAdventureMap)
			AddTemplateLookup(entry.MapNorm, entry, useMapTemplate: true);
		AddFirst(BattleEntriesByUnitsPath, entry.BattleNorm, entry);
		AddFirst(MapEntriesByUnitsPath, entry.MapNorm, entry);
		if (entry.SwapAdventureMap)
			AddFirst(SwappableMapEntriesByUnitsPath, entry.MapNorm, entry);
		AddLeafIndex(LeafSid(entry.BattleNorm), entry);
		AddLeafIndex(LeafSid(entry.MapNorm), entry);
		if (entry.GameUnitSids == null)
			return;
		for (var i = 0; i < entry.GameUnitSids.Count; i++)
			AddFirst(EntriesByGameUnitSid, entry.GameUnitSids[i], entry);
	}

	static Entry TryEntryByBundleName(string bundleName)
	{
		if (string.IsNullOrEmpty(bundleName))
			return null;
		for (var i = 0; i < Entries.Count; i++)
		{
			var e = Entries[i];
			if (e != null && string.Equals(e.BundleName, bundleName, StringComparison.OrdinalIgnoreCase))
				return e;
		}

		return null;
	}

	static void AddFirst(Dictionary<string, Entry> dict, string key, Entry entry)
	{
		if (dict == null || entry == null || string.IsNullOrEmpty(key) || dict.ContainsKey(key))
			return;
		dict[key] = entry;
	}

	static void AddLeafIndex(string sid, Entry entry)
	{
		if (entry == null || string.IsNullOrEmpty(sid))
			return;
		if (!EntriesByLeafSid.TryGetValue(sid, out var list))
		{
			list = new List<Entry>();
			EntriesByLeafSid[sid] = list;
		}

		if (!list.Contains(entry))
			list.Add(entry);
	}

	static void AddTemplateLookup(string key, Entry entry, bool useMapTemplate)
	{
		if (entry == null || string.IsNullOrEmpty(key) || TemplateLookupByUnitsPath.ContainsKey(key))
			return;
		TemplateLookupByUnitsPath[key] = new TemplateLookup { Entry = entry, UseMapTemplate = useMapTemplate };
	}

	internal static void RequireLoadedEntriesForReleaseSafeFeature(ManualLogSource log, string featureName)
	{
		TryLoadTable(log);
		if (Entries.Count > 0)
			return;
		throw new InvalidOperationException(
			"required HoMM3 import feature '"
			+ (string.IsNullOrWhiteSpace(featureName) ? "unknown" : featureName)
			+ "' has no loaded homm3_import.json entries.");
	}

	static string TokenString(JToken token)
	{
		if (token == null || token.Type == JTokenType.Null || token.Type == JTokenType.Undefined)
			return null;
		return token.ToString();
	}

	static bool TokenBool(JToken token, bool fallback)
	{
		var s = TokenString(token);
		if (string.IsNullOrWhiteSpace(s))
			return fallback;
		if (string.Equals(s, "true", StringComparison.OrdinalIgnoreCase))
			return true;
		if (string.Equals(s, "false", StringComparison.OrdinalIgnoreCase))
			return false;
		return fallback;
	}

	/// <summary>Finite positive number or null. Non-numeric / non-positive values are treated as absent (the validator rejects them before deploy).</summary>
	static float? TokenPositiveFloat(JToken token)
	{
		var s = TokenString(token);
		if (string.IsNullOrWhiteSpace(s))
			return null;
		if (!Homm3JsonNumber.TryParseFloat(s, out var value))
			return null;
		if (float.IsNaN(value) || float.IsInfinity(value) || value <= 0f)
			return null;
		return value;
	}

	static string NormUnits(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return null;
		var p = raw.Trim().Replace('\\', '/').TrimEnd('/');


		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		if (!p.StartsWith("units/", StringComparison.Ordinal))
			p = "units/" + p;
		return p;
	}

	internal static bool IsSyntheticHomm3ImportUnitsPath(string unitsPath)
	{
		var p = NormUnits(unitsPath);
		return p != null && p.StartsWith("units/homm3_import/", StringComparison.Ordinal);
	}

	internal static bool IsSyntheticHomm3ImportEntry(Entry e) =>
		e != null && (IsSyntheticHomm3ImportUnitsPath(e.BattleNorm) || IsSyntheticHomm3ImportUnitsPath(e.MapNorm));

	internal static bool LooksLikeHomm3NativeShellMapPrefab(GameObject go)
	{
		if (!go || go.transform == null)
			return false;
		var n = go.name ?? string.Empty;
		return n.EndsWith("_native_shell", StringComparison.Ordinal)
		       || n.EndsWith("_native_shell(Clone)", StringComparison.Ordinal);
	}

	internal static bool TryGetTemplateForUnitsPath(string unitsPath, ManualLogSource log, out GameObject template)
	{
		template = null;
		TryLoadTable(log);
		if (string.IsNullOrEmpty(unitsPath))
			return false;
		var u = unitsPath.Trim().Replace('\\', '/');
		if (!TemplateLookupByUnitsPath.TryGetValue(u, out var lookup) || lookup?.Entry == null)
			return false;
		return lookup.UseMapTemplate
			? TryGetMapTemplate(lookup.Entry, log, out template)
			: TryGetBattleTemplate(lookup.Entry, log, out template);
	}

	/// <summary><c>true</c> when <paramref name="unitsPath"/> matches a table row’s adventure <c>mapResPath</c> with swap enabled.</summary>
	internal static bool IsAdventureMapUnitsPath(string unitsPath)
	{
		TryLoadTable(null);
		if (string.IsNullOrEmpty(unitsPath))
			return false;
		var u = unitsPath.Trim().Replace('\\', '/');
		return SwappableMapEntriesByUnitsPath.ContainsKey(u);
	}

	internal static bool EntryHasGameUnitSidGate(Entry e) =>
		e?.GameUnitSids != null && e.GameUnitSids.Count > 0;

	internal static bool EntryAllowsGameUnitSid(Entry e, string unitSid)
	{
		if (!EntryHasGameUnitSidGate(e))
			return true;
		if (string.IsNullOrWhiteSpace(unitSid))
			return false;
		var sid = unitSid.Trim();
		foreach (var g in e.GameUnitSids)
			if (string.Equals(g, sid, StringComparison.Ordinal))
				return true;
		return false;
	}

	internal static bool TryGetBattlePresentationTemplate(Entry e, ManualLogSource log, out GameObject template)
	{
		template = null;
		if (e == null || string.IsNullOrEmpty(e.BattlePresentationNorm))
			return false;
		return TryLoadResManagerGameObject(e.BattlePresentationNorm, log, out template) && template;
	}

	/// <summary>
	/// Cache-only presentation template lookup. Combat Init must NOT ResManager-load the
	/// presentation donor: the release hook observed a hard freeze when the re-entrant
	/// ResManager.Get ran mid battle-load (log stopped right after the ResManager type probe,
	/// before any Hex/Lit resolution line). Callers on the combat path may only use a donor
	/// that a safe context (preview UI) already loaded and cached.
	/// </summary>
	internal static bool TryGetCachedBattlePresentationTemplate(Entry e, ManualLogSource log, out GameObject template)
	{
		template = null;
		if (e == null || string.IsNullOrEmpty(e.BattlePresentationNorm))
			return false;
		if (ResManagerGameObjectCache.TryGetValue(e.BattlePresentationNorm, out var cached) && cached)
		{
			template = cached;
			return true;
		}
		return false;
	}

	private static readonly Dictionary<string, GameObject> ResManagerGameObjectCache =
		new Dictionary<string, GameObject>(StringComparer.Ordinal);

	internal static bool TryGetMapShellTemplate(Entry e, ManualLogSource log, out GameObject template)
	{
		template = null;
		if (e == null || string.IsNullOrEmpty(e.MapShellNorm))
			return false;
		return TryLoadResManagerGameObject(e.MapShellNorm, log, out template) && template;
	}

	internal static bool TryLoadMapShellVanillaDonor(Entry e, ManualLogSource log, out GameObject vanillaDonor) =>
		TryGetMapShellTemplate(e, log, out vanillaDonor);

	internal static void TryNoteResManagerInstance(object instance)
	{
		if (instance != null)
			_resManagerInstanceFromHook = instance;
	}

	internal static void RegisterNativeResManagerCacheInterest(string resPath)
	{
		if (!string.IsNullOrWhiteSpace(resPath))
			NativeResManagerCacheInterest.Add(resPath.Trim());
	}

	internal static void TryCacheNativeResManagerGameObject(string resPath, GameObject go)
	{
		if (!go || string.IsNullOrWhiteSpace(resPath))
			return;
		var key = resPath.Trim();
		if (!NativeResManagerCacheInterest.Contains(key))
			return;
		ResManagerGameObjectCache[key] = go;
	}

	internal static bool TryGetCachedNativeResManagerGameObject(string resPath, out GameObject go)
	{
		go = null;
		if (string.IsNullOrWhiteSpace(resPath))
			return false;
		return ResManagerGameObjectCache.TryGetValue(resPath.Trim(), out go) && go;
	}

	/// <summary>
	/// Direct ResManager.Get via MethodInfo.Invoke. Homm3MeshFx must never call this:
	/// Golden Era AccessViolation in il2cpp_string_new_utf16 (Harmony DMD) from
	/// LateUpdate, MapObject.Init, and ScMainMenu.Start, including Get of objects/fx/fx_map_fire.
	/// Use <see cref="TryLoadNativeResManagerGameObjectIl2Cpp"/> instead.
	/// </summary>
	internal static bool TryLoadNativeResManagerGameObject(string resPath, ManualLogSource log, out GameObject go)
	{
		return TryLoadResManagerGameObject(resPath, log, out go);
	}

	/// <summary>
	/// Load a ResManager GameObject the same way generated Il2Cpp stubs do:
	/// marshal the path with <see cref="IL2CPP.ManagedStringToIl2Cpp"/> then
	/// <see cref="IL2CPP.il2cpp_runtime_invoke"/> the inflated public static
	/// <c>ResManager.Get&lt;GameObject&gt;</c> — the game's own entry point, which
	/// searches loaded AssetBundles and then falls back to <c>Resources.Load</c>.
	/// <paramref name="resPath"/> is a Resources path (ResourceManager container key,
	/// e.g. <c>units/nature/1prefabs/phoenix</c>). Do not MethodInfo.Invoke the
	/// Harmony DMD. Do not call from MapObject.Init, ScMainMenu.Start, or combat
	/// ecd.Init — Homm3MeshFx uses LateUpdate only.
	/// </summary>
	internal static unsafe bool TryLoadNativeResManagerGameObjectIl2Cpp(
		string resPath,
		ManualLogSource log,
		out GameObject go)
	{
		go = null;
		if (string.IsNullOrWhiteSpace(resPath))
			return false;
		var key = resPath.Trim();
		if (TryGetCachedNativeResManagerGameObject(key, out go) && go)
			return true;
		if (!TryEnsureResManagerNativeGetPtr(log))
			return false;

		try
		{
			// Static Get<T>: no receiver. It creates the ResManager singleton itself if needed.
			var arg0 = IL2CPP.ManagedStringToIl2Cpp(key);
			var args = stackalloc IntPtr[1];
			args[0] = arg0;
			var exception = IntPtr.Zero;
			var resultPtr = IL2CPP.il2cpp_runtime_invoke(
				_resManagerGetNativeMethodPtr,
				IntPtr.Zero,
				(void**)args,
				ref exception);
			if (exception != IntPtr.Zero)
			{
				if (_loggedResManagerLoadFail < 12)
				{
					_loggedResManagerLoadFail++;
					var detail = "native exception";
					try
					{
						Il2CppInterop.Runtime.Il2CppException.RaiseExceptionIfNecessary(exception);
					}
					catch (Exception ex)
					{
						detail = ex.Message;
					}
					log?.LogWarning(
						"Homm3Import: Il2Cpp ResManager Get failed for '" + key + "': " + detail);
				}
				return false;
			}
			if (resultPtr == IntPtr.Zero)
			{
				if (_loggedResManagerNullResult < 12)
				{
					_loggedResManagerNullResult++;
					log?.LogWarning(
						"Homm3Import: Il2Cpp ResManager.Get<GameObject>('"
						+ key
						+ "') returned null: no AssetBundle entry and no Resources asset at that path.");
				}
				return false;
			}
			go = Il2CppObjectPool.Get<GameObject>(resultPtr);
			if (go)
				ResManagerGameObjectCache[key] = go;
			return go;
		}
		catch (Exception ex)
		{
			if (_loggedResManagerLoadFail < 12)
			{
				_loggedResManagerLoadFail++;
				log?.LogWarning(
					"Homm3Import: Il2Cpp ResManager Get failed for '" + key + "': " + ex.Message);
			}
			return false;
		}
	}

	private static bool TryEnsureResManagerNativeGetPtr(ManualLogSource log)
	{
		if (_resManagerGetNativeMethodPtr != IntPtr.Zero)
			return true;
		if (!TryEnsureResManagerGameObjectInvoker(log) || _resManagerType == null)
			return false;

		TryInitializeIl2CppType(_resManagerType);
		TryInitializeIl2CppType(typeof(GameObject));

		// Exactly the public static Get<GameObject> store: no name-scan fallback. The private
		// object loader (GetAssetFromBundle) only sees AssetBundles and returns null for every
		// vanilla prefab, which live in resources.assets.
		Type store = null;
		try
		{
			store = _resManagerType.GetNestedType(
				GameSymbols.ImportVisuals.ResManagerStaticGetGenericStore,
				BindingFlags.Public | BindingFlags.NonPublic);
		}
		catch
		{
		}
		if (TryReadClosedGenericStorePointer(store, log, out var storePtr))
		{
			_resManagerGetNativeMethodPtr = storePtr;
			return true;
		}

		log?.LogError(
			"Homm3Import: ResManager static Get<GameObject> MethodInfoStore '"
			+ GameSymbols.ImportVisuals.ResManagerStaticGetGenericStore
			+ "' Pointer was not found; refuse MethodInfo.Invoke and the bundle-only loader.");
		return false;
	}

	private static bool TryReadClosedGenericStorePointer(Type storeType, ManualLogSource log, out IntPtr pointer)
	{
		pointer = IntPtr.Zero;
		if (storeType == null)
			return false;
		Type closed = storeType;
		try
		{
			if (storeType.IsGenericTypeDefinition)
				closed = storeType.MakeGenericType(typeof(GameObject));
		}
		catch
		{
			return false;
		}

		TryInitializeIl2CppType(closed);
		try
		{
			RuntimeHelpers.RunClassConstructor(closed.TypeHandle);
		}
		catch
		{
		}

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		try
		{
			var field = closed.GetField("Pointer", flags);
			if (field == null || field.FieldType != typeof(IntPtr))
				return false;
			pointer = (IntPtr)field.GetValue(null);
			if (pointer == IntPtr.Zero)
				return false;
			log?.LogInfo(
				"Homm3Import: ResManager Get<GameObject> native ptr from '"
				+ closed.FullName
				+ ".Pointer'.");
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			var storeType = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(storeType.TypeHandle);
		}
		catch
		{
		}
	}

	private static bool TryLoadResManagerGameObject(string unitsPath, ManualLogSource log, out GameObject go)
	{
		go = null;
		if (string.IsNullOrEmpty(unitsPath) || !TryEnsureResManagerGameObjectInvoker(log))
			return false;

		try
		{
			object result;
			if (_resManagerGetGameObjectIsStatic)
				result = _resManagerGetGameObject.Invoke(null, new object[] { unitsPath });
			else
			{
				var instance = TryFindResManagerInstance();
				if (instance == null)
				{
					if (_loggedResManagerNoInstance < 4)
					{
						_loggedResManagerNoInstance++;
						log?.LogWarning("Homm3Import: ResManager.Get<GameObject> is instance method but no instance is available for '" + unitsPath + "'.");
					}

					return false;
				}

				result = _resManagerGetGameObject.Invoke(instance, new object[] { unitsPath });
			}

			go = result as GameObject;
		if (go)
			ResManagerGameObjectCache[unitsPath] = go;
		return go;
		}
		catch (Exception ex)
		{
			if (_loggedResManagerLoadFail < 12)
			{
				_loggedResManagerLoadFail++;
				log?.LogWarning("Homm3Import: ResManager.Get<GameObject> failed for '" + unitsPath + "': " + ex.Message);
			}

			return false;
		}
	}

	private static bool TryEnsureResManagerGameObjectInvoker(ManualLogSource log)
	{
		if (_resManagerGetGameObject != null)
			return true;

		try
		{
			var asm = typeof(ObjCityConfig).Assembly;
			_resManagerType = ResManagerInteropProbe.TryResolveResManagerType(asm, msg => log?.LogWarning("Homm3Import: " + msg));
			if (_resManagerType == null)
				return false;
			var openGeneric = ResManagerInteropProbe.FindResManagerGetOpenGeneric(_resManagerType);
			if (openGeneric == null)
				return false;
			_resManagerGetGameObject = openGeneric.MakeGenericMethod(typeof(GameObject));
			_resManagerGetGameObjectIsStatic = _resManagerGetGameObject.IsStatic;
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedResManagerLoadFail < 12)
			{
				_loggedResManagerLoadFail++;
				log?.LogWarning("Homm3Import: ResManager.Get<GameObject> init failed: " + ex.Message);
			}

			return false;
		}
	}

	private static object TryFindResManagerInstance()
	{
		if (_resManagerType == null)
			return null;
		if (_resManagerInstanceFromHook != null
		    && (_resManagerType.IsInstanceOfType(_resManagerInstanceFromHook)
		        || _resManagerType.IsAssignableFrom(_resManagerInstanceFromHook.GetType())))
			return _resManagerInstanceFromHook;

		const BindingFlags bf = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var p in _resManagerType.GetProperties(bf))
		{
			try
			{
				if (p.GetIndexParameters().Length != 0)
					continue;
				var v = p.GetValue(null);
				if (v != null && _resManagerType.IsInstanceOfType(v))
					return v;
			}
			catch
			{
				// ignored
			}
		}

		foreach (var f in _resManagerType.GetFields(bf))
		{
			try
			{
				var v = f.GetValue(null);
				if (v != null && _resManagerType.IsInstanceOfType(v))
					return v;
			}
			catch
			{
				// ignored
			}
		}

		return null;
	}

	/// <summary>
	/// Layer/sorting + hex/Lit donor rebind — shared by <see cref="Homm3ImportUnitViewHook"/>,
	/// <see cref="Homm3ImportResManagerHook"/>, and <see cref="Homm3ImportNarrowSpawnerHook"/> (vanilla must still exist when hex rebind runs).
	/// </summary>
	internal static void FinishHomm3MapPrefabForAdventure(GameObject vanilla, GameObject template, ManualLogSource log)
	{
		FinishHomm3MapPrefabForAdventure(vanilla, template, TryEntryForMapTemplate(template), log);
	}

	internal static void FinishHomm3MapPrefabForAdventure(GameObject vanilla, GameObject template, Entry entry, ManualLogSource log)
	{
		if (!template)
			return;
		if (!_loggedMapFinishSignature)
		{
			_loggedMapFinishSignature = true;
			log?.LogInfo("Homm3Import: map finish signature v9-array-slice-hexlit (0.125 scale + MapIdle/array + slice-to-Hex/Lit on native shell).");
		}
		if (vanilla)
		{
			var matched = EsquireBattleVisualPresentation.SyncAdventureMapPrefabPresentationFromVanilla(vanilla, template);
			if (matched == 0)
			{
				EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(vanilla, template);
				EsquireBattleVisualPresentation.SyncMapRenderersSortingDepthFirstFallback(vanilla, template);
			}
			var renderDonor = EsquireBattleVisualPresentation.TryFindDominantRenderable(vanilla);
			if (renderDonor)
			{
				LogMapRendererFlagSync(renderDonor, template, before: true, log);
				EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(renderDonor, template);
				LogMapRendererFlagSync(renderDonor, template, before: false, log);
			}
		}

		var mapLabSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		var mapArray = !string.IsNullOrEmpty(mapLabSid)
		               && Homm3BattleArrayBillboard.IsMapArrayPilotReady(mapLabSid, entry, log);
		var scopedFrameMaterials = TryGetScopedMapFrameMaterials(entry, log);
		if (!mapArray && EsquirePikemanVisuals.IsMapBillboardSpritesDefaultMode())
		{
			EsquirePikemanVisuals.TryRestoreHomm3MapMaterialsToSpritesDefault(template, scopedFrameMaterials, log);
		}
		else
		{
			EsquirePikemanVisuals.TryRemoveHomm3MapBillboardFogSync(template, log);
			if (vanilla && !mapArray)
				EsquirePikemanVisuals.TryRebindHomm3MapMaterialsFromVanilla(vanilla, template, scopedFrameMaterials, log);
			// Map-array pilots: array material stays on hidden homm3_map_visual; Hex/Lit slice bridge owns shell draw.
		}

		NormalizeAdventureMapPrefabBillboardScale(template, log);

		if (!mapArray)
			TryApplyMapAdventureAnimatorPlaybackTiming(template, entry, log);
	}

	/// <summary>
	/// Town-style hex-lit billboards apply <see cref="TownStyleUnitBillboardScale"/> to authored 16x map quads.
	/// The map.prefab route must do the same or RIFE/map-array units tower over towns.
	/// </summary>
	internal static void ClearAdventureMapPrefabScaleNormalizationState()
	{
		MapPrefabScaleNormalizedRootIds.Clear();
		ResetMapLoadProfileCounters();
		_mapPrefabScaleLogRemaining = 8;
	}

	internal static void ResetMapLoadProfileCounters()
	{
		_mapLoadProfileShells = 0;
		_mapLoadProfileTownBillboardAttempts = 0;
		_mapLoadProfileTownBillboardSuccesses = 0;
		_mapLoadProfileDiskFrameLoads = 0;
		_mapLoadProfileIdleFrameLoads = 0;
		_mapLoadProfileIdleFrameScans = 0;
		_mapLoadProfilePostconditionChecks = 0;
		_mapLoadProfileLastReportShells = 0;
		_mapLoadProfileShellTicks = 0;
		_mapLoadProfileTownBillboardTicks = 0;
		_mapLoadProfileDiskFrameTicks = 0;
		_mapLoadProfileIdleFrameLoadTicks = 0;
		_mapLoadProfileIdleFrameScanTicks = 0;
		_mapLoadProfilePostconditionTicks = 0;
	}

	internal static void NormalizeAdventureMapPrefabBillboardScale(GameObject mapRoot, ManualLogSource log)
	{
		if (!mapRoot)
			return;
		if (!MapPrefabScaleNormalizedRootIds.Add(mapRoot.GetInstanceID()))
			return;

		var scaledQuads = 0;
		foreach (var t in mapRoot.GetComponentsInChildren<Transform>(true))
		{
			if (!t)
				continue;
			if (!string.Equals(t.name, "quad", StringComparison.OrdinalIgnoreCase))
				continue;
			var ls = t.localScale;
			if (ls.x < AuthoredMapQuadOversizeThreshold && ls.y < AuthoredMapQuadOversizeThreshold)
				continue;
			var factor = TownStyleUnitBillboardScale;
			t.localScale = new Vector3(ls.x * factor, ls.y * factor, ls.z);
			var lp = t.localPosition;
			t.localPosition = new Vector3(lp.x * factor, lp.y * factor, lp.z);
			scaledQuads++;
		}

		if (scaledQuads > 0 && _mapPrefabScaleLogRemaining > 0)
		{
			_mapPrefabScaleLogRemaining--;
			log?.LogInfo(
				"Homm3Import: adventure map prefab billboard scale x"
				+ TownStyleUnitBillboardScale.ToString("0.###")
				+ " on "
				+ scaledQuads
				+ " quad(s) under '"
				+ (mapRoot.name ?? "?")
				+ "'.");
		}
	}

	internal static GameObject CreateNativeShellMapPrefabForAdventure(
		GameObject vanilla,
		GameObject homm3Template,
		Entry entry,
		ManualLogSource log)
	{
		Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.enter", vanilla, "entry=" + (entry?.MapNorm ?? entry?.BattlePrefabAssetPath ?? "?"), census: true);
		if (!vanilla || !homm3Template)
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.no-vanilla-or-template", homm3Template);
			return homm3Template;
		}

		var profileStart = Stopwatch.GetTimestamp();
		GameObject shell = null;
		GameObject visual = null;
		try
		{
			var mapArrayPilot = IsMapArrayPilotEntry(entry, log);
			shell = mapArrayPilot
				? CreateLightweightMapArrayShell(vanilla, homm3Template)
				: UnityEngine.Object.Instantiate(vanilla);
			if (!shell)
			{
				Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.instantiate-shell-miss", homm3Template);
				return homm3Template;
			}
			shell.name = (homm3Template.name ?? "homm3_map") + "_native_shell";
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.shell-instantiated", shell, mapArrayPilot ? "lightweightMapArray=true" : "lightweightMapArray=false");

			if (IsHomm3SkinnedBattleInstance(homm3Template))
			{
				RemoveTownStyleBillboardFromShell(shell);
				visual = UnityEngine.Object.Instantiate(homm3Template);
				if (!visual)
				{
					UnityEngine.Object.Destroy(shell);
					Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.skinned-visual-instantiate-miss", homm3Template);
					return homm3Template;
				}
				visual.name = MapPrefabVisualChildName;
				visual.transform.SetParent(shell.transform, false);
				visual.transform.SetSiblingIndex(shell.transform.childCount - 1);
				visual.transform.localPosition = Vector3.zero;
				visual.transform.localRotation = Quaternion.identity;
				FinishOwnedSkinnedAdventureMapPresentation(shell, visual, homm3Template, vanilla, entry, log, fitScale: true);
				TryAttachMapSquadRuntimeAttach(shell, log);
				PrepareReturnedNativeShellTemplate(shell, log);
				Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.skinned-idle-return", shell, census: true);
				return shell;
			}

			// RIFE / map-array units must use map.prefab MapIdle (or Texture2DArray), not town-style disk tick.
			// Town-style wins first otherwise and never reaches playback-timing / array attach.
			if (!ShouldUseMapPrefabMapIdleAnimator(entry, log)
			    && TryApplyTownStyleUnitBillboard(shell, homm3Template, entry, log))
			{
				Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.town-style-return", shell, census: true);
				TryAttachMapSquadRuntimeAttach(shell, log);
				PrepareReturnedNativeShellTemplate(shell, log);
				return shell;
			}

			RemoveTownStyleBillboardFromShell(shell);
			visual = UnityEngine.Object.Instantiate(homm3Template);
			if (!visual)
			{
				UnityEngine.Object.Destroy(shell);
				Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.visual-instantiate-miss", homm3Template);
				return homm3Template;
			}
			visual.name = MapPrefabVisualChildName;
			visual.transform.SetParent(shell.transform, false);
			// UnitViewConfig-driven map setup may scale the first child. Keep the vanilla child order intact
			// and append the HoMM3 visual so it does not receive an extra engine scale pass.
			visual.transform.SetSiblingIndex(shell.transform.childCount - 1);
			visual.transform.localPosition = Vector3.zero;
			visual.transform.localRotation = Quaternion.identity;
			visual.transform.localScale = Vector3.one;
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.visual-attached", visual, census: true);

			FinishHomm3MapPrefabForAdventure(vanilla, visual, entry, log);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.finish-homm3-visual", visual);
			EsquirePikemanVisuals.EnsureHomm3NativeShellRendererTransplantSyncTypeRegistered(log);
			TryAttachMapArrayBillboardOnShell(shell, visual, entry, log);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.after-array-attach", shell);
			TryFinalizeNativeShellMapPresentation(shell, visual, vanilla, entry, log);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.after-finalize", shell, census: true);

			if (_nativeShellDiagRemaining > 0)
			{
				_nativeShellDiagRemaining--;
				log?.LogInfo(
					"Homm3Import: native-shell map swap vanillaRoot='"
					+ (vanilla.name ?? "?")
					+ "' shell='"
					+ (shell.name ?? "?")
					+ "' visualRenderers="
					+ visual.GetComponentsInChildren<Renderer>(true).Length
					+ " nativeDriverRenderers="
					+ CountNativeDriverRenderers(shell, visual.transform)
					+ " shellComponents="
					+ shell.GetComponents<Component>().Length
					+ ".");
			}

			TryAttachMapSquadRuntimeAttach(shell, log);
			Homm3BattleBillboardCameraFacing.TryAttach(shell, log);
			PrepareReturnedNativeShellTemplate(shell, log);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.create.return-shell", shell);
			return shell;
		}
		catch (Exception ex)
		{
			Homm3MapLoadFlightRecorder.Mark("native-shell.create.exception", ex.GetType().FullName + ": " + ex.Message, census: true);
			log?.LogWarning("Homm3Import: native-shell map swap failed; falling back to direct template: " + ex);
			if (visual)
				UnityEngine.Object.Destroy(visual);
			if (shell)
				UnityEngine.Object.Destroy(shell);
			return homm3Template;
		}
		finally
		{
			_mapLoadProfileShells++;
			_mapLoadProfileShellTicks += Stopwatch.GetTimestamp() - profileStart;
			MaybeLogMapLoadProfile(log, force: false);
		}
	}

	static bool IsMapArrayPilotEntry(Entry entry, ManualLogSource log)
	{
		if (IsOwnedSkinnedBattleEntry(entry))
			return false;
		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		return !string.IsNullOrEmpty(labSid)
		       && Homm3BattleArrayBillboard.IsMapArrayPilotReady(labSid, entry, log);
	}

	static GameObject CreateLightweightMapArrayShell(GameObject vanilla, GameObject homm3Template)
	{
		var shell = new GameObject((homm3Template ? homm3Template.name : "homm3_map") + "_native_shell");
		if (vanilla)
			shell.layer = vanilla.layer;
		var driver = new GameObject("Scale_roll_pos");
		driver.layer = shell.layer;
		driver.transform.SetParent(shell.transform, false);
		return shell;
	}

	internal static bool TryCreateDirectMapArrayShellPrefabForAdventure(
		Entry entry,
		ManualLogSource log,
		out GameObject shell)
	{
		shell = null;
		if (entry == null || Homm3MapLoadFlightRecorder.DisableMapArrayPilots)
			return false;
		if (!IsMapArrayPilotEntry(entry, log))
			return false;
		if (!TryGetMapTemplate(entry, log, out var homm3Template) || !homm3Template)
			return false;
		if (!TryGetDirectMapArrayDonorMaterial(entry, log, out var donorMaterial) || !donorMaterial)
			return false;

		var profileStart = Stopwatch.GetTimestamp();
		GameObject visual = null;
		try
		{
			shell = CreateLightweightMapArrayShell(null, homm3Template);
			if (!shell)
				return false;
			shell.name = (homm3Template.name ?? "homm3_map") + "_native_shell";
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.direct-map-array.shell-created", shell, "entry=" + (entry.MapNorm ?? entry.BattlePrefabAssetPath ?? "?"), census: true);

			visual = UnityEngine.Object.Instantiate(homm3Template);
			if (!visual)
			{
				UnityEngine.Object.Destroy(shell);
				shell = null;
				return false;
			}
			visual.name = MapPrefabVisualChildName;
			visual.transform.SetParent(shell.transform, false);
			visual.transform.SetSiblingIndex(shell.transform.childCount - 1);
			visual.transform.localPosition = Vector3.zero;
			visual.transform.localRotation = Quaternion.identity;
			visual.transform.localScale = Vector3.one;

			FinishHomm3MapPrefabForAdventure(null, visual, entry, log);
			EsquirePikemanVisuals.EnsureHomm3NativeShellRendererTransplantSyncTypeRegistered(log);
			TryAttachMapArrayBillboardOnShell(shell, visual, entry, log);
			if (!TryFinalizeNativeShellMapPresentation(shell, visual, null, entry, log, donorMaterial))
			{
				UnityEngine.Object.Destroy(visual);
				UnityEngine.Object.Destroy(shell);
				visual = null;
				shell = null;
				return false;
			}
			TryAttachMapSquadRuntimeAttach(shell, log);
			Homm3BattleBillboardCameraFacing.TryAttach(shell, log);
			PrepareReturnedNativeShellTemplate(shell, log);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.direct-map-array.return-shell", shell, census: true);
			return true;
		}
		catch (Exception ex)
		{
			Homm3MapLoadFlightRecorder.Mark("native-shell.direct-map-array.exception", ex.GetType().FullName + ": " + ex.Message, census: true);
			log?.LogWarning("Homm3Import: direct map-array shell failed; using native UnitView loader: " + ex.Message);
			if (visual)
				UnityEngine.Object.Destroy(visual);
			if (shell)
				UnityEngine.Object.Destroy(shell);
			shell = null;
			return false;
		}
		finally
		{
			_mapLoadProfileShells++;
			_mapLoadProfileShellTicks += Stopwatch.GetTimestamp() - profileStart;
			MaybeLogMapLoadProfile(log, force: false);
		}
	}

	static bool TryGetDirectMapArrayDonorMaterial(Entry entry, ManualLogSource log, out Material donorMaterial)
	{
		donorMaterial = null;
		var cacheKey = entry?.MapShellNorm;
		if (!string.IsNullOrEmpty(cacheKey)
		    && DirectMapArrayDonorMaterialsByShell.TryGetValue(cacheKey, out var cached)
		    && cached)
		{
			donorMaterial = cached;
			return true;
		}

		if (entry == null || string.IsNullOrEmpty(entry.MapShellNorm))
			return false;
		if (EsquirePikemanVisuals.TryFindLoadedUnitStyleHexLitMapDonor(log, out donorMaterial) && donorMaterial)
		{
			if (EsquirePikemanVisuals.IsHexLitMaterialForRuntimeSync(donorMaterial))
			{
				DirectMapArrayDonorMaterialsByShell[entry.MapShellNorm] = donorMaterial;
				return true;
			}
			if (DirectMapArrayDonorMisses.Add(entry.MapShellNorm + "|non-hex-lit"))
			{
				log?.LogWarning(
					"Homm3Import: direct map-array shell skipped because map shell '"
					+ entry.MapShellNorm
					+ "' resolved non-Hex/Lit donor shader='"
					+ (donorMaterial.shader ? donorMaterial.shader.name : "(null)")
					+ "'.");
			}
			donorMaterial = null;
			return false;
		}

		if (DirectMapArrayDonorMisses.Add(entry.MapShellNorm))
		{
			log?.LogWarning(
				"Homm3Import: direct map-array shell skipped because no loaded unit-style Hex/Lit donor material is available yet for map shell '"
				+ entry.MapShellNorm
				+ "'; using native UnitView loader.");
		}
		return false;
	}

	internal static void RefreshNativeShellMapPrefabForAdventure(GameObject shell, GameObject homm3Template, Entry entry, ManualLogSource log)
	{
		if (!shell)
			return;
		try
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.refresh.enter", shell, "entry=" + (entry?.MapNorm ?? entry?.BattlePrefabAssetPath ?? "?"), census: true);
			if (homm3Template && IsHomm3SkinnedBattleInstance(homm3Template))
			{
				var existingVisual = shell.transform.Find(MapPrefabVisualChildName);
				var createdNew = false;
				if (existingVisual && !IsHomm3SkinnedBattleInstance(existingVisual.gameObject))
				{
					existingVisual.name = MapPrefabVisualChildName + "__replace__";
					UnityEngine.Object.Destroy(existingVisual.gameObject);
					existingVisual = null;
				}
				if (!existingVisual)
					createdNew = true;
				if (TryEnsureMapPrefabVisualOnShell(shell, homm3Template, entry, log, out var skinnedVisual) && skinnedVisual)
				{
					FinishOwnedSkinnedAdventureMapPresentation(
						shell,
						skinnedVisual,
						homm3Template,
						shell,
						entry,
						log,
						fitScale: createdNew);
					Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.refresh.skinned-idle-return", shell, census: true);
				}
				TryAttachMapSquadRuntimeAttach(shell, log);
				return;
			}
			if (ShouldUseMapPrefabMapIdleAnimator(entry, log))
			{
				GameObject vanillaDonor = null;
				TryLoadMapShellVanillaDonor(entry, log, out vanillaDonor);
				if (TryEnsureMapPrefabVisualOnShell(shell, homm3Template, entry, log, out var mapVisual))
				{
					FinishHomm3MapPrefabForAdventure(vanillaDonor ? vanillaDonor : shell, mapVisual, entry, log);
					TryAttachMapArrayBillboardOnShell(shell, mapVisual, entry, log);
					TryFinalizeNativeShellMapPresentation(shell, mapVisual, vanillaDonor ? vanillaDonor : shell, entry, log);
					Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.refresh.after-finalize", shell, census: true);
				}
				TryAttachMapSquadRuntimeAttach(shell, log);
				Homm3BattleBillboardCameraFacing.TryAttach(shell, log);
				return;
			}

			// Reload/restart can return a cached HoMM3 shell prefab. Re-run the owned billboard path so
			// material frame templates and live renderer registration are restored for the new map load.
			if (homm3Template && TryApplyTownStyleUnitBillboard(shell, homm3Template, entry, log))
			{
				Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.refresh.town-style-return", shell, census: true);
				TryAttachMapSquadRuntimeAttach(shell, log);
				return;
			}

			var townRoot = shell.transform.Find(TownStyleUnitBillboardRootName);
			if (townRoot != null)
			{
				townRoot.gameObject.SetActive(true);
				var quad = townRoot.Find("quad");
				if (quad != null)
				{
					quad.gameObject.SetActive(true);
					var renderer = quad.GetComponent<Renderer>();
					if (renderer)
					{
						renderer.enabled = true;
						renderer.forceRenderingOff = false;
						TryAttachTownStyleUnitIdleAnimator(quad.gameObject, renderer.sharedMaterial, entry, log);
					}
				}
			}
			TryAttachMapSquadRuntimeAttach(shell, log);
			Homm3BattleBillboardCameraFacing.TryAttach(shell, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: native-shell map refresh failed: " + ex.Message);
		}
	}

	static void RemoveTownStyleBillboardFromShell(GameObject shell)
	{
		if (!shell)
			return;
		var townRoot = shell.transform.Find(TownStyleUnitBillboardRootName);
		if (townRoot != null)
			UnityEngine.Object.Destroy(townRoot.gameObject);
	}

	static bool TryEnsureMapPrefabVisualOnShell(
		GameObject shell,
		GameObject homm3Template,
		Entry entry,
		ManualLogSource log,
		out GameObject mapVisual)
	{
		mapVisual = null;
		if (!shell || !homm3Template || entry == null)
			return false;
		RemoveTownStyleBillboardFromShell(shell);
		var visualTr = shell.transform.Find(MapPrefabVisualChildName);
		if (visualTr != null && !visualTr.GetComponentInChildren<Animator>(true))
		{
			UnityEngine.Object.Destroy(visualTr.gameObject);
			visualTr = null;
		}
		if (visualTr == null)
		{
			var inst = UnityEngine.Object.Instantiate(homm3Template);
			if (!inst)
				return false;
			inst.name = MapPrefabVisualChildName;
			inst.transform.SetParent(shell.transform, false);
			inst.transform.SetSiblingIndex(shell.transform.childCount - 1);
			inst.transform.localPosition = Vector3.zero;
			inst.transform.localRotation = Quaternion.identity;
			inst.transform.localScale = Vector3.one;
			mapVisual = inst;
		}
		else
			mapVisual = visualTr.gameObject;
		mapVisual.SetActive(true);
		return true;
	}

	static bool TryApplyTownStyleUnitBillboard(GameObject shell, GameObject homm3Template, Entry entry, ManualLogSource log)
	{
		if (!shell || !homm3Template)
			return false;
		if (IsHomm3SkinnedBattleInstance(homm3Template) || IsOwnedSkinnedBattleEntry(entry))
			return false;

		// Adventure-map idle is authored on map.prefab (MapIdle material-swap clip over map_frame_*).
		// Town-style hex-lit quads bypass that Animator; RIFE pilots must use the prefab clip even when
		// the bundle only lists one map_frame_* asset name (hydration still leaves Count==1).
		if (ShouldUseMapPrefabMapIdleAnimator(entry, log))
			return false;

		var profileStart = Stopwatch.GetTimestamp();
		_mapLoadProfileTownBillboardAttempts++;
		var success = false;
		try
		{
			var donorRenderer = FindBestTownStyleUnitMapDonorRenderer(shell);
			var donorMaterial = donorRenderer ? donorRenderer.sharedMaterial : null;
			TownStyleUnitBillboardSource source;
			string mapTextureName;
			string battleTextureName;
			Texture mapTexture;
			if (!TryFindFirstHomm3BillboardSource(homm3Template, out source))
			{
				if (_townStyleUnitBillboardDiagRemaining > 0)
					log?.LogWarning("Homm3Import: town-style unit billboard skipped; no HoMM3 map frame texture found on '" + (homm3Template.name ?? "?") + "'.");
				return false;
			}
			mapTexture = source.Texture;
			mapTextureName = mapTexture ? mapTexture.name : null;
			battleTextureName = "disabled";
			if (TryLoadHomm3DiskFrameTexture(entry, log, out var diskTexture, out var diskTextureName) && diskTexture)
			{
				source.Texture = diskTexture;
				battleTextureName = diskTextureName;
			}

			var material = CreateTownStyleUnitBillboardMaterial(donorMaterial, source.Texture, entry, log);
			if (!material)
				return false;
			var mapLayer = donorRenderer ? donorRenderer.gameObject.layer : shell.layer;

			RemoveNativeShellVisibilityMirrors(shell, log);
			HideTownStyleUnitExistingRenderers(shell);
			shell.layer = mapLayer;

			var billboardRoot = shell.transform.Find(TownStyleUnitBillboardRootName);
			if (billboardRoot == null)
			{
				var go = new GameObject(TownStyleUnitBillboardRootName);
				billboardRoot = go.transform;
				billboardRoot.SetParent(shell.transform, false);
			}

			billboardRoot.localPosition = source.RootLocalPosition;
			billboardRoot.localRotation = source.RootLocalRotation;
			billboardRoot.localScale = source.RootLocalScale;
			billboardRoot.gameObject.layer = mapLayer;
			billboardRoot.gameObject.SetActive(true);
			billboardRoot.SetSiblingIndex(shell.transform.childCount - 1);

			var quad = billboardRoot.Find("quad");
			GameObject quadGo;
			if (quad == null)
			{
				quadGo = new GameObject("quad");
				quadGo.transform.SetParent(billboardRoot, false);
			}
			else
				quadGo = quad.gameObject;

			quadGo.layer = mapLayer;
			quadGo.SetActive(true);
			quadGo.transform.localPosition = source.QuadLocalPosition;
			quadGo.transform.localRotation = source.QuadLocalRotation;
			quadGo.transform.localScale = source.QuadLocalScale;

			var mf = quadGo.GetComponent<MeshFilter>();
			if (!mf)
				mf = quadGo.AddComponent<MeshFilter>();
			var nd = quadGo.GetComponent<MeshRenderer>();
			if (!nd)
				nd = quadGo.AddComponent<MeshRenderer>();

			mf.sharedMesh = GetOrCreateTownStyleUnitBillboardQuadMesh();
			nd.sharedMaterial = material;
			Homm3MapBillboardDeathFadeHook.AttachToQuad(quadGo, log);
			TryAttachTownStyleUnitIdleAnimator(quadGo, material, entry, log);
			if (donorRenderer)
				EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donorRenderer, billboardRoot.gameObject);
			nd.enabled = true;
			nd.forceRenderingOff = false;
			// Match custom town/dwelling billboards: these quads are camera-facing presentation,
			// not native mesh bodies, so Unity dynamic occlusion can hide the color pass while
			// the shadow caster still updates.
			nd.shadowCastingMode = ShadowCastingMode.On;
			nd.receiveShadows = false;
			nd.allowOcclusionWhenDynamic = false;
			Homm3BattleBillboardCameraFacing.TryAttach(shell, log);

			ValidateTownStyleUnitBillboardPostconditions(shell, billboardRoot, quadGo, nd, material, source.Texture, entry, log);

			if (_townStyleUnitBillboardDiagRemaining > 0)
			{
				_townStyleUnitBillboardDiagRemaining--;
				log?.LogInfo(
					"Homm3Import: town-style unit billboard applied shell='"
					+ (shell.name ?? "?")
					+ "' texture='"
					+ (source.Texture ? source.Texture.name : "?")
					+ "' textureId="
					+ (source.Texture ? source.Texture.GetInstanceID() : 0)
					+ " mapTexture='"
					+ (mapTextureName ?? "?")
					+ "' mapTextureId="
					+ (mapTexture ? mapTexture.GetInstanceID() : 0)
					+ " battleTexture='"
					+ (battleTextureName ?? "?")
					+ "'"
					+ "' sourceRenderer='"
					+ (source.RendererName ?? "?")
					+ "' size="
					+ source.Size.x.ToString("0.###")
					+ "x"
					+ source.Size.y.ToString("0.###")
					+ " rootPos="
					+ source.RootLocalPosition.ToString("0.###")
					+ " rootRot="
					+ source.RootLocalRotation.eulerAngles.ToString("0.###")
					+ " quadPos="
					+ source.QuadLocalPosition.ToString("0.###")
					+ " quadRot="
					+ source.QuadLocalRotation.eulerAngles.ToString("0.###")
					+ " quadScale="
					+ source.QuadLocalScale.ToString("0.###")
					+ " donor=["
					+ DescribeMaterial(donorMaterial)
					+ " flags="
					+ DescribeRendererFlags(donorRenderer)
					+ "] final=["
					+ DescribeMaterial(material)
					+ "] flags="
					+ DescribeRendererFlags(nd)
					+ ".");
			}

			success = true;
			return true;
		}
		finally
		{
			if (success)
				_mapLoadProfileTownBillboardSuccesses++;
			_mapLoadProfileTownBillboardTicks += Stopwatch.GetTimestamp() - profileStart;
		}
	}

	static void ValidateTownStyleUnitBillboardPostconditions(
		GameObject shell,
		Transform billboardRoot,
		GameObject quadGo,
		MeshRenderer renderer,
		Material material,
		Texture texture,
		Entry entry,
		ManualLogSource log)
	{
		var profileStart = Stopwatch.GetTimestamp();
		_mapLoadProfilePostconditionChecks++;
		try
		{
		var label = DescribeEntryUnitSidsForDiagnostics(entry);
		if (!shell)
		{
			WarnTownStyleUnitBillboardPostcondition(log, label, "shell-missing", "native shell is null after billboard application");
			return;
		}
		if (billboardRoot == null || !billboardRoot.gameObject)
			WarnTownStyleUnitBillboardPostcondition(log, label, "root-missing", "homm3_map_visual root is missing after billboard application");
		if (!quadGo)
			WarnTownStyleUnitBillboardPostcondition(log, label, "quad-missing", "homm3_map_visual/quad is missing after billboard application");
		else if (!quadGo.activeSelf)
			WarnTownStyleUnitBillboardPostcondition(log, label, "quad-inactive", "homm3_map_visual/quad is inactive after billboard application");
		if (!renderer)
			WarnTownStyleUnitBillboardPostcondition(log, label, "renderer-missing", "homm3_map_visual/quad MeshRenderer is missing after billboard application");
		else if (!renderer.enabled)
			WarnTownStyleUnitBillboardPostcondition(log, label, "renderer-disabled", "homm3_map_visual/quad MeshRenderer is disabled after billboard application");
		else if (renderer.forceRenderingOff)
			WarnTownStyleUnitBillboardPostcondition(log, label, "renderer-force-off", "homm3_map_visual/quad MeshRenderer is forceRenderingOff after billboard application");
		if (!material)
			WarnTownStyleUnitBillboardPostcondition(log, label, "material-missing", "homm3_map_visual/quad material is missing after billboard application");
		if (!texture)
			WarnTownStyleUnitBillboardPostcondition(log, label, "texture-missing", "homm3_map_visual/quad texture is missing after billboard application");

		var donorRenderersStillEnabled = 0;
		foreach (var candidate in shell.GetComponentsInChildren<Renderer>(true))
		{
			if (!candidate || !candidate.enabled)
				continue;
			if (billboardRoot != null && candidate.transform && candidate.transform.IsChildOf(billboardRoot))
				continue;
			donorRenderersStillEnabled++;
		}
		if (donorRenderersStillEnabled > 0)
			WarnTownStyleUnitBillboardPostcondition(log, label, "donor-renderers-enabled", donorRenderersStillEnabled + " donor renderer(s) remain enabled after custom billboard application");

		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid))
		{
			WarnTownStyleUnitBillboardPostcondition(log, label, "lab-sid-missing", "entry does not resolve a homm3_lab SID from battlePrefabAssetPath");
			return;
		}
		var hasBundledStaticMapFrame = TryGetBundleMapFrameTextures(entry, log, out var bundledIdleFrames, out _)
		                               && bundledIdleFrames != null
		                               && bundledIdleFrames.Length > 0;
		if (hasBundledStaticMapFrame && bundledIdleFrames.Length > 1)
			return;
		if (hasBundledStaticMapFrame)
		{
			WarnTownStyleUnitBillboardPostcondition(log, label, "idle-animation-missing", "bundled static map frame is present, but no multi-frame bundled map_frame_ animation is available; adventure map sprite will be static");
			return;
		}
		if (!LooseHomm3LabFramePngFallbackEnabled)
		{
			WarnTownStyleUnitBillboardPostcondition(log, label, "bundle-frame-source-missing", "missing bundled map_frame_ frames; loose homm3_lab PNG sidecar fallback is disabled");
			return;
		}
		var extracted = FindHomm3LabExtractedBattleRoot(labSid);
		if (string.IsNullOrEmpty(extracted))
		{
			WarnTownStyleUnitBillboardPostcondition(log, label, "frame-source-missing", "missing bundled map frames and deployed homm3_lab/" + labSid + "/extracted_battle sidecar frames");
			return;
		}
		try
		{
			var idleFrames = CandidateHomm3DiskIdleFramePaths(labSid, extracted);
			if (idleFrames == null || idleFrames.Count <= 1)
				WarnTownStyleUnitBillboardPostcondition(log, label, "idle-frames-missing", "missing deployed HoMM3 idle frames under " + extracted + " (expected numeric 02_*.png frames or manifest sequence group 2)");
		}
		catch (Exception ex)
		{
			WarnTownStyleUnitBillboardPostcondition(log, label, "idle-frame-scan-failed", "could not scan deployed HoMM3 idle frames under " + extracted + ": " + ex.Message);
		}
		}
		finally
		{
			_mapLoadProfilePostconditionTicks += Stopwatch.GetTimestamp() - profileStart;
		}
	}

	static void WarnTownStyleUnitBillboardPostcondition(ManualLogSource log, string label, string condition, string message)
	{
		var key = (label ?? "?") + "|" + condition;
		if (!TownStyleUnitBillboardPostconditionWarnings.Add(key))
			return;
		log?.LogWarning("Homm3Import: town-style unit billboard postcondition failed sid='" + (label ?? "?") + "' condition='" + condition + "': " + message + ".");
	}

	static void MaybeLogMapLoadProfile(ManualLogSource log, bool force)
	{
		if (log == null)
			return;
		if (!force
		    && (_mapLoadProfileShells - _mapLoadProfileLastReportShells) < MapLoadProfileReportEveryShells)
			return;
		_mapLoadProfileLastReportShells = _mapLoadProfileShells;
		log.LogInfo(
			"HOMM3_MAP_LOAD_PROFILE shells="
			+ _mapLoadProfileShells
			+ " shellMs="
			+ ProfileMs(_mapLoadProfileShellTicks)
			+ " townBillboard="
			+ _mapLoadProfileTownBillboardSuccesses
			+ "/"
			+ _mapLoadProfileTownBillboardAttempts
			+ " townMs="
			+ ProfileMs(_mapLoadProfileTownBillboardTicks)
			+ " diskFrameLoads="
			+ _mapLoadProfileDiskFrameLoads
			+ " diskFrameMs="
			+ ProfileMs(_mapLoadProfileDiskFrameTicks)
			+ " idleLoads="
			+ _mapLoadProfileIdleFrameLoads
			+ " idleLoadMs="
			+ ProfileMs(_mapLoadProfileIdleFrameLoadTicks)
			+ " idleScans="
			+ _mapLoadProfileIdleFrameScans
			+ " idleScanMs="
			+ ProfileMs(_mapLoadProfileIdleFrameScanTicks)
			+ " postconditions="
			+ _mapLoadProfilePostconditionChecks
			+ " postconditionMs="
			+ ProfileMs(_mapLoadProfilePostconditionTicks)
			+ ".");
	}

	static string ProfileMs(long ticks)
	{
		if (ticks <= 0)
			return "0";
		var ms = ticks * 1000.0 / Stopwatch.Frequency;
		return ms.ToString("0.###");
	}

	internal static string DescribeEntryUnitSidsForDiagnostics(Entry entry)
	{
		if (entry?.GameUnitSids != null && entry.GameUnitSids.Count > 0)
			return string.Join(",", entry.GameUnitSids);
		return LeafSid(entry?.MapNorm) ?? LeafSid(entry?.BattleNorm) ?? "?";
	}

	static void TryAttachTownStyleUnitIdleAnimator(GameObject quadGo, Material material, Entry entry, ManualLogSource log)
	{
		if (!quadGo || !material || entry == null)
			return;
		if (!TryLoadHomm3DiskIdleFrameTextures(entry, log, out var frames, out var sourceName) || frames == null || frames.Length <= 1)
			return;
		var labSidForFrames = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (!string.IsNullOrEmpty(labSidForFrames)
		    && TryGetMapRifePlaybackMeta(labSidForFrames, out _, out _, out var rifeOutputCount, out _)
		    && rifeOutputCount > 1
		    && frames.Length > rifeOutputCount + 2)
		{
			var trimmed = new Texture2D[rifeOutputCount];
			Array.Copy(frames, trimmed, rifeOutputCount);
			frames = trimmed;
			log?.LogWarning(
				"Homm3Import: town-style map idle trimmed labSid='"
				+ labSidForFrames
				+ "' to "
				+ rifeOutputCount
				+ " frames (disk had "
				+ sourceName
				+ " excess PNGs; rerun map RIFE with --reset-from-source-backup).");
		}
		EnsureHomm3MapIdleAnimatorHost(log);
		if (!Homm3MapIdleAnimatorRegistered)
			return;

		var frameMs = ResolveTownStyleMapIdleFrameMs(entry, frames.Length);
		var labSidForLog = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (!string.IsNullOrEmpty(labSidForLog) && TryGetMapRifePlaybackMeta(labSidForLog, out _, out _, out _, out _))
		{
			log?.LogInfo(
				"Homm3Import: town-style map idle timing labSid='"
				+ labSidForLog
				+ "' frames="
				+ frames.Length
				+ " frameMs="
				+ frameMs.ToString("0.##")
				+ " (~"
				+ (1000f / frameMs).ToString("0.#")
				+ " fps).");
		}
		try
		{
			Homm3MapIdleTextureAnimatorRegistry.Register(material, frames, frameMs);
			Homm3MapIdleTextureAnimatorRegistry.RegisterRenderer(quadGo.GetComponent<Renderer>());
			if (!quadGo.GetComponent<Homm3MapIdleTextureAnimator>())
				quadGo.AddComponent<Homm3MapIdleTextureAnimator>();
			if (_townStyleUnitIdleAnimDiagRemaining > 0)
			{
				_townStyleUnitIdleAnimDiagRemaining--;
				log?.LogInfo(
					"Homm3Import: town-style unit idle animator registered quad='"
					+ (quadGo.name ?? "?")
					+ "' frames="
					+ frames.Length
					+ " source='"
					+ (sourceName ?? "?")
					+ "' material='"
					+ (material.name ?? "?")
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: town-style unit idle animator attach failed: " + ex.Message);
		}
	}

	static float ResolveTownStyleMapIdleFrameMs(Entry entry, int liveFrameCount)
	{
		if (liveFrameCount <= 1)
			return TownStyleUnitIdleFrameMs;
		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (TryGetMapRifePlaybackMeta(labSid, out var cycleSec, out _, out var outputCount, out _)
		    && cycleSec > 0.001f)
		{
			// Double-RIFE or stale PNG globs can load 5× too many files; timing must follow RIFE outputCount.
			var timingFrames = liveFrameCount;
			if (outputCount > 1 && liveFrameCount > outputCount + 2)
				timingFrames = outputCount;
			return Mathf.Clamp((cycleSec * 1000f) / timingFrames, 8f, 250f);
		}
		return TownStyleUnitIdleFrameMs;
	}

	static bool ShouldUseMapPrefabMapIdleAnimator(Entry entry, ManualLogSource log)
	{
		if (entry == null)
			return false;
		if (IsOwnedSkinnedBattleEntry(entry))
			return false;
		var labSid = TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
		if (!string.IsNullOrEmpty(labSid) && Homm3BattleArrayBillboard.IsMapArrayPilotReady(labSid, entry, log))
		{
			if (_townStyleUnitBillboardDiagRemaining > 0)
			{
				_townStyleUnitBillboardDiagRemaining--;
				log?.LogInfo(
					"Homm3Import: town-style unit billboard skipped for labSid='"
					+ labSid
					+ "'; using map Texture2DArray (map_array_manifest + slice-to-Hex/Lit bridge).");
			}
			return true;
		}
		if (!string.IsNullOrEmpty(labSid) && Homm3BattleArrayBillboard.IsMapArrayPrototypeLabSid(labSid))
		{
			// A manifest-without-map_array.mat miss usually means the deployed bundle set is stale or was
			// overwritten from tools\homm3_import\build_out. Verify asset provenance before debugging renderer
			// visibility; the route below is a fallback and can produce oversized map-frame sprites.
			log?.LogInfo(
				"Homm3Import: map-array manifest present for labSid='"
				+ labSid
				+ "' but bundle lacks map_array.mat; using map RIFE / map_frame route instead.");
		}
		if (!string.IsNullOrEmpty(labSid) && TryGetMapRifeMetaFilePath(labSid, out _))
		{
			if (TryGetMapRifePlaybackMeta(labSid, out _, out _, out var outputCount, out _)
			    && outputCount > 1)
			{
				log?.LogInfo(
					"Homm3Import: map prefab route for labSid='"
					+ labSid
					+ "' (map RIFE metadata, outputCount="
					+ outputCount
					+ ").");
				return true;
			}

			log?.LogWarning(
				"Homm3Import: map prefab route for labSid='"
				+ labSid
				+ "' (.rife_map_done.json present but playback meta incomplete; avoiding town-style disk tick).");
			return true;
		}
		if (string.IsNullOrEmpty(entry.BundleName))
			return false;
		if (CountMapFrameAssetNamesInBundle(GetBundle(entry.BundleName, log)) <= 1)
			return false;
		if (_townStyleUnitBillboardDiagRemaining > 0)
		{
			_townStyleUnitBillboardDiagRemaining--;
			log?.LogInfo(
				"Homm3Import: town-style unit billboard skipped for bundle '"
				+ entry.BundleName
				+ "'; using map.prefab MapIdle animator (multi map_frame_ bundle).");
		}
		return true;
	}

	static void TryApplyMapAdventureAnimatorPlaybackTiming(GameObject mapVisual, Entry entry, ManualLogSource log)
	{
		if (!mapVisual)
			return;
		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid)
		    || !TryGetMapRifePlaybackMeta(labSid, out var cycleSec, out var targetFps, out var outputCount, out var sourceCount)
		    || cycleSec <= 0.001f)
			return;

		Animator[] animators;
		try
		{
			animators = mapVisual.GetComponentsInChildren<Animator>(true);
		}
		catch
		{
			return;
		}
		if (animators == null || animators.Length == 0)
			return;

		for (var ai = 0; ai < animators.Length; ai++)
		{
			var animator = animators[ai];
			if (!animator)
				continue;
			var clip = TryFindMapAdventureWalkClip(animator);
			if (!clip)
				continue;
			var clipLength = clip.length;
			if (clipLength <= 0.001f)
				continue;
			var speed = Mathf.Clamp(clipLength / cycleSec, MapAdventurePlaybackSpeedMin, MapAdventurePlaybackSpeedMax);
			animator.speed = speed;
			if (_mapAdventurePlaybackTimingDiagRemaining > 0)
			{
				_mapAdventurePlaybackTimingDiagRemaining--;
				log?.LogInfo(
					"Homm3Import: map adventure playback timing labSid='"
					+ labSid
					+ "' clip='"
					+ (clip.name ?? "?")
					+ "' frames="
					+ Mathf.Max(1, Mathf.RoundToInt(clip.frameRate * clipLength))
					+ " clipFps="
					+ clip.frameRate.ToString("0.###")
					+ " clipLen="
					+ clipLength.ToString("0.###")
					+ "s rifeCycle="
					+ cycleSec.ToString("0.###")
					+ "s ("
					+ outputCount
					+ "@"
					+ targetFps.ToString("0.###")
					+ "fps, src="
					+ sourceCount
					+ ") animator.speed="
					+ speed.ToString("0.###")
					+ ".");
			}
		}
	}

	static AnimationClip TryFindMapAdventureWalkClip(Animator animator)
	{
		if (!animator)
			return null;
		RuntimeAnimatorController rac;
		try
		{
			rac = animator.runtimeAnimatorController;
		}
		catch
		{
			return null;
		}
		if (!rac)
			return null;
		AnimationClip[] clips;
		try
		{
			clips = rac.animationClips;
		}
		catch
		{
			return null;
		}
		if (clips == null || clips.Length == 0)
			return null;
		for (var i = 0; i < clips.Length; i++)
		{
			var clip = clips[i];
			if (clip && string.Equals(clip.name, MapAdventureWalkClipName, StringComparison.OrdinalIgnoreCase))
				return clip;
		}
		return clips.Length == 1 ? clips[0] : null;
	}

	static bool TryGetMapRifeMetaFilePath(string labSid, out string metaPath)
	{
		metaPath = null;
		if (string.IsNullOrEmpty(labSid))
			return false;
		var mapRoot = FindHomm3LabExtractedMapRoot(labSid);
		if (string.IsNullOrEmpty(mapRoot))
			return false;
		var candidate = Path.Combine(mapRoot, ".rife_map_done.json");
		if (!File.Exists(candidate))
			return false;
		metaPath = candidate;
		return true;
	}

	static bool TryGetMapRifePlaybackMeta(
		string labSid,
		out float cycleSeconds,
		out float targetFps,
		out int outputCount,
		out int sourceCount)
	{
		cycleSeconds = 0f;
		targetFps = 0f;
		outputCount = 0;
		sourceCount = 0;
		if (!TryGetMapRifeMetaFilePath(labSid, out var metaPath))
			return false;
		try
		{
			var root = JObject.Parse(File.ReadAllText(metaPath));
			// IL2CPP Newtonsoft proxies can make `token as JObject` return null on valid objects.
			targetFps = ReadMapRifeJsonFloat(root, "cycle.targetFps")
			            ?? root.Value<float?>("targetFps")
			            ?? 50f;
			var sourceFps = root.Value<float?>("sourceFps") ?? 10f;
			if (targetFps <= 0f)
				targetFps = 50f;
			if (sourceFps <= 0f)
				sourceFps = 10f;
			outputCount = ReadMapRifeJsonInt(root, "cycle.outputCount") ?? 0;
			sourceCount = ReadMapRifeJsonInt(root, "cycle.sourceCount") ?? 0;
			if (outputCount <= 1)
				return false;
			cycleSeconds = (outputCount - 1) / targetFps;
			return cycleSeconds > 0.001f;
		}
		catch
		{
			return false;
		}
	}

	static int? ReadMapRifeJsonInt(JObject root, string dottedPath)
	{
		var token = ReadMapRifeJsonToken(root, dottedPath);
		if (token == null || token.Type == JTokenType.Null)
			return null;
		try
		{
			if (token.Type == JTokenType.Integer)
				return (int)token;
			if (token.Type == JTokenType.Float)
				return (int)(float)token;
			return int.TryParse(token.ToString(), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var v)
				? v
				: null;
		}
		catch
		{
			return null;
		}
	}

	static float? ReadMapRifeJsonFloat(JObject root, string dottedPath)
	{
		var token = ReadMapRifeJsonToken(root, dottedPath);
		if (token == null || token.Type == JTokenType.Null)
			return null;
		try
		{
			if (token.Type == JTokenType.Integer)
				return (int)token;
			if (token.Type == JTokenType.Float)
				return (float)token;
			return Homm3JsonNumber.TryParseFloat(token.ToString(), out var v)
				? v
				: null;
		}
		catch
		{
			return null;
		}
	}

	/// <summary>
	/// Walk dotted paths without SelectToken. IL2CPP Newtonsoft proxies often make SelectToken miss
	/// nested cycle.outputCount even when .rife_map_done.json on disk is complete.
	/// </summary>
	static JToken ReadMapRifeJsonToken(JObject root, string dottedPath)
	{
		if (root == null || string.IsNullOrEmpty(dottedPath))
			return null;
		try
		{
			JToken current = root;
			var parts = dottedPath.Split('.');
			for (var i = 0; i < parts.Length; i++)
			{
				if (current == null || current.Type == JTokenType.Null)
					return null;
				if (current is JObject obj)
				{
					current = obj[parts[i]];
					continue;
				}

				// IL2CPP proxies may not preserve JObject identity; fall back to indexer via ToObject path.
				try
				{
					current = current[parts[i]];
				}
				catch
				{
					return null;
				}
			}
			return current;
		}
		catch
		{
			return null;
		}
	}

	static bool TryGetMapRifeCycleGroup(string labSid, out int group)
	{
		group = 0;
		if (!TryGetMapRifeMetaFilePath(labSid, out var metaPath))
			return false;
		try
		{
			var root = JObject.Parse(File.ReadAllText(metaPath));
			group = ReadMapRifeJsonInt(root, "cycle.group") ?? 0;
			return true;
		}
		catch
		{
			return false;
		}
	}

	internal static void EnsureHomm3MapIdleAnimatorHost(ManualLogSource log)
	{
		try
		{
			EnsureHomm3MapIdleAnimatorHostCore(log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3MapIdleTextureAnimator registration failed: " + ex.Message);
		}
	}

	internal static void EnsureHomm3MapIdleAnimatorHostRequired(ManualLogSource log, string owner)
	{
		EnsureHomm3MapIdleAnimatorHostCore(log);
		if (!Homm3MapIdleAnimatorRegistered || !Homm3MapIdleAnimatorHostAttached || !Homm3MapIdleAnimatorHostObject)
			throw new InvalidOperationException((owner ?? "Homm3Import") + " requires the global Homm3MapIdleTextureAnimator host.");
	}

	static void EnsureHomm3MapIdleAnimatorHostCore(ManualLogSource log)
	{
		if (!Homm3MapIdleAnimatorRegistered)
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3MapIdleTextureAnimator>();
			Homm3MapIdleAnimatorRegistered = true;
			log?.LogInfo("Homm3Import: registered Il2Cpp type Homm3MapIdleTextureAnimator (global Hex/Lit map idle texture ticker).");
		}
		if (Homm3MapIdleAnimatorHostAttached && Homm3MapIdleAnimatorHostObject)
			return;
		Homm3MapIdleAnimatorHostAttached = false;
		var host = new GameObject("Homm3MapIdleTextureAnimator");
		host.hideFlags = HideFlags.HideAndDontSave;
		if (!host.AddComponent<Homm3MapIdleTextureAnimator>())
		{
			UnityEngine.Object.Destroy(host);
			throw new InvalidOperationException("Homm3MapIdleTextureAnimator AddComponent returned null.");
		}
		UnityEngine.Object.DontDestroyOnLoad(host);
		Homm3MapIdleAnimatorHostObject = host;
		Homm3MapIdleAnimatorHostAttached = true;
		log?.LogInfo("Homm3Import: attached global Homm3MapIdleTextureAnimator host.");
	}
	internal static void RebindTownStyleUnitBillboardTexture(Material material, Texture texture)
	{
		if (!material || !texture)
			return;
		if (IsTownStyleUnitMapBillboardMaterial(material))
		{
			SetTownStyleUnitMapMainTextureSlots(material, texture);
			ClearTownStyleUnitMapEmission(material);
			StabilizeTownStyleUnitMapMaterial(material);
			return;
		}
		try
		{
			if (material.shader)
			{
				var n = material.shader.GetPropertyCount();
				for (var i = 0; i < n; i++)
				{
					if (material.shader.GetPropertyType(i) != ShaderPropertyType.Texture)
						continue;
					var prop = material.shader.GetPropertyName(i);
					if (string.IsNullOrEmpty(prop) || !material.HasProperty(prop))
						continue;
					material.SetTexture(prop, texture);
					material.SetTextureScale(prop, Vector2.one);
					material.SetTextureOffset(prop, Vector2.zero);
				}
			}
		}
		catch
		{
			// Some IL2CPP shader proxies can fail property enumeration; the explicit slots below cover Hex/Lit.
		}

		SetTextureIfPresent(material, "_MainTex", texture);
		SetTextureIfPresent(material, "_EmissionTex", texture);
		material.mainTexture = texture;
		material.mainTextureScale = Vector2.one;
		material.mainTextureOffset = Vector2.zero;
	}

	static bool IsTownStyleUnitMapBillboardMaterial(Material material)
	{
		if (!material)
			return false;
		var name = material.name ?? string.Empty;
		const string instanceSuffix = " (Instance)";
		if (name.EndsWith(instanceSuffix, StringComparison.Ordinal))
			name = name.Substring(0, name.Length - instanceSuffix.Length);
		// Map-building animation materials (Homm3MapBuildingAnim) are Hex/Lit billboard clones too:
		// frame swaps must only touch the main texture slots.
		return name.StartsWith("HOMM3_unit_map_billboard", StringComparison.Ordinal)
		       || name.StartsWith(Homm3MapBuildingAnim.MaterialPrefix, StringComparison.Ordinal);
	}

	static readonly string[] TownStyleUnitMapMainTextureProperties =
	{
		"_MainTex",
		"_BaseMap",
		"_BaseColorMap",
		"_AlbedoMap",
		"_DiffuseMap",
		"_MainTexture"
	};

	static readonly string[] TownStyleUnitMapEmissionTextureProperties =
	{
		"_EmissionTex",
		"_EmissionMap"
	};

	static void SetTownStyleUnitMapMainTextureSlots(Material material, Texture texture)
	{
		if (!material || !texture)
			return;
		for (var i = 0; i < TownStyleUnitMapMainTextureProperties.Length; i++)
			SetTextureIfPresent(material, TownStyleUnitMapMainTextureProperties[i], texture);
		material.mainTexture = texture;
		material.mainTextureScale = Vector2.one;
		material.mainTextureOffset = Vector2.zero;
	}

	static void ClearTownStyleUnitMapEmission(Material material)
	{
		if (!material)
			return;
		for (var i = 0; i < TownStyleUnitMapEmissionTextureProperties.Length; i++)
			ClearTextureIfPresent(material, TownStyleUnitMapEmissionTextureProperties[i]);
		SetColorIfPresent(material, "_EmissionColor", Color.black);
		DisableKeywordIfPresent(material, "HEX_EMISSION_MAP_ENABLED");
		DisableKeywordIfPresent(material, "_EMISSION");
	}

	static void StabilizeTownStyleUnitMapMaterial(Material material)
	{
		if (!material)
			return;
		DisableKeywordIfPresent(material, "HEX_DITHER_FADE_ENABLED");
		EnableKeywordIfPresent(material, "HEX_ALPHA_CLIP_ENABLED");
		EnableKeywordIfPresent(material, "_ALPHATEST_ON");
		SetFloatIfPresent(material, "_AlphaClip", 1f);
		SetFloatIfPresent(material, "_AlphaCutoff", 0.05f);
		SetFloatIfPresent(material, "_Cutoff", 0.05f);
		SetFloatIfPresent(material, "_AlphaClipThreshold", 0.05f);
		SetColorIfPresent(material, "_Color", Color.white);
		SetColorIfPresent(material, "_BaseColor", Color.white);
	}

	static void SetTextureIfPresent(Material material, string propertyName, Texture texture)
	{
		if (!material || string.IsNullOrEmpty(propertyName) || !texture)
			return;
		try
		{
			if (!material.HasProperty(propertyName))
				return;
			material.SetTexture(propertyName, texture);
			material.SetTextureScale(propertyName, Vector2.one);
			material.SetTextureOffset(propertyName, Vector2.zero);
		}
		catch
		{
		}
	}

	static void ClearTextureIfPresent(Material material, string propertyName)
	{
		if (!material || string.IsNullOrEmpty(propertyName))
			return;
		try
		{
			if (!material.HasProperty(propertyName))
				return;
			material.SetTexture(propertyName, null);
			material.SetTextureScale(propertyName, Vector2.one);
			material.SetTextureOffset(propertyName, Vector2.zero);
		}
		catch
		{
		}
	}

	static void SetFloatIfPresent(Material material, string propertyName, float value)
	{
		if (!material || string.IsNullOrEmpty(propertyName))
			return;
		try
		{
			if (material.HasProperty(propertyName))
				material.SetFloat(propertyName, value);
		}
		catch
		{
		}
	}

	static void SetColorIfPresent(Material material, string propertyName, Color value)
	{
		if (!material || string.IsNullOrEmpty(propertyName))
			return;
		try
		{
			if (material.HasProperty(propertyName))
				material.SetColor(propertyName, value);
		}
		catch
		{
		}
	}

	static void EnableKeywordIfPresent(Material material, string keyword)
	{
		if (!material || string.IsNullOrEmpty(keyword))
			return;
		try
		{
			material.EnableKeyword(keyword);
		}
		catch
		{
		}
	}

	static void DisableKeywordIfPresent(Material material, string keyword)
	{
		if (!material || string.IsNullOrEmpty(keyword))
			return;
		try
		{
			material.DisableKeyword(keyword);
		}
		catch
		{
		}
	}

	static Material CreateTownStyleUnitBillboardMaterial(Material donor, Texture texture, Entry entry, ManualLogSource log)
	{
		if (!texture)
			return null;
		var materialName = "HOMM3_unit_map_billboard_hexlit";
		var sid = entry == null ? null : LeafSid(entry.MapNorm);
		if (!string.IsNullOrEmpty(sid))
			materialName += "_" + sid;

		if (donor)
		{
			var clone = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(donor, texture, materialName);
			StabilizeTownStyleUnitMapMaterial(clone);
			ClearTownStyleUnitMapEmission(clone);
			if (clone)
				return clone;
		}

		var shader = Shader.Find("Hex/Lit") ?? Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Transparent") ?? Shader.Find("Standard");
		if (!shader)
			return null;
		var fallback = new Material(shader)
		{
			name = materialName + "_fallback",
			mainTexture = texture
		};
		log?.LogWarning("Homm3Import: town-style unit billboard using fallback shader=" + shader.name + " because no Hex/Lit donor material was found.");
		return fallback;
	}

	static bool TryFindFirstHomm3BillboardSource(GameObject template, out TownStyleUnitBillboardSource source)
	{
		source = default;
		if (!template)
			return false;

		foreach (var r in template.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			var mats = r.sharedMaterials;
			if (mats == null)
				continue;
			for (var i = 0; i < mats.Length; i++)
			{
				var m = mats[i];
				if (!m)
					continue;
				var tex = m.HasProperty("_MainTex") ? m.GetTexture("_MainTex") : m.mainTexture;
				if (!tex)
					continue;
				source = BuildTownStyleUnitBillboardSource(template.transform, r, tex);
				return true;
			}
		}

		return false;
	}

	static bool TryLoadHomm3DiskFrameTexture(Entry entry, ManualLogSource log, out Texture2D texture, out string sourcePath)
	{
		var profileStart = Stopwatch.GetTimestamp();
		_mapLoadProfileDiskFrameLoads++;
		texture = null;
		sourcePath = null;
		try
		{
		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid))
			return false;
		if (DiskFrameTexturesByLabSid.TryGetValue(labSid, out var cached) && cached)
		{
			texture = cached;
			sourcePath = cached.name;
			return true;
		}

		if (TryGetBundleMapFrameTextures(entry, log, out var bundledMapFrames, out var bundledMapSource)
		    && TryFirstTexture(bundledMapFrames, out var bundledMapTexture))
		{
			DiskFrameTexturesByLabSid[labSid] = bundledMapTexture;
			texture = bundledMapTexture;
			sourcePath = bundledMapSource;
			return true;
		}

		var mapRoot = FindHomm3LabExtractedMapRoot(labSid);
		if (!string.IsNullOrEmpty(mapRoot))
		{
			var mapPaths = CandidateHomm3MapCycleFramePaths(labSid, mapRoot);
			if (mapPaths != null && mapPaths.Count > 0)
			{
				var loadedMap = LoadDiskFrameTexturesFromPaths(labSid, mapPaths.GetRange(0, 1), log, "HOMM3_map_first_");
				if (loadedMap != null && loadedMap.Length > 0 && loadedMap[0])
				{
					DiskFrameTexturesByLabSid[labSid] = loadedMap[0];
					texture = loadedMap[0];
					sourcePath = mapRoot + " extracted_map first frame";
					return true;
				}
			}
		}

		if (!LooseHomm3LabFramePngFallbackEnabled)
		{
			log?.LogInfo("Homm3Import: map frame load skipped labSid='" + labSid + "' because bundled map_frame_ textures were unavailable and loose homm3_lab PNG fallback is disabled.");
			return false;
		}

		foreach (var path in CandidateHomm3DiskFramePaths(labSid))
		{
			if (string.IsNullOrEmpty(path) || !File.Exists(path))
				continue;
			try
			{
				var bytes = File.ReadAllBytes(path);
				var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
				if (!TryLoadTextureImage(tex, bytes))
				{
					UnityEngine.Object.Destroy(tex);
					continue;
				}

				tex.name = "HOMM3_disk_" + labSid + "_" + Path.GetFileNameWithoutExtension(path);
				tex.filterMode = FilterMode.Point;
				tex.wrapMode = TextureWrapMode.Clamp;
				DiskFrameTexturesByLabSid[labSid] = tex;
				texture = tex;
				sourcePath = path;
				return true;
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: disk frame load failed for '" + path + "': " + ex.Message);
			}
		}

		return false;
		}
		finally
		{
			_mapLoadProfileDiskFrameTicks += Stopwatch.GetTimestamp() - profileStart;
		}
	}

	static bool TryLoadHomm3DiskIdleFrameTextures(Entry entry, ManualLogSource log, out Texture2D[] textures, out string sourceName)
	{
		var profileStart = Stopwatch.GetTimestamp();
		_mapLoadProfileIdleFrameLoads++;
		textures = null;
		sourceName = null;
		try
		{
		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid))
			return false;
		if (DiskIdleFrameTexturesByLabSid.TryGetValue(labSid, out var cached))
		{
			if (HasUsableCachedFrameTextures(cached, allowSparse: false, minLive: 2))
			{
				textures = cached;
				sourceName = "cache:" + labSid;
				return true;
			}
			DiskIdleFrameTexturesByLabSid.Remove(labSid);
			LogUnitMapFrameCacheInvalidated(log, "idle", labSid);
		}
		if (DiskIdleFrameTextureMissesByLabSid.Contains(labSid))
			return false;

		if (TryGetBundleMapFrameTextures(entry, log, out var bundledMapFrames, out var bundledMapSource)
		    && bundledMapFrames != null
		    && bundledMapFrames.Length > 1)
		{
			textures = bundledMapFrames;
			DiskIdleFrameTexturesByLabSid[labSid] = textures;
			sourceName = bundledMapSource;
			return true;
		}

		var mapRoot = FindHomm3LabExtractedMapRoot(labSid);
		if (!string.IsNullOrEmpty(mapRoot))
		{
			var mapPaths = CandidateHomm3MapCycleFramePaths(labSid, mapRoot);
			if (mapPaths != null && mapPaths.Count > 1)
			{
				var loadedMap = LoadDiskFrameTexturesFromPaths(labSid, mapPaths, log, "HOMM3_map_idle_");
				if (loadedMap != null && loadedMap.Length > 1)
				{
					textures = loadedMap;
					DiskIdleFrameTexturesByLabSid[labSid] = textures;
					sourceName = mapRoot + " extracted_map cycle";
					return true;
				}
			}
		}

		if (!LooseHomm3LabFramePngFallbackEnabled)
		{
			DiskIdleFrameTextureMissesByLabSid.Add(labSid);
			LogTownStyleIdleAnimMiss(log, labSid, "bundled map_frame_ idle frames unavailable and loose homm3_lab PNG fallback is disabled");
			return false;
		}

		var unitRoot = FindHomm3LabExtractedBattleRoot(labSid);
		if (string.IsNullOrEmpty(unitRoot))
		{
			DiskIdleFrameTextureMissesByLabSid.Add(labSid);
			LogTownStyleIdleAnimMiss(log, labSid, "missing extracted_battle root");
			return false;
		}

		var framePaths = CandidateHomm3DiskIdleFramePaths(labSid, unitRoot);
		if (framePaths == null || framePaths.Count <= 1)
		{
			DiskIdleFrameTextureMissesByLabSid.Add(labSid);
			LogTownStyleIdleAnimMiss(log, labSid, "found " + (framePaths == null ? 0 : framePaths.Count) + " idle frame(s) under " + unitRoot + " (numeric 02_*.png or manifest sequence group 2)");
			return false;
		}

		var loaded = LoadDiskFrameTexturesFromPaths(labSid, framePaths, log, "HOMM3_idle_");

		if (loaded == null || loaded.Length <= 1)
		{
			DiskIdleFrameTextureMissesByLabSid.Add(labSid);
			LogTownStyleIdleAnimMiss(log, labSid, "loaded " + (loaded == null ? 0 : loaded.Length) + " idle texture(s) from " + framePaths.Count + " candidate file(s)");
			return false;
		}

		textures = loaded;
		DiskIdleFrameTexturesByLabSid[labSid] = textures;
		sourceName = unitRoot + (UsesNumericIdleFrameNames(framePaths) ? " group=02" : " manifest group=2");
		return true;
		}
		finally
		{
			_mapLoadProfileIdleFrameLoadTicks += Stopwatch.GetTimestamp() - profileStart;
		}
	}

	static List<string> CandidateHomm3DiskIdleFramePaths(string labSid, string unitRoot)
	{
		if (!string.IsNullOrEmpty(labSid) && DiskIdleFramePathsByLabSid.TryGetValue(labSid, out var cached))
			return cached;

		var profileStart = Stopwatch.GetTimestamp();
		_mapLoadProfileIdleFrameScans++;
		try
		{
		if (string.IsNullOrEmpty(unitRoot) || !Directory.Exists(unitRoot))
			return null;
		string[] files;
		try
		{
			files = Directory.GetFiles(unitRoot, "02_*.png", SearchOption.AllDirectories);
		}
		catch
		{
			files = null;
		}

		if (files != null && files.Length > 0)
		{
			Array.Sort(files, StringComparer.OrdinalIgnoreCase);
			var result = new List<string>(files.Length);
			for (var i = 0; i < files.Length; i++)
			{
				var name = Path.GetFileNameWithoutExtension(files[i]);
				if (string.IsNullOrEmpty(name) || !name.StartsWith("02_", StringComparison.OrdinalIgnoreCase) || name.Length < 5)
					continue;
				var digitsOk = true;
				for (var ci = 3; ci < name.Length; ci++)
				{
					if (!char.IsDigit(name[ci]))
					{
						digitsOk = false;
						break;
					}
				}
				if (!digitsOk)
					continue;
				result.Add(files[i]);
			}
			if (result.Count > 1)
			{
				if (!string.IsNullOrEmpty(labSid))
					DiskIdleFramePathsByLabSid[labSid] = result;
				return result;
			}
		}

		var manifestResult = CandidateManifestSequenceFramePaths(unitRoot, 2);
		if (!string.IsNullOrEmpty(labSid))
			DiskIdleFramePathsByLabSid[labSid] = manifestResult;
		return manifestResult;
		}
		finally
		{
			_mapLoadProfileIdleFrameScanTicks += Stopwatch.GetTimestamp() - profileStart;
		}
	}

	static bool UsesNumericIdleFrameNames(List<string> framePaths)
	{
		if (framePaths == null || framePaths.Count == 0)
			return false;
		var name = Path.GetFileNameWithoutExtension(framePaths[0]);
		return !string.IsNullOrEmpty(name) && name.Length == 5 && name.StartsWith("02_", StringComparison.OrdinalIgnoreCase);
	}

	static List<string> CandidateHomm3MapCycleFramePaths(string labSid, string mapRoot)
	{
		if (string.IsNullOrEmpty(mapRoot) || !Directory.Exists(mapRoot))
			return null;
		var rifeOutputCount = 0;
		var hasRifeMeta = !string.IsNullOrEmpty(labSid)
		                  && TryGetMapRifePlaybackMeta(labSid, out _, out _, out rifeOutputCount, out _);
		if (!string.IsNullOrEmpty(labSid) && TryGetMapRifeCycleGroup(labSid, out var rifeGroup))
		{
			var rifeSeq = CandidateManifestSequenceFramePaths(mapRoot, rifeGroup);
			if (rifeSeq != null && rifeSeq.Count > 1)
				return TrimMapCyclePathsToRifeOutput(rifeSeq, hasRifeMeta, rifeOutputCount);
		}
		// Adventure-map DEF walk/idle cycles are usually group 0; idle-only fallbacks use group 2.
		var walk = CandidateManifestSequenceFramePaths(mapRoot, 0);
		if (walk != null && walk.Count > 1)
			return TrimMapCyclePathsToRifeOutput(walk, hasRifeMeta, rifeOutputCount);
		var idle = CandidateManifestSequenceFramePaths(mapRoot, 2);
		if (idle != null && idle.Count > 1)
			return TrimMapCyclePathsToRifeOutput(idle, hasRifeMeta, rifeOutputCount);
		if (hasRifeMeta)
			return walk != null && walk.Count > 0 ? walk : idle;
		string[] files;
		try
		{
			files = Directory.GetFiles(mapRoot, "*.png", SearchOption.AllDirectories);
		}
		catch
		{
			files = null;
		}
		if (files == null || files.Length <= 1)
			return walk != null && walk.Count > 0 ? walk : idle;
		Array.Sort(files, StringComparer.OrdinalIgnoreCase);
		return new List<string>(files);
	}

	static List<string> TrimMapCyclePathsToRifeOutput(List<string> paths, bool hasRifeMeta, int rifeOutputCount)
	{
		if (paths == null || paths.Count <= 1)
			return paths;
		if (!hasRifeMeta || rifeOutputCount <= 1 || paths.Count <= rifeOutputCount + 2)
			return paths;
		return paths.GetRange(0, rifeOutputCount);
	}

	static Texture2D[] LoadDiskFrameTexturesFromPaths(
		string labSid,
		List<string> framePaths,
		ManualLogSource log,
		string textureNamePrefix)
	{
		if (framePaths == null || framePaths.Count == 0)
			return null;
		var loaded = new List<Texture2D>(framePaths.Count);
		for (var fi = 0; fi < framePaths.Count; fi++)
		{
			var framePath = framePaths[fi];
			if (string.IsNullOrEmpty(framePath) || !File.Exists(framePath))
				continue;
			try
			{
				var bytes = File.ReadAllBytes(framePath);
				var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
				if (!TryLoadTextureImage(tex, bytes))
				{
					UnityEngine.Object.Destroy(tex);
					continue;
				}
				tex.name = textureNamePrefix + labSid + "_" + Path.GetFileNameWithoutExtension(framePath);
				tex.filterMode = FilterMode.Point;
				tex.wrapMode = TextureWrapMode.Clamp;
				loaded.Add(tex);
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: frame load failed for '" + framePath + "': " + ex.Message);
			}
		}
		return loaded.Count <= 0 ? null : loaded.ToArray();
	}

	static void LogTownStyleIdleAnimMiss(ManualLogSource log, string labSid, string reason)
	{
		if (_townStyleUnitIdleAnimMissDiagRemaining <= 0)
			return;
		_townStyleUnitIdleAnimMissDiagRemaining--;
		log?.LogInfo("Homm3Import: town-style unit idle animator skipped labSid='" + (labSid ?? "?") + "' reason='" + (reason ?? "?") + "'.");
	}

	static IEnumerable<string> CandidateHomm3DiskFramePaths(string labSid)
	{
		var unitRoot = FindHomm3LabExtractedBattleRoot(labSid);
		if (string.IsNullOrEmpty(unitRoot))
			yield break;

		foreach (var frame in new[] { "00_04.png", "00_00.png", "02_00.png", "00_0004.png", "00_0000.png", "02_0000.png" })
		{
			string[] files = null;
			try
			{
				files = Directory.GetFiles(unitRoot, frame, SearchOption.AllDirectories);
			}
			catch
			{
				files = null;
			}
			if (files == null)
				continue;
			Array.Sort(files, StringComparer.OrdinalIgnoreCase);
			for (var i = 0; i < files.Length; i++)
				yield return files[i];
		}

		foreach (var path in CandidateManifestSequenceFramePaths(unitRoot, 0, 4))
			yield return path;
		foreach (var path in CandidateManifestSequenceFramePaths(unitRoot, 0, 0))
			yield return path;
		foreach (var path in CandidateManifestSequenceFramePaths(unitRoot, 2, 0))
			yield return path;
	}

	static List<string> CandidateManifestSequenceFramePaths(string unitRoot, int group, int? preferredFrameIndex = null)
	{
		var result = new List<string>();
		if (string.IsNullOrEmpty(unitRoot) || !Directory.Exists(unitRoot))
			return result;
		string[] manifests;
		try
		{
			manifests = Directory.GetFiles(unitRoot, "*.json", SearchOption.TopDirectoryOnly);
		}
		catch
		{
			return result;
		}
		if (manifests == null || manifests.Length == 0)
			return result;
		Array.Sort(manifests, StringComparer.OrdinalIgnoreCase);
		var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		for (var mi = 0; mi < manifests.Length; mi++)
		{
			var manifestName = Path.GetFileName(manifests[mi]);
			if (!string.IsNullOrEmpty(manifestName)
			    && manifestName.StartsWith(".rife", StringComparison.OrdinalIgnoreCase))
				continue;
			string text = null;
			try
			{
				text = File.ReadAllText(manifests[mi]);
				var root = JObject.Parse(text);
				var sequences = root["sequences"] as JArray;
				if (sequences == null)
					continue;
				for (var si = 0; si < sequences.Count; si++)
				{
					var sequence = sequences[si] as JObject;
					if (sequence == null || sequence.Value<int?>("group") != group)
						continue;
					var frames = sequence["frames"] as JArray;
					if (frames == null || frames.Count == 0)
						continue;
					if (preferredFrameIndex.HasValue)
					{
						var index = preferredFrameIndex.Value;
						if (index >= 0 && index < frames.Count)
							AddManifestFramePath(unitRoot, frames[index]?.ToString(), result, seen);
						continue;
					}
					for (var fi = 0; fi < frames.Count; fi++)
						AddManifestFramePath(unitRoot, frames[fi]?.ToString(), result, seen);
				}
			}
			catch
			{
				// A malformed sidecar manifest should not block older numeric DEF frame layouts.
			}
			if (result.Count == 0 && !string.IsNullOrEmpty(text))
				AddManifestSequenceFramePathsFromText(unitRoot, text, group, preferredFrameIndex, result, seen);
		}
		return result;
	}

	static void AddManifestSequenceFramePathsFromText(
		string unitRoot,
		string text,
		int group,
		int? preferredFrameIndex,
		List<string> result,
		HashSet<string> seen)
	{
		if (string.IsNullOrEmpty(unitRoot) || string.IsNullOrEmpty(text) || result == null || seen == null)
			return;
		var search = "\"group\"";
		var pos = 0;
		while (pos >= 0 && pos < text.Length)
		{
			pos = text.IndexOf(search, pos, StringComparison.OrdinalIgnoreCase);
			if (pos < 0)
				break;
			var colon = text.IndexOf(':', pos + search.Length);
			if (colon < 0)
				break;
			var valueStart = SkipJsonWhitespace(text, colon + 1);
			if (!TryParseJsonInt(text, valueStart, out var parsedGroup, out var afterGroup))
			{
				pos = colon + 1;
				continue;
			}
			if (parsedGroup != group)
			{
				pos = afterGroup;
				continue;
			}

			var framesKey = text.IndexOf("\"frames\"", afterGroup, StringComparison.OrdinalIgnoreCase);
			if (framesKey < 0)
				break;
			var framesColon = text.IndexOf(':', framesKey + "\"frames\"".Length);
			if (framesColon < 0)
				break;
			var arrayStart = SkipJsonWhitespace(text, framesColon + 1);
			if (arrayStart >= text.Length || text[arrayStart] != '[')
			{
				pos = framesColon + 1;
				continue;
			}

			var frameIndex = 0;
			var cursor = arrayStart + 1;
			while (cursor < text.Length)
			{
				cursor = SkipJsonWhitespace(text, cursor);
				if (cursor >= text.Length || text[cursor] == ']')
					break;
				if (text[cursor] != '"')
				{
					cursor++;
					continue;
				}
				if (!TryReadJsonString(text, cursor, out var relativePath, out var afterString))
					break;
				if (!preferredFrameIndex.HasValue || preferredFrameIndex.Value == frameIndex)
					AddManifestFramePath(unitRoot, relativePath, result, seen);
				frameIndex++;
				cursor = afterString;
			}
			pos = cursor + 1;
		}
	}

	static int SkipJsonWhitespace(string text, int index)
	{
		while (index < text.Length && char.IsWhiteSpace(text[index]))
			index++;
		return index;
	}

	static bool TryParseJsonInt(string text, int index, out int value, out int next)
	{
		value = 0;
		next = index;
		if (string.IsNullOrEmpty(text) || index >= text.Length)
			return false;
		var sign = 1;
		if (text[index] == '-')
		{
			sign = -1;
			index++;
		}
		var start = index;
		while (index < text.Length && char.IsDigit(text[index]))
		{
			value = value * 10 + (text[index] - '0');
			index++;
		}
		if (index == start)
			return false;
		value *= sign;
		next = index;
		return true;
	}

	static bool TryReadJsonString(string text, int index, out string value, out int next)
	{
		value = null;
		next = index;
		if (string.IsNullOrEmpty(text) || index >= text.Length || text[index] != '"')
			return false;
		var sb = new System.Text.StringBuilder();
		for (var i = index + 1; i < text.Length; i++)
		{
			var c = text[i];
			if (c == '"')
			{
				value = sb.ToString();
				next = i + 1;
				return true;
			}
			if (c == '\\' && i + 1 < text.Length)
			{
				var escaped = text[++i];
				sb.Append(escaped == '\\' || escaped == '/' || escaped == '"' ? escaped : c);
				if (escaped != '\\' && escaped != '/' && escaped != '"')
					sb.Append(escaped);
				continue;
			}
			sb.Append(c);
		}
		return false;
	}

	static void AddManifestFramePath(string unitRoot, string relativePath, List<string> result, HashSet<string> seen)
	{
		if (string.IsNullOrWhiteSpace(unitRoot) || string.IsNullOrWhiteSpace(relativePath) || result == null || seen == null)
			return;
		try
		{
			var normalizedRelative = relativePath.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
			var fullPath = Path.GetFullPath(Path.Combine(unitRoot, normalizedRelative));
			var fullRoot = Path.GetFullPath(unitRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
			if (!fullPath.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
				return;
			if (!File.Exists(fullPath))
				return;
			if (seen.Add(fullPath))
				result.Add(fullPath);
		}
		catch
		{
			// Ignore bad manifest paths; diagnostics report missing candidate frames when none remain.
		}
	}

	internal static string FindHomm3LabExtractedBattleRoot(string labSid)
	{
		return FindHomm3LabExtractedSubfolder(labSid, "extracted_battle");
	}

	internal static string FindHomm3LabExtractedMapRoot(string labSid)
	{
		return FindHomm3LabExtractedSubfolder(labSid, "extracted_map");
	}

	static string FindHomm3LabExtractedSubfolder(string labSid, string subfolder)
	{
		if (string.IsNullOrEmpty(labSid) || string.IsNullOrEmpty(subfolder))
			return null;
		var relative = Path.Combine("homm3_lab", labSid, subfolder).Replace('\\', '/');
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(relative, out var startupPath)
		    && Directory.Exists(startupPath))
			return startupPath;
		var pluginRoot = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "homm3_lab", labSid, subfolder);
		if (Directory.Exists(pluginRoot))
			return pluginRoot;
		var directPlugin = Path.Combine(Paths.PluginPath, "homm3_lab", labSid, subfolder);
		if (Directory.Exists(directPlugin))
			return directPlugin;
#if !RELEASE_CANDIDATE_BUILD
		var repoRoot = Path.GetFullPath(Path.Combine(Paths.GameRootPath, ".."));
		var unitRoot = Path.Combine(repoRoot, "oldenera_factions", "Assets", "CustomUnits", "homm3_lab", labSid, subfolder);
		return Directory.Exists(unitRoot) ? unitRoot : null;
#else
		return null;
#endif
	}

	static int CountMapFrameAssetNamesInBundle(AssetBundle bundle)
	{
		if (!bundle)
			return 0;
		try
		{
			var names = bundle.GetAllAssetNames();
			if (names == null)
				return 0;
			var count = 0;
			for (var i = 0; i < names.Length; i++)
			{
				if (BundleAssetNameMatchesFramePrefix(names[i], "map_frame_"))
					count++;
			}
			return count;
		}
		catch
		{
			return 0;
		}
	}

	internal static bool TryLoadTextureImage(Texture2D texture, byte[] bytes)
	{
		if (!texture || bytes == null || bytes.Length == 0)
			return false;
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		return ImageConversion.LoadImage(texture, il2cppBytes);
	}

	internal static bool TryGetBundleBattleFrameTextures(Entry entry, ManualLogSource log, out Texture2D[] textures, out string sourceName)
	{
		return TryGetBundleFrameTextures(entry, log, entry?.BattlePrefabAssetPath, "homm3_frame_", true, out textures, out sourceName);
	}

	static bool TryGetBundleMapFrameTextures(Entry entry, ManualLogSource log, out Texture2D[] textures, out string sourceName)
	{
		return TryGetBundleFrameTextures(entry, log, entry?.MapPrefabAssetPath, "map_frame_", false, out textures, out sourceName);
	}

	static bool TryGetBundleFrameTextures(
		Entry entry,
		ManualLogSource log,
		string prefabAssetPath,
		string materialPrefix,
		bool preserveMaterialIndices,
		out Texture2D[] textures,
		out string sourceName)
	{
		textures = null;
		sourceName = null;
		if (entry == null
		    || string.IsNullOrEmpty(entry.BundleName)
		    || string.IsNullOrEmpty(prefabAssetPath)
		    || string.IsNullOrEmpty(materialPrefix))
			return false;

		var isMapFramePrefix = string.Equals(materialPrefix, "map_frame_", StringComparison.OrdinalIgnoreCase);
		var key = entry.BundleName + "::" + prefabAssetPath + "::" + materialPrefix + "::" + (preserveMaterialIndices ? "indexed" : "compact");
		if (BundleFrameTexturesByKey.TryGetValue(key, out var cached))
		{
			var minLive = isMapFramePrefix ? 2 : 1;
			if (HasUsableCachedFrameTextures(cached, allowSparse: preserveMaterialIndices, minLive: minLive))
			{
				textures = cached;
				sourceName = "bundle:" + key;
				return true;
			}
			BundleFrameTexturesByKey.Remove(key);
			LogUnitMapFrameCacheInvalidated(log, "bundle", key);
		}
		if (BundleFrameTextureMissesByKey.Contains(key))
			return false;

		if (string.Equals(materialPrefix, "map_frame_", StringComparison.OrdinalIgnoreCase)
		    && MapFrameTexturesByBundleName.TryGetValue(entry.BundleName, out var sharedMapFrames)
		    && HasUsableCachedFrameTextures(sharedMapFrames, allowSparse: false, minLive: 2))
		{
			textures = sharedMapFrames;
			BundleFrameTexturesByKey[key] = textures;
			sourceName = "bundle-map-shared:" + entry.BundleName;
			return true;
		}

		var bundle = GetBundle(entry.BundleName, log);
		if (bundle == null)
		{
			BundleFrameTextureMissesByKey.Add(key);
			return false;
		}

		var framesByIndex = new SortedDictionary<int, Texture2D>();
		void AddFrameTexture(int index, Texture2D texture)
		{
			if (index < 0 || !texture)
				return;
			texture.filterMode = FilterMode.Point;
			texture.wrapMode = TextureWrapMode.Clamp;
			if (!framesByIndex.ContainsKey(index))
				framesByIndex[index] = texture;
		}
		void AddMaterial(Material material)
		{
			if (!TryGetFrameTextureFromMaterial(material, materialPrefix, out var index, out var texture))
				return;
			AddFrameTexture(index, texture);
		}
		void AddTexture(Texture2D texture)
		{
			if (!TryGetFrameTextureAsset(texture, materialPrefix, out var index))
				return;
			AddFrameTexture(index, texture);
		}
		void AddAssetName(string assetName)
		{
			if (!TryParseFrameMaterialIndex(assetName, materialPrefix, out var index))
				return;
			try
			{
				var material = bundle.LoadAsset<Material>(assetName);
				if (TryGetTextureFromMaterial(material, out var materialTexture))
					AddFrameTexture(index, materialTexture);
			}
			catch
			{
			}
			try
			{
				var texture = bundle.LoadAsset<Texture2D>(assetName);
				AddFrameTexture(index, texture);
			}
			catch
			{
			}
		}

		try
		{
			var prefab = bundle.LoadAsset<GameObject>(prefabAssetPath);
			if (prefab)
			{
				foreach (var renderer in prefab.GetComponentsInChildren<Renderer>(true))
				{
					if (!renderer)
						continue;
					var mats = renderer.sharedMaterials;
					if (mats == null)
						continue;
					for (var i = 0; i < mats.Length; i++)
						AddMaterial(mats[i]);
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: bundle frame prefab scan failed for '" + key + "': " + ex.Message);
		}

		// Targeted name loads only. LoadAllAssets() hydrates entire battle bundles (Texture2DArray,
		// hundreds of homm3_frame_* clips, audio) even when map load only needs map_frame_* textures.
		try
		{
			var names = bundle.GetAllAssetNames();
			if (names != null)
			{
				for (var i = 0; i < names.Length; i++)
				{
					var assetName = names[i];
					if (!BundleAssetNameMatchesFramePrefix(assetName, materialPrefix))
						continue;
					AddAssetName(assetName);
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: bundle frame asset-name scan failed for '" + key + "': " + ex.Message);
		}

		if (isMapFramePrefix && framesByIndex.Count <= 1)
			HydrateMapFrameTexturesFromBundle(bundle, materialPrefix, framesByIndex, log, entry.BundleName);

		if (framesByIndex.Count == 0)
		{
			BundleFrameTextureMissesByKey.Add(key);
			return false;
		}

		if (preserveMaterialIndices)
		{
			var maxIndex = -1;
			foreach (var kv in framesByIndex)
				if (kv.Key > maxIndex)
					maxIndex = kv.Key;
			textures = new Texture2D[maxIndex + 1];
			foreach (var kv in framesByIndex)
				textures[kv.Key] = kv.Value;
		}
		else
		{
			textures = new Texture2D[framesByIndex.Count];
			var write = 0;
			foreach (var kv in framesByIndex)
				textures[write++] = kv.Value;
		}
		if (!isMapFramePrefix || textures.Length > 1)
			BundleFrameTexturesByKey[key] = textures;
		if (isMapFramePrefix && textures.Length > 1)
			MapFrameTexturesByBundleName[entry.BundleName] = textures;
		sourceName = "bundle:" + key;
		log?.LogInfo("Homm3Import: loaded " + framesByIndex.Count + " " + materialPrefix + " texture(s) from bundle '" + entry.BundleName + "' arrayLength=" + textures.Length + ".");
		return true;
	}

	/// <summary>
	/// Per-material <see cref="AssetBundle.LoadAsset{T}"/> often leaves <c>map_frame_*</c> materials without
	/// resident <c>_MainTex</c> until the bundle is fully hydrated. Adventure-map idle needs every frame.
	/// </summary>
	static void HydrateMapFrameTexturesFromBundle(
		AssetBundle bundle,
		string materialPrefix,
		SortedDictionary<int, Texture2D> framesByIndex,
		ManualLogSource log,
		string bundleName)
	{
		if (!bundle || framesByIndex == null || string.IsNullOrEmpty(materialPrefix))
			return;
		var bundleId = bundle.GetInstanceID();
		if (!MapFrameBundleHydratedInstanceIds.Add(bundleId))
			return;

		var before = framesByIndex.Count;
		try
		{
			var all = bundle.LoadAllAssets();
			if (all == null || all.Length == 0)
				return;
			for (var i = 0; i < all.Length; i++)
			{
				var obj = all[i];
				if (!obj)
					continue;
				var material = obj.TryCast<Material>();
				if (material && IsHomm3MapFrameMaterial(material))
				{
					if (TryGetFrameTextureFromMaterial(material, materialPrefix, out var mapIndex, out var mapTexture))
					{
						if (!framesByIndex.ContainsKey(mapIndex))
							framesByIndex[mapIndex] = mapTexture;
					}
					else if (TryGetTextureFromMaterial(material, out var anyTexture)
					         && TryParseFrameMaterialIndex(material.name, materialPrefix, out var fallbackIndex))
					{
						if (!framesByIndex.ContainsKey(fallbackIndex))
							framesByIndex[fallbackIndex] = anyTexture;
					}
					continue;
				}
				if (material
				    && TryGetFrameTextureFromMaterial(material, materialPrefix, out var matIndex, out var matTexture))
				{
					if (!framesByIndex.ContainsKey(matIndex))
						framesByIndex[matIndex] = matTexture;
					continue;
				}
				var texture = obj.TryCast<Texture2D>();
				if (texture && TryGetFrameTextureAsset(texture, materialPrefix, out var texIndex)
				    && !framesByIndex.ContainsKey(texIndex))
					framesByIndex[texIndex] = texture;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning(
				"Homm3Import: map_frame bundle hydration failed for '"
				+ (bundleName ?? "?")
				+ "': "
				+ ex.Message);
			return;
		}

		if (framesByIndex.Count > before)
		{
			log?.LogInfo(
				"Homm3Import: map_frame bundle hydration for '"
				+ (bundleName ?? "?")
				+ "' restored "
				+ framesByIndex.Count
				+ " frame texture(s) (was "
				+ before
				+ "; targeted LoadAsset left materials without textures).");
		}
	}

	static bool HasUsableCachedFrameTextures(Texture2D[] textures, bool allowSparse, int minLive)
	{
		if (textures == null || textures.Length == 0)
			return false;
		var live = 0;
		for (var i = 0; i < textures.Length; i++)
		{
			if (textures[i])
			{
				live++;
				continue;
			}
			if (!allowSparse)
				return false;
		}
		return live >= Math.Max(1, minLive);
	}

	static void LogUnitMapFrameCacheInvalidated(ManualLogSource log, string cacheKind, string key)
	{
		if (_unitMapFrameCacheRefreshDiagRemaining <= 0)
			return;
		_unitMapFrameCacheRefreshDiagRemaining--;
		log?.LogInfo("Homm3Import: invalidated " + cacheKind + " map-frame texture cache '" + (key ?? "?") + "' after reload; rebuilding from bundle assets.");
	}

	static bool TryGetFrameTextureFromMaterial(Material material, string materialPrefix, out int index, out Texture2D texture)
	{
		index = -1;
		texture = null;
		if (!material || string.IsNullOrEmpty(materialPrefix))
			return false;
		if (!TryParseFrameMaterialIndex(material.name, materialPrefix, out index))
			return false;
		return TryGetTextureFromMaterial(material, out texture);
	}

	static bool TryGetTextureFromMaterial(Material material, out Texture2D texture)
	{
		texture = null;
		if (!material)
			return false;
		var t = material.HasProperty("_MainTex") ? material.GetTexture("_MainTex") : material.mainTexture;
		texture = t ? t.TryCast<Texture2D>() : null;
		return texture;
	}

	static bool TryGetFrameTextureAsset(Texture2D texture, string materialPrefix, out int index)
	{
		index = -1;
		if (!texture || string.IsNullOrEmpty(materialPrefix))
			return false;
		if (!TryParseFrameMaterialIndex(texture.name, materialPrefix, out index))
			return false;
		return true;
	}

	static bool BundleAssetNameMatchesFramePrefix(string assetName, string materialPrefix)
	{
		return !string.IsNullOrEmpty(assetName)
		       && !string.IsNullOrEmpty(materialPrefix)
		       && assetName.IndexOf(materialPrefix, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	static bool TryParseFrameMaterialIndex(string materialName, string materialPrefix, out int index)
	{
		index = -1;
		if (string.IsNullOrWhiteSpace(materialName) || string.IsNullOrEmpty(materialPrefix))
			return false;
		var n = materialName.Trim();
		const string instanceSuffix = " (Instance)";
		if (n.EndsWith(instanceSuffix, StringComparison.Ordinal))
			n = n.Substring(0, n.Length - instanceSuffix.Length);
		var p = n.IndexOf(materialPrefix, StringComparison.OrdinalIgnoreCase);
		if (p < 0)
			return false;
		p += materialPrefix.Length;
		var start = p;
		while (p < n.Length && char.IsDigit(n[p]))
			p++;
		return p > start && int.TryParse(n.Substring(start, p - start), out index);
	}

	static bool TryFirstTexture(Texture2D[] textures, out Texture2D texture)
	{
		texture = null;
		if (textures == null)
			return false;
		for (var i = 0; i < textures.Length; i++)
		{
			var candidate = textures[i];
			if (candidate)
			{
				texture = candidate;
				return true;
			}
		}
		return false;
	}

	static TownStyleUnitBillboardSource BuildTownStyleUnitBillboardSource(Transform templateRoot, Renderer sourceRenderer, Texture texture)
	{
		var size = EstimateTownStyleUnitBillboardSize(sourceRenderer);
		var quadScale = sourceRenderer ? sourceRenderer.transform.localScale : new Vector3(size.x, size.y, 1f);
		if (!IsUsefulBillboardDimension(Mathf.Abs(quadScale.x)) || !IsUsefulBillboardDimension(Mathf.Abs(quadScale.y)))
			quadScale = new Vector3(size.x, size.y, 1f);
		quadScale = new Vector3(quadScale.x * TownStyleUnitBillboardScale, quadScale.y * TownStyleUnitBillboardScale, quadScale.z);

		// Center the replacement quad so its bottom sits on the native shell origin. Copying the
		// authored map-frame renderer center preserves small prefab lifts and makes every stack hover.
		var rootY = Mathf.Abs(quadScale.y) * 0.5f;

		return new TownStyleUnitBillboardSource
		{
			Texture = texture,
			Size = size,
			RendererName = sourceRenderer ? sourceRenderer.name : null,
			RootLocalPosition = new Vector3(0f, rootY, 0f),
			RootLocalRotation = Quaternion.identity,
			RootLocalScale = Vector3.one,
			QuadLocalPosition = Vector3.zero,
			QuadLocalRotation = Quaternion.identity,
			QuadLocalScale = quadScale
		};
	}

	static Vector2 EstimateTownStyleUnitBillboardSize(Renderer sourceRenderer)
	{
		var width = 1f;
		var height = 1f;
		if (sourceRenderer)
		{
			var boundsSize = sourceRenderer.bounds.size;
			if (IsUsefulBillboardDimension(boundsSize.x))
				width = boundsSize.x;
			if (IsUsefulBillboardDimension(boundsSize.y))
				height = boundsSize.y;

			if ((!IsUsefulBillboardDimension(width) || !IsUsefulBillboardDimension(height))
			    && sourceRenderer.TryGetComponent<MeshFilter>(out var mf)
			    && mf
			    && mf.sharedMesh)
			{
				var meshSize = mf.sharedMesh.bounds.size;
				var scale = sourceRenderer.transform.lossyScale;
				if (IsUsefulBillboardDimension(meshSize.x * Mathf.Abs(scale.x)))
					width = meshSize.x * Mathf.Abs(scale.x);
				if (IsUsefulBillboardDimension(meshSize.y * Mathf.Abs(scale.y)))
					height = meshSize.y * Mathf.Abs(scale.y);
			}
		}

		width = Mathf.Clamp(width, 0.25f, 8f);
		height = Mathf.Clamp(height, 0.25f, 8f);
		return new Vector2(width, height);
	}

	static bool IsUsefulBillboardDimension(float v) => !float.IsNaN(v) && !float.IsInfinity(v) && v > 0.01f && v < 100f;

	static void HideTownStyleUnitExistingRenderers(GameObject root)
	{
		if (!root)
			return;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTownStyleUnitBillboardMarker(r.transform))
				continue;
			r.enabled = false;
		}
	}

	static void TryAttachMapSquadRuntimeAttach(GameObject shell, ManualLogSource log)
	{
		if (!shell)
			return;
		if (!Homm3MapSquadRuntimeAttachEnabled)
			return;
		Homm3MapSquadVisualControllerHook.EnsureRuntimeAttachTypeRegistered(log);
		if (!Homm3MapSquadVisualControllerHook.IsRuntimeAttachTypeRegistered)
			return;
		try
		{
			if (!Homm3MapSquadVisualControllerHook.GetComponentSafe<Homm3MapSquadRuntimeAttach>(shell))
				Homm3MapSquadVisualControllerHook.AddComponentSafe<Homm3MapSquadRuntimeAttach>(shell);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: map squad runtime attach failed: " + ex.Message);
		}
	}

	internal static void RemoveNativeShellVisibilityMirrors(GameObject root, ManualLogSource log)
	{
		if (!root)
			return;
		var disabled = 0;
		foreach (var c in root.GetComponentsInChildren<Component>(true))
		{
			if (!c || !string.Equals(c.GetType().Name, "Homm3NativeShellVisibilitySync", StringComparison.Ordinal))
				continue;
			try
			{
				if (c is Behaviour b)
					b.enabled = false;
				UnityEngine.Object.Destroy(c);
				disabled++;
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: town-style unit billboard visibility mirror removal failed: " + ex.Message);
			}
		}
		if (disabled > 0 && _townStyleUnitBillboardDiagRemaining > 0)
			log?.LogInfo("Homm3Import: town-style unit billboard removed " + disabled + " stale native-shell visibility mirror component(s).");
	}

	static bool IsUnderTownStyleUnitBillboardMarker(Transform t)
	{
		for (var cur = t; cur != null; cur = cur.parent)
			if (cur.name == TownStyleUnitBillboardRootName)
				return true;
		return false;
	}

	static Renderer FindBestTownStyleUnitMapDonorRenderer(GameObject root)
	{
		if (!root)
			return null;
		Renderer best = null;
		var bestScore = float.NegativeInfinity;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTownStyleUnitBillboardMarker(r.transform))
				continue;
			var m = r.sharedMaterial;
			if (!m || !m.shader)
				continue;
			var shaderName = m.shader.name ?? string.Empty;
			if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			var score = 0f;
			if (r.enabled)
				score += 1000f;
			if (m.renderQueue >= 2000 && m.renderQueue <= 2500)
				score += 500f;
			if (HasMaterialKeyword(m, "HEX_DITHER_FADE_ENABLED"))
				score += 300f;
			if (HasMaterialKeyword(m, "HEX_ALPHA_CLIP_ENABLED"))
				score += 300f;
			if (r.shadowCastingMode != ShadowCastingMode.Off)
				score += 100f;
			score += Mathf.Clamp(r.bounds.size.sqrMagnitude, 0f, 100f);
			score -= TownStyleUnitAuxiliaryRendererPenalty(r);
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = r;
		}
		return best;
	}

	static int TownStyleUnitAuxiliaryRendererPenalty(Renderer r)
	{
		if (!r)
			return 0;
		var name = r.name ?? string.Empty;
		var matName = r.sharedMaterial ? r.sharedMaterial.name ?? string.Empty : string.Empty;
		var path = EsquireBattleVisualPresentation.BuildRelativePath(r.transform, null);
		if (ContainsAuxiliaryRendererToken(name)
		    || ContainsAuxiliaryRendererToken(matName)
		    || ContainsAuxiliaryRendererToken(path))
			return 1000;
		return 0;
	}

	static bool ContainsAuxiliaryRendererToken(string value)
	{
		if (string.IsNullOrEmpty(value))
			return false;
		return value.IndexOf("weapon", StringComparison.OrdinalIgnoreCase) >= 0
		       || value.IndexOf("projectile", StringComparison.OrdinalIgnoreCase) >= 0
		       || value.IndexOf("arrow", StringComparison.OrdinalIgnoreCase) >= 0
		       || value.IndexOf("bolt", StringComparison.OrdinalIgnoreCase) >= 0
		       || value.IndexOf("bow", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	static bool HasMaterialKeyword(Material m, string keyword)
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

	static string DescribeMaterial(Material m)
	{
		if (!m)
			return "(null)";
		var kws = m.shaderKeywords;
		return "name='"
		       + (m.name ?? "?")
		       + "' shader="
		       + (m.shader ? m.shader.name : "(null)")
		       + " queue="
		       + m.renderQueue
		       + " keywords=["
		       + (kws != null ? string.Join(",", kws) : string.Empty)
		       + "]";
	}

	static Mesh GetOrCreateTownStyleUnitBillboardQuadMesh()
	{
		if (_townStyleUnitBillboardQuadMesh)
			return _townStyleUnitBillboardQuadMesh;

		_townStyleUnitBillboardQuadMesh = new Mesh { name = "HOMM3_unit_map_billboard_quad" };
		_townStyleUnitBillboardQuadMesh.vertices = new[]
		{
			new Vector3(-0.5f, -0.5f, 0f),
			new Vector3(0.5f, -0.5f, 0f),
			new Vector3(-0.5f, 0.5f, 0f),
			new Vector3(0.5f, 0.5f, 0f)
		};
		_townStyleUnitBillboardQuadMesh.uv = new[]
		{
			new Vector2(0f, 0f),
			new Vector2(1f, 0f),
			new Vector2(0f, 1f),
			new Vector2(1f, 1f)
		};
		_townStyleUnitBillboardQuadMesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
		_townStyleUnitBillboardQuadMesh.RecalculateNormals();
		_townStyleUnitBillboardQuadMesh.RecalculateBounds();
		return _townStyleUnitBillboardQuadMesh;
	}

	static void PrepareNativeShellDriverRenderers(GameObject root, Transform keepSubtree)
	{
		if (!root)
			return;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTransform(r.transform, keepSubtree))
				continue;
			PrepareNativeShellDriverRenderer(r);
		}
	}

	internal static void PrepareNativeShellDriverRenderersExcept(GameObject root, Transform keepSubtree, Renderer exceptRenderer)
	{
		if (!root)
			return;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || r == exceptRenderer || IsUnderTransform(r.transform, keepSubtree))
				continue;
			PrepareNativeShellDriverRenderer(r);
		}
	}

	internal static void PrepareNativeShellDriverRenderer(Renderer r)
	{
		if (!r)
			return;
		// Hide donor mesh like town-style billboards (enabled=false). The transplant target is
		// controlled by the bridge once it has a copied Hex/Lit slice; all other native slots stay off.
		r.enabled = false;
		r.forceRenderingOff = true;
		r.shadowCastingMode = ShadowCastingMode.Off;
		r.receiveShadows = false;
	}

	internal static void PrepareNativeShellFogProbeRenderers(GameObject root, Transform keepSubtree)
	{
		if (!root)
			return;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTransform(r.transform, keepSubtree))
				continue;
			PrepareNativeShellFogProbeRenderer(r);
		}
	}

	internal static void PrepareNativeShellFogProbeRenderer(Renderer r)
	{
		if (!r)
			return;
		// Owned-skinned draw is the homm3_map_visual mesh. Native stays hidden
		// (forceRenderingOff). Owned Hex/Lit uses WorldSpace fade, not native.enabled.
		r.forceRenderingOff = true;
		r.shadowCastingMode = ShadowCastingMode.Off;
		r.receiveShadows = false;
	}

	internal static void RestoreOwnedSkinnedMapFogProbe(GameObject shell, bool undoTemplateHide = false)
	{
		if (!shell)
			return;
		var visual = shell.transform.Find(MapPrefabVisualChildName);
		if (!visual || !IsHomm3SkinnedBattleInstance(visual.gameObject))
			return;
		PrepareNativeShellFogProbeRenderers(shell, visual);
		if (undoTemplateHide)
		{
			var native = shell.GetComponentsInChildren<Renderer>(true);
			for (var i = 0; native != null && i < native.Length; i++)
			{
				var r = native[i];
				if (!r || IsUnderTransform(r.transform, visual))
					continue;
				r.enabled = true;
				r.forceRenderingOff = true;
			}
		}
		Homm3OwnedSkinnedMapFogProbe.TryAttach(shell, visual.gameObject, Plugin.LogSource);
	}

	internal static Vector3 ResolveLocalScaleForParent(Vector3 desiredWorldScale, Transform parent)
	{
		if (!parent)
			return desiredWorldScale;
		var parentScale = parent.lossyScale;
		if (Mathf.Abs(parentScale.x) <= 0.0001f
		    || Mathf.Abs(parentScale.y) <= 0.0001f
		    || Mathf.Abs(parentScale.z) <= 0.0001f)
			throw new InvalidOperationException("Cannot mirror HoMM3 map billboard scale because the target parent has a near-zero world scale.");
		return new Vector3(
			desiredWorldScale.x / parentScale.x,
			desiredWorldScale.y / parentScale.y,
			desiredWorldScale.z / parentScale.z);
	}
	internal static void AlignMapBillboardRendererBottomToShellAnchor(Renderer targetRenderer, Transform shellTransform)
	{
		if (!targetRenderer || !shellTransform)
			return;
		var bounds = targetRenderer.bounds;
		var bottomY = bounds.min.y;
		if (float.IsNaN(bottomY) || float.IsInfinity(bottomY))
			throw new InvalidOperationException("Cannot anchor HoMM3 map billboard because the target renderer bounds are invalid.");
		var deltaY = shellTransform.position.y - bottomY;
		if (Mathf.Abs(deltaY) <= 0.0001f)
			return;
		targetRenderer.transform.position += Vector3.up * deltaY;
	}

	static void PrepareReturnedNativeShellTemplate(GameObject shell, ManualLogSource log)
	{
		if (!shell)
			return;
		try
		{
			EnsureHomm3MapNativeShellTemplateGuardTypeRegistered(log);
			var guard = shell.GetComponent<Homm3MapNativeShellTemplateGuard>();
			if (!guard)
				guard = shell.AddComponent<Homm3MapNativeShellTemplateGuard>();
			if (guard)
				guard.Configure();
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.template.suppressed-return", shell, census: true);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: native-shell returned-template guard failed: " + ex.Message);
		}
	}

	static void EnsureHomm3MapNativeShellTemplateGuardTypeRegistered(ManualLogSource log)
	{
		if (Homm3MapNativeShellTemplateGuardRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3MapNativeShellTemplateGuard>();
			Homm3MapNativeShellTemplateGuardRegistered = true;
			log?.LogInfo("Homm3Import: registered Il2Cpp type Homm3MapNativeShellTemplateGuard.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3MapNativeShellTemplateGuard Il2Cpp register failed: " + ex.Message);
		}
	}

	internal static int ApplyNativeShellDrawVisibility(GameObject shell, bool visible)
	{
		if (!shell)
			return 0;

		Homm3MapArraySliceHexLitBridge.EnsureIl2CppTypeRegistered(Plugin.LogSource);
		EsquirePikemanVisuals.EnsureHomm3NativeShellRendererTransplantSyncTypeRegistered(Plugin.LogSource);

		var applied = 0;
		var bridges = CollectNativeShellComponents<Homm3MapArraySliceHexLitBridge>(shell.transform);
		for (var i = 0; i < bridges.Count; i++)
		{
			var bridge = bridges[i];
			if (!bridge)
				continue;
			bridge.ApplyControllerVisibility(visible);
			applied++;
		}

		var transplants = CollectNativeShellComponents<Homm3NativeShellRendererTransplantSync>(shell.transform);
		for (var i = 0; i < transplants.Count; i++)
		{
			var transplant = transplants[i];
			if (!transplant)
				continue;
			transplant.ApplyControllerVisibility(visible);
			applied++;
		}

		if (applied == 0)
		{
			var visual = shell.transform.Find(MapPrefabVisualChildName) ?? shell.transform.Find(TownStyleUnitBillboardRootName);
			if (visual)
			{
				var renderers = visual.GetComponentsInChildren<Renderer>(true);
				for (var i = 0; i < renderers.Length; i++)
				{
					var r = renderers[i];
					if (!r)
						continue;
					r.enabled = visible;
					r.forceRenderingOff = !visible;
					if (!visible)
					{
						r.shadowCastingMode = ShadowCastingMode.Off;
						r.receiveShadows = false;
					}
					applied++;
				}
			}
		}

		return applied;
	}

	internal static int SuppressNativeShellTemplateDrawOnly(GameObject shell)
	{
		if (!shell)
			return 0;
		var applied = 0;
		var renderers = shell.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; renderers != null && i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			r.enabled = false;
			r.forceRenderingOff = true;
			r.shadowCastingMode = ShadowCastingMode.Off;
			r.receiveShadows = false;
			applied++;
		}
		return applied;
	}

	static List<T> CollectNativeShellComponents<T>(Transform root) where T : Component
	{
		var result = new List<T>();
		CollectNativeShellComponents(root, result);
		return result;
	}

	static void CollectNativeShellComponents<T>(Transform root, List<T> result) where T : Component
	{
		if (!root)
			return;
		var component = root.GetComponent(Il2CppType.Of<T>())?.TryCast<T>();
		if (component)
			result.Add(component);
		for (var i = 0; i < root.childCount; i++)
			CollectNativeShellComponents(root.GetChild(i), result);
	}

	private static bool ShouldLogMapArrayBridgeFailure(string labSid)
	{
		if (IsMapArrayBridgeDiagnosticEnabled())
			return true;
		var key = string.IsNullOrWhiteSpace(labSid) ? "?" : labSid.Trim();
		if (!LoggedMapArrayBridgeFailures.Add(key))
			return false;
		if (_loggedMapArrayBridgeFailureCount >= MapArrayBridgeFailureLogLimit)
			return false;
		_loggedMapArrayBridgeFailureCount++;
		return true;
	}

	private static bool IsMapArrayBridgeDiagnosticEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_map_array_bridge_diag.flag");
	}

	/// <summary>
	/// Stock map units draw on the vanilla shell renderer. HoMM3 MapIdle animates a hidden child;
	/// <see cref="Homm3NativeShellRendererTransplantSync"/> copies mesh/materials onto the native slot each frame.
	/// </summary>
	static bool TryFinalizeNativeShellMapPresentation(
		GameObject shell,
		GameObject mapVisual,
		GameObject vanillaDonorPrefab,
		Entry entry,
		ManualLogSource log,
		Material mapArrayDonorOverride = null)
	{
		if (!shell || !mapVisual)
			return false;
		Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.enter", shell, "visual=" + (mapVisual.name ?? "?"), census: true);
		RemoveNativeShellVisibilityMirrors(shell, log);
		EsquirePikemanVisuals.TryRemoveHomm3MapBillboardFogSync(shell, log);
		EsquirePikemanVisuals.TryRemoveHomm3MapBillboardFogSync(mapVisual, log);

		var visualRoot = mapVisual.transform;
		var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
		var mapArrayPilot = !string.IsNullOrEmpty(labSid)
		                    && Homm3BattleArrayBillboard.IsMapArrayPilotReady(labSid, entry, log);
		Homm3MapLoadFlightRecorder.MarkGameObject(
			"native-shell.finalize.route",
			shell,
			"labSid=" + (labSid ?? "?")
			+ " mapArrayPilot=" + mapArrayPilot
			+ " disableMapArray=" + Homm3MapLoadFlightRecorder.DisableMapArrayPilots
			+ " disableTransplant=" + Homm3MapLoadFlightRecorder.DisableNativeShellTransplant);
		if (mapArrayPilot && Homm3MapLoadFlightRecorder.DisableMapArrayPilots)
		{
			log?.LogWarning(
				"Homm3Import: map-array pilot disabled by diagnostic flag for labSid='"
				+ labSid
				+ "'; restoring native donor shell.");
			HideHoMm3MapVisualRenderers(mapVisual);
			RestoreNativeShellRenderersAfterFailedTransplant(shell, visualRoot);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.map-array-disabled", shell, Homm3MapLoadFlightRecorder.DisableMapArrayPilotsFlag, census: true);
			return false;
		}
		if (mapArrayPilot && Homm3DiagnosticFlags.IsEnabled("homm3_map_array_bridge_disabled.flag"))
		{
			log?.LogWarning(
				"Homm3Import: map-array slice-to-Hex/Lit bridge disabled by diagnostic flag for labSid='"
				+ labSid
				+ "'; restoring native donor shell instead of transplanting raw map_array material.");
			HideHoMm3MapVisualRenderers(mapVisual);
			RestoreNativeShellRenderersAfterFailedTransplant(shell, visualRoot);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.bridge-disabled", shell, "homm3_map_array_bridge_disabled.flag", census: true);
			return false;
		}
		var transplantTarget = FindBestNativeMapTransplantRenderer(shell, visualRoot, mapArrayPilot);
		Homm3MapLoadFlightRecorder.MarkGameObject(
			"native-shell.finalize.transplant-target",
			transplantTarget ? transplantTarget.gameObject : null,
			"preferMapArray=" + mapArrayPilot);
		var mapArrayDonor = mapArrayDonorOverride;
		var hasMapArrayDonor = (bool)mapArrayDonor;
		if (!hasMapArrayDonor)
			hasMapArrayDonor = EsquirePikemanVisuals.TryFindHomm3MapDonorMaterialFromVanilla(vanillaDonorPrefab, log, out mapArrayDonor) && mapArrayDonor;
		if (mapArrayPilot
		    && hasMapArrayDonor
		    && mapArrayDonor
		    && Homm3MapArraySliceHexLitBridge.TryAttach(
			    shell,
			    mapVisual,
			    transplantTarget,
			    mapArrayDonor,
			    labSid,
			    log))
		{
			if (IsMapArrayBridgeDiagnosticEnabled())
			{
				log?.LogInfo(
					"Homm3Import: map-array slice-to-Hex/Lit bridge on '"
					+ (shell.name ?? "?")
					+ "' labSid='"
					+ labSid
					+ "'.");
			}
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.map-array-bridge-ok", shell, "labSid=" + labSid, census: true);
			return true;
		}

		if (mapArrayPilot)
		{
			var shouldLogFailure = ShouldLogMapArrayBridgeFailure(labSid);
			if (shouldLogFailure)
			{
				log?.LogWarning(
					"Homm3Import: map-array slice bridge failed for '"
					+ (shell.name ?? "?")
					+ "' labSid='"
					+ labSid
					+ "'; restoring native donor shell instead of transplanting raw map_array material.");
			}
			HideHoMm3MapVisualRenderers(mapVisual);
			RestoreNativeShellRenderersAfterFailedTransplant(shell, visualRoot);
			if (shouldLogFailure)
			{
				log?.LogInfo(
					"Homm3Import: map-array pilot disabled for '"
					+ (shell.name ?? "?")
					+ "' after slice bridge failure; native donor shell restored.");
			}
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.map-array-bridge-failed", shell, "labSid=" + labSid, census: true);
			return false;
		}

		if (Homm3MapLoadFlightRecorder.DisableNativeShellTransplant)
		{
			log?.LogWarning(
				"Homm3Import: native-shell renderer transplant disabled by diagnostic flag for '"
				+ (shell.name ?? "?")
				+ "'; restoring native donor shell.");
			HideHoMm3MapVisualRenderers(mapVisual);
			RestoreNativeShellRenderersAfterFailedTransplant(shell, visualRoot);
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.transplant-disabled", shell, Homm3MapLoadFlightRecorder.DisableNativeShellTransplantFlag, census: true);
			return false;
		}

		if (EsquirePikemanVisuals.TryFindHomm3MapDonorMaterialFromVanilla(vanillaDonorPrefab, log, out var donorMaterial)
		    && donorMaterial
		    && transplantTarget)
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.transplant-attach.start", shell);
			PrepareNativeShellDriverRenderersExcept(shell, visualRoot, transplantTarget);
			if (TryAttachNativeShellRendererTransplantSync(shell, donorMaterial, log))
			{
				if (mapArrayPilot)
					SuppressMapArrayVisualDraw(mapVisual);
				else
					HideHoMm3MapVisualRenderers(mapVisual);
				log?.LogInfo(
					"Homm3Import: native-shell renderer transplant on '"
					+ (shell.name ?? "?")
					+ (mapArrayPilot ? "'; homm3_map_visual draw suppressed." : "'."));
				Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.transplant-attach.ok", shell, census: true);
				return true;
			}
			Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.transplant-attach.failed", shell, census: true);
			log?.LogWarning(
				"Homm3Import: native-shell renderer transplant attach failed for '"
				+ (shell.name ?? "?")
				+ "' target='"
				+ (transplantTarget ? transplantTarget.name : "(null)")
				+ "'.");
		}
		else
		{
			if (mapArrayPilot)
				LogNativeMapTransplantTargetMiss(shell, visualRoot, log);
			log?.LogWarning(
				"Homm3Import: native-shell renderer transplant skipped for '"
				+ (shell.name ?? "?")
				+ "' donor="
				+ (donorMaterial ? "yes" : "no")
				+ " target="
				+ (transplantTarget ? transplantTarget.name : "(null)")
				+ ".");
		}

		if (mapArrayPilot)
		{
			RestoreMapArrayPilotVisualRenderers(mapVisual, log);
			log?.LogWarning(
				"Homm3Import: native-shell renderer transplant unavailable for '"
				+ (shell.name ?? "?")
				+ "'; map-array pilot drawing on its Hex/Lit homm3_map_visual fallback.");
			return true;
		}

		RestoreNativeShellRenderersAfterFailedTransplant(shell, visualRoot);
		Homm3MapLoadFlightRecorder.MarkGameObject("native-shell.finalize.transplant-unavailable-restore", shell, census: true);
		log?.LogWarning(
			"Homm3Import: native-shell renderer transplant unavailable for '"
			+ (shell.name ?? "?")
			+ "'; leaving native shell renderers enabled.");
		return false;
	}

	static void RestoreNativeShellRenderersAfterFailedTransplant(GameObject shell, Transform keepSubtree)
	{
		if (!shell)
			return;
		foreach (var r in shell.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTransform(r.transform, keepSubtree))
				continue;
			if (IsMapArraySyntheticFlatTarget(r))
			{
				r.enabled = false;
				r.forceRenderingOff = true;
				continue;
			}
			r.enabled = true;
			r.forceRenderingOff = false;
		}
	}

	static bool IsMapArraySyntheticFlatTarget(Renderer renderer)
	{
		return renderer
		       && renderer.gameObject
		       && Homm3MapArraySliceHexLitBridge.IsSyntheticFlatTargetName(renderer.gameObject.name);
	}

	internal static Renderer FindBestNativeMapTransplantRenderer(GameObject shell, Transform visualSubtree)
	{
		return FindBestNativeMapTransplantRenderer(shell, visualSubtree, preferFlatMeshSlot: false);
	}

	/// <param name="preferFlatMeshSlot">Map-array pilots should land on a <see cref="MeshRenderer"/> when possible so the HoMM3 quad mesh can replace donor skinned shells.</param>
	internal static Renderer FindBestNativeMapTransplantRenderer(
		GameObject shell,
		Transform visualSubtree,
		bool preferFlatMeshSlot)
	{
		if (!shell)
			return null;
		Renderer best = null;
		var bestScore = -1f;
		foreach (var r in shell.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTransform(r.transform, visualSubtree))
				continue;
			if (IsMapArraySyntheticFlatTarget(r))
				continue;
			if (!IsCandidateNativeMapTransplantRenderer(r))
				continue;
			// Prefer enabled stock slots, but accept disabled donors — map shells are often inactive until fog binds.
			var score = r.bounds.size.sqrMagnitude;
			if (!r.enabled)
				score *= 0.25f;
			if (preferFlatMeshSlot)
			{
				if (TryAsMeshRenderer(r) != null)
					score *= 4f;
				else if (TryAsSkinnedMeshRenderer(r) != null)
					score *= 0.05f;
			}
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = r;
		}
		return best;
	}

	/// <summary>
	/// Troglodyte (and many other) map shells only expose a <see cref="SkinnedMeshRenderer"/>.
	/// Billboard quad meshes do not draw correctly through that skinned slot, which left map-frame
	/// transplant units (Factory/Bulwark before map-array assets) invisible. Create the same shell-local
	/// flat <see cref="MeshRenderer"/> used by <see cref="Homm3MapArraySliceHexLitBridge"/>.
	/// </summary>
	internal static Renderer EnsureSyntheticFlatMapTransplantTarget(
		GameObject shell,
		Renderer requestedTarget,
		Renderer sourceRenderer,
		string labSid)
	{
		if (!shell || !sourceRenderer)
			return requestedTarget;

		var requestedIsSynthetic = requestedTarget
		                           && requestedTarget.gameObject
		                           && Homm3MapArraySliceHexLitBridge.IsSyntheticFlatTargetName(requestedTarget.gameObject.name);
		if (requestedTarget && !requestedIsSynthetic && TryAsMeshRenderer(requestedTarget) != null)
			return requestedTarget;

		Transform existing = null;
		if (requestedIsSynthetic)
			existing = requestedTarget.transform;
		else
		{
			for (var i = 0; i < shell.transform.childCount; i++)
			{
				var child = shell.transform.GetChild(i);
				if (child && Homm3MapArraySliceHexLitBridge.IsSyntheticFlatTargetName(child.name))
				{
					existing = child;
					break;
				}
			}
		}

		GameObject targetGo;
		if (existing)
			targetGo = existing.gameObject;
		else
		{
			targetGo = new GameObject(Homm3MapArraySliceHexLitBridge.SyntheticFlatTargetName);
			targetGo.transform.SetParent(shell.transform, false);
		}

		targetGo.name = string.IsNullOrEmpty(labSid)
			? Homm3MapArraySliceHexLitBridge.SyntheticFlatTargetName
			: Homm3MapArraySliceHexLitBridge.SyntheticFlatTargetName + "__sid__" + labSid;
		targetGo.layer = requestedTarget ? requestedTarget.gameObject.layer : sourceRenderer.gameObject.layer;

		var mf = targetGo.GetComponent<MeshFilter>();
		if (!mf)
			mf = targetGo.AddComponent<MeshFilter>();
		var mr = targetGo.GetComponent<MeshRenderer>();
		if (!mr)
			mr = targetGo.AddComponent<MeshRenderer>();

		var sourceMesh = TryGetMeshFilter(sourceRenderer)?.sharedMesh;
		if (!sourceMesh)
		{
			var srcSkinned = TryAsSkinnedMeshRenderer(sourceRenderer);
			if (srcSkinned)
				sourceMesh = srcSkinned.sharedMesh;
		}
		if (sourceMesh)
			mf.sharedMesh = sourceMesh;

		var flagDonor = requestedTarget ? requestedTarget : sourceRenderer;
		if (flagDonor)
		{
			mr.shadowCastingMode = flagDonor.shadowCastingMode;
			mr.receiveShadows = flagDonor.receiveShadows;
			mr.lightProbeUsage = flagDonor.lightProbeUsage;
			mr.reflectionProbeUsage = flagDonor.reflectionProbeUsage;
			mr.allowOcclusionWhenDynamic = flagDonor.allowOcclusionWhenDynamic;
			mr.sortingLayerID = flagDonor.sortingLayerID;
			mr.sortingOrder = flagDonor.sortingOrder;
		}
		mr.enabled = false;
		mr.forceRenderingOff = true;
		return mr;
	}

	internal static MeshRenderer TryAsMeshRenderer(Renderer r) => r?.TryCast<MeshRenderer>();

	internal static SkinnedMeshRenderer TryAsSkinnedMeshRenderer(Renderer r) => r?.TryCast<SkinnedMeshRenderer>();

	internal static SpriteRenderer TryAsSpriteRenderer(Renderer r) => r?.TryCast<SpriteRenderer>();

	internal static MeshFilter TryGetMeshFilter(Renderer r)
	{
		var meshRenderer = TryAsMeshRenderer(r);
		if (!meshRenderer)
			return null;
		return meshRenderer.GetComponent<MeshFilter>()
		       ?? meshRenderer.GetComponentInChildren<MeshFilter>(true);
	}

	/// <summary>IL2CPP <see cref="Renderer"/> enumerations often fail C# pattern checks; use <see cref="Il2CppObjectBase.TryCast{T}"/>.</summary>
	internal static bool IsCandidateNativeMapTransplantRenderer(Renderer r)
	{
		if (!r)
			return false;
		if (TryAsSpriteRenderer(r) || TryAsSkinnedMeshRenderer(r) || TryAsMeshRenderer(r))
			return true;
		var typeName = r.GetIl2CppType()?.Name ?? r.GetType().Name ?? string.Empty;
		return typeName.IndexOf("SpriteRenderer", StringComparison.Ordinal) >= 0
		       || typeName.IndexOf("SkinnedMeshRenderer", StringComparison.Ordinal) >= 0
		       || typeName.IndexOf("MeshRenderer", StringComparison.Ordinal) >= 0;
	}

	internal static string DescribeMapRenderer(Renderer r)
	{
		if (!r)
			return "(null)";
		if (TryAsSpriteRenderer(r) != null)
			return "SpriteRenderer";
		if (TryAsSkinnedMeshRenderer(r) != null)
			return "SkinnedMeshRenderer";
		if (TryAsMeshRenderer(r) != null)
			return "MeshRenderer";
		return r.GetIl2CppType()?.Name ?? r.GetType().Name ?? "Renderer";
	}

	static void LogNativeMapTransplantTargetMiss(GameObject shell, Transform visualSubtree, ManualLogSource log)
	{
		if (!shell || log == null || _nativeShellTransplantTargetDiagRemaining <= 0)
			return;
		_nativeShellTransplantTargetDiagRemaining--;
		var sb = new System.Text.StringBuilder();
		sb.Append("Homm3Import: native-shell transplant target miss shell='")
			.Append(shell.name ?? "?")
			.Append("' renderers=[");
		var n = 0;
		foreach (var r in shell.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			if (n++ > 0)
				sb.Append("; ");
			var underVisual = IsUnderTransform(r.transform, visualSubtree);
			sb.Append(DescribeMapRenderer(r))
				.Append(" name=")
				.Append(r.name ?? "?")
				.Append(" enabled=")
				.Append(r.enabled)
				.Append(" underVisual=")
				.Append(underVisual)
				.Append(" candidate=")
				.Append(IsCandidateNativeMapTransplantRenderer(r) && !underVisual);
		}
		sb.Append("].");
		log.LogWarning(sb.ToString());
	}

	static int _nativeShellTransplantTargetDiagRemaining = 6;

	static void HideHoMm3MapVisualRenderers(GameObject mapVisual)
	{
		if (!mapVisual)
			return;
		foreach (var r in mapVisual.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			r.enabled = false;
			r.forceRenderingOff = true;
		}
	}

	/// <summary>
	/// When native-shell transplant fails, map-array pilots must still draw on the bundle quad (hidden by default).
	/// </summary>
	static void RestoreMapArrayPilotVisualRenderers(GameObject mapVisual, ManualLogSource log)
	{
		if (!mapVisual)
			return;
		var restored = 0;
		foreach (var r in mapVisual.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			r.enabled = true;
			r.forceRenderingOff = false;
			restored++;
		}
		if (restored > 0)
			log?.LogInfo(
				"Homm3Import: map-array pilot visual restored "
				+ restored
				+ " renderer(s) on '"
				+ (mapVisual.name ?? "?")
				+ "' (transplant fallback).");
	}

	static void TryAttachNativeShellVisibilitySync(GameObject shell, ManualLogSource log)
	{
		RemoveNativeShellVisibilityMirrors(shell, log);
	}

	static void TryAttachMapArrayBillboardOnShell(GameObject shell, GameObject mapVisual, Entry entry, ManualLogSource log)
	{
		if (!mapVisual || entry == null)
			return;
		var labSid = TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid) || !Homm3BattleArrayBillboard.IsMapArrayPilotReady(labSid, entry, log))
			return;
		if (!TryEnsureMapArrayBillboardMaterial(mapVisual, entry, labSid, log))
		{
			log?.LogWarning(
				"Homm3Import: map-array material bootstrap failed for labSid='"
				+ labSid
				+ "'; skipping map-array attach.");
			return;
		}
		TryHydrateMapArrayMaterialTextures(mapVisual, entry, labSid, log);
		Homm3BattleArrayBillboard.TryAttachForMapVisual(mapVisual, labSid, log);
	}

	static bool TryEnsureMapArrayBillboardMaterial(GameObject mapVisual, Entry entry, string labSid, ManualLogSource log)
	{
		if (!mapVisual || entry == null || string.IsNullOrEmpty(entry.BundleName))
			return false;
		Renderer targetRenderer = null;
		foreach (var renderer in mapVisual.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer)
				continue;
			if (IsHomm3MapArrayBillboardMaterial(renderer.sharedMaterial))
			{
				targetRenderer = renderer;
				break;
			}
			if (targetRenderer == null && renderer.gameObject.name.IndexOf("quad", StringComparison.OrdinalIgnoreCase) >= 0)
				targetRenderer = renderer;
		}
		if (!targetRenderer)
			return false;
		if (IsHomm3MapArrayBillboardMaterial(targetRenderer.sharedMaterial))
			return true;
		var mapArrayMat = GetMapArrayMaterialForBundle(entry.BundleName, labSid, log);
		if (!mapArrayMat)
			return false;
		targetRenderer.sharedMaterial = UnityEngine.Object.Instantiate(mapArrayMat);
		log?.LogInfo(
			"Homm3Import: map-array material bootstrap labSid='"
			+ labSid
			+ "' shader="
			+ (targetRenderer.sharedMaterial ? targetRenderer.sharedMaterial.shader?.name : "?"));
		return IsHomm3MapArrayBillboardMaterial(targetRenderer.sharedMaterial);
	}

	static Material GetMapArrayMaterialForBundle(string bundleName, string labSid, ManualLogSource log)
	{
		if (string.IsNullOrEmpty(bundleName))
			return null;
		if (MapArrayMaterialsByBundle.TryGetValue(bundleName, out var cached))
			return cached;
		var bundle = GetBundle(bundleName, log);
		if (!bundle)
			return null;
		Material mapArrayMat = null;
		try
		{
			var names = bundle.GetAllAssetNames();
			if (names != null)
			{
				for (var i = 0; i < names.Length; i++)
				{
					var assetName = names[i];
					if (string.IsNullOrEmpty(assetName)
					    || assetName.IndexOf("map_array", StringComparison.OrdinalIgnoreCase) < 0
					    || !assetName.EndsWith(".mat", StringComparison.OrdinalIgnoreCase))
						continue;
					mapArrayMat = bundle.LoadAsset<Material>(assetName);
					if (mapArrayMat)
						break;
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: map-array material bootstrap failed for labSid='" + labSid + "': " + ex.Message);
			return null;
		}
		if (mapArrayMat)
			MapArrayMaterialsByBundle[bundleName] = mapArrayMat;
		return mapArrayMat;
	}

	static int _mapArrayHydrateDiagRemaining = 8;

	static void TryHydrateMapArrayMaterialTextures(GameObject mapVisual, Entry entry, string labSid, ManualLogSource log)
	{
		if (!mapVisual || entry == null || string.IsNullOrEmpty(entry.BundleName))
			return;
		var arraysByIndex = GetMapArrayTexturesForBundle(entry.BundleName, log);

		if (arraysByIndex.Count == 0)
			return;

		var arrayChunkSize = Homm3BattleArrayBillboard.ResolveMapArrayChunkSize(labSid);
		var boundRenderers = 0;
		foreach (var r in mapVisual.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			var mat = r.sharedMaterial;
			if (!IsHomm3MapArrayBillboardMaterial(mat))
				continue;
			if (mat.HasProperty("_ArraySliceSize"))
				mat.SetFloat("_ArraySliceSize", arrayChunkSize);
			foreach (var kv in arraysByIndex)
				BindMapArrayTexture(mat, kv.Key, kv.Value);
			boundRenderers++;
		}

		if (boundRenderers > 0 && _mapArrayHydrateDiagRemaining > 0)
		{
			_mapArrayHydrateDiagRemaining--;
			log?.LogInfo(
				"Homm3Import: hydrated map Texture2DArray material labSid='"
				+ (labSid ?? "?")
				+ "' arrays="
				+ arraysByIndex.Count
				+ " rendererCount="
				+ boundRenderers
				+ " bundle='"
				+ entry.BundleName
				+ "'.");
		}
	}

	internal static bool TryEnsureMapArrayMaterialTexturesForLabSid(GameObject mapVisual, string labSid, ManualLogSource log)
	{
		if (!mapVisual || string.IsNullOrEmpty(labSid))
			return false;
		if (HasMapArrayMaterialTexture(mapVisual))
			return true;
		TryLoadTable(log);
		if (!TryFindEntryByLabSid(labSid, out var entry))
			return false;
		if (!TryEnsureMapArrayBillboardMaterial(mapVisual, entry, labSid, log))
			return false;
		TryHydrateMapArrayMaterialTextures(mapVisual, entry, labSid, log);
		return HasMapArrayMaterialTexture(mapVisual);
	}

	static bool TryFindEntryByLabSid(string labSid, out Entry entry)
	{
		entry = null;
		if (string.IsNullOrEmpty(labSid))
			return false;
		for (var i = 0; i < Entries.Count; i++)
		{
			var candidate = Entries[i];
			if (candidate == null)
				continue;
			var candidateLabSid = TryHomm3LabSidFromPrefabPath(candidate.BattlePrefabAssetPath);
			if (!string.Equals(candidateLabSid, labSid, StringComparison.Ordinal))
				continue;
			entry = candidate;
			return true;
		}
		return false;
	}

	static bool HasMapArrayMaterialTexture(GameObject mapVisual)
	{
		if (!mapVisual)
			return false;
		foreach (var r in mapVisual.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || !MaterialHasMapArrayTexture(r.sharedMaterial))
				continue;
			return true;
		}
		return false;
	}

	static bool MaterialHasMapArrayTexture(Material mat)
	{
		if (!IsHomm3MapArrayBillboardMaterial(mat))
			return false;
		return HasTexture(mat, "_MainTexArray")
		       || HasTexture(mat, "_MainTexArray1")
		       || HasTexture(mat, "_MainTexArray2")
		       || HasTexture(mat, "_MainTexArray3");
	}

	static bool HasTexture(Material mat, string property)
	{
		if (!mat || string.IsNullOrEmpty(property) || !mat.HasProperty(property))
			return false;
		return (bool)mat.GetTexture(property);
	}

	static SortedDictionary<int, Texture2DArray> GetMapArrayTexturesForBundle(string bundleName, ManualLogSource log)
	{
		if (string.IsNullOrEmpty(bundleName))
			return new SortedDictionary<int, Texture2DArray>();
		if (MapArrayTexturesByBundle.TryGetValue(bundleName, out var cached))
		{
			if (HasLiveMapArrayTexture(cached))
				return cached;
			MapArrayTexturesByBundle.Remove(bundleName);
		}

		var arraysByIndex = new SortedDictionary<int, Texture2DArray>();
		var bundle = GetBundle(bundleName, log);
		if (!bundle)
		{
			MapArrayTexturesByBundle[bundleName] = arraysByIndex;
			return arraysByIndex;
		}

		try
		{
			var names = bundle.GetAllAssetNames();
			if (names != null)
			{
				for (var i = 0; i < names.Length; i++)
				{
					var assetName = names[i];
					if (string.IsNullOrEmpty(assetName)
					    || assetName.IndexOf("/generated/mapbillboard/array/", StringComparison.OrdinalIgnoreCase) < 0
					    || assetName.IndexOf("battle_frames_array_", StringComparison.OrdinalIgnoreCase) < 0)
						continue;
					var index = TryParseTrailingIndex(assetName, "battle_frames_array_");
					if (index < 0)
						continue;
					var array = bundle.LoadAsset<Texture2DArray>(assetName);
					if (array)
					{
						array.filterMode = FilterMode.Point;
						array.wrapMode = TextureWrapMode.Clamp;
						arraysByIndex[index] = array;
					}
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: map-array texture hydration failed for bundle '" + bundleName + "': " + ex.Message);
		}

		MapArrayTexturesByBundle[bundleName] = arraysByIndex;
		return arraysByIndex;
	}

	static bool HasLiveMapArrayTexture(SortedDictionary<int, Texture2DArray> arraysByIndex)
	{
		if (arraysByIndex == null || arraysByIndex.Count == 0)
			return false;
		foreach (var kv in arraysByIndex)
		{
			if (kv.Value)
				return true;
		}
		return false;
	}

	static void BindMapArrayTexture(Material mat, int index, Texture2DArray array)
	{
		if (!mat || !array)
			return;
		var property = index switch
		{
			0 => "_MainTexArray",
			1 => "_MainTexArray1",
			2 => "_MainTexArray2",
			3 => "_MainTexArray3",
			_ => null
		};
		if (string.IsNullOrEmpty(property) || !mat.HasProperty(property))
			return;
		mat.SetTexture(property, array);
	}

	static int TryParseTrailingIndex(string assetName, string prefix)
	{
		if (string.IsNullOrEmpty(assetName) || string.IsNullOrEmpty(prefix))
			return -1;
		var start = assetName.LastIndexOf(prefix, StringComparison.OrdinalIgnoreCase);
		if (start < 0)
			return -1;
		start += prefix.Length;
		var end = assetName.IndexOf('.', start);
		if (end < 0)
			end = assetName.Length;
		return int.TryParse(assetName.Substring(start, end - start), out var index) ? index : -1;
	}

	internal static bool IsHomm3MapArrayBillboardMaterial(Material m)
	{
		return Homm3ArrayUpscaleShaderSupport.IsArrayBillboardMaterial(m);
	}

	internal static void SuppressMapArrayVisualDraw(GameObject mapVisual)
	{
		if (!mapVisual)
			return;
		foreach (var r in mapVisual.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			r.enabled = false;
			r.forceRenderingOff = true;
			r.shadowCastingMode = ShadowCastingMode.Off;
			r.receiveShadows = false;
		}
	}

	static bool TryAttachNativeShellRendererTransplantSync(GameObject shell, Material donorMaterial, ManualLogSource log)
	{
		if (!shell || !donorMaterial)
			return false;
		// This attaches only the native-shell map-frame transplant fallback. Do not use it to "repair" missing
		// RIFE Hex/Lit map units without first proving the deployed custom_units_* bundles still contain map_array.mat.
		EsquirePikemanVisuals.EnsureHomm3NativeShellRendererTransplantSyncTypeRegistered(log);
		if (!EsquirePikemanVisuals.IsHomm3NativeShellRendererTransplantSyncTypeRegistered)
			return false;
		try
		{
			var sync = shell.GetComponent<Homm3NativeShellRendererTransplantSync>();
			if (!sync)
			{
				sync = shell.AddComponent<Homm3NativeShellRendererTransplantSync>();
				log?.LogInfo("Homm3Import: native-shell renderer transplant attached to '" + (shell.name ?? "?") + "'.");
			}
			sync.Configure(donorMaterial);
			return (UnityEngine.Object)sync;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: native-shell renderer transplant attach failed: " + ex);
			return false;
		}
	}


	static int CountNativeDriverRenderers(GameObject root, Transform keepSubtree)
	{
		if (!root)
			return 0;
		var n = 0;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderTransform(r.transform, keepSubtree))
				continue;
			if (r.forceRenderingOff && r.shadowCastingMode == ShadowCastingMode.Off)
				n++;
		}
		return n;
	}

	static bool IsUnderTransform(Transform t, Transform possibleParent)
	{
		if (!t || !possibleParent)
			return false;
		for (var cur = t; cur != null; cur = cur.parent)
			if (cur == possibleParent)
				return true;
		return false;
	}

	static void LogMapRendererFlagSync(Renderer donor, GameObject targetRoot, bool before, ManualLogSource log)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks || _mapRendererFlagDiagRemaining <= 0 || !donor || !targetRoot)
			return;
		if (!before)
			_mapRendererFlagDiagRemaining--;
		var target = targetRoot.GetComponentInChildren<Renderer>(true);
		log?.LogInfo(
			"Homm3Import: renderer flags "
			+ (before ? "before" : "after")
			+ " native-map sync donor=["
			+ DescribeRendererFlags(donor)
			+ "] target=["
			+ DescribeRendererFlags(target)
			+ "].");
	}

	static string DescribeRendererFlags(Renderer r)
	{
		if (!r)
			return "(null)";
		return r.GetType().Name
		       + " layer=" + r.gameObject.layer
		       + " sorting=" + r.sortingLayerID + "/" + r.sortingOrder
		       + " renderLayerMask=" + r.renderingLayerMask
		       + " shadow=" + r.shadowCastingMode
		       + " receive=" + r.receiveShadows
		       + " lightProbe=" + r.lightProbeUsage
		       + " reflectionProbe=" + r.reflectionProbeUsage
		       + " motionVec=" + r.motionVectorGenerationMode
		       + " dynamicOcclusion=" + r.allowOcclusionWhenDynamic;
	}

	static Entry TryEntryForMapTemplate(GameObject template)
	{
		if (!template)
			return null;
		return MapTemplateEntriesByInstanceId.TryGetValue(template.GetInstanceID(), out var e) ? e : null;
	}

	internal static bool TryGetBattleTemplateForUnitSid(string unitSid, ManualLogSource log, out GameObject template)
	{
		template = null;
		return TryResolveHomm3BattleEntryForUnitSid(unitSid, log, out var entry) && TryGetBattleTemplate(entry, log, out template);
	}

	/// <summary>Preview-only native donor id for an owned unit SID (the row's explicit <c>previewDonorSid</c>).</summary>
	internal static bool TryGetPreviewDonorSidForUnitSid(string unitSid, ManualLogSource log, out string donorSid)
	{
		donorSid = null;
		if (!TryResolveHomm3BattleEntryForUnitSid(unitSid, log, out var entry) || entry == null)
			return false;
		donorSid = entry.PreviewDonorSid;
		return !string.IsNullOrWhiteSpace(donorSid);
	}

	internal static bool TryResolveHomm3BattleEntryForUnitSid(string unitSid, ManualLogSource log, out Entry entry)
	{
		entry = null;
		TryLoadTable(log);
		if (string.IsNullOrWhiteSpace(unitSid))
			return false;
		var sid = unitSid.Trim();
		if (EntriesByLeafSid.TryGetValue(sid, out var leafEntries))
		{
			for (var i = 0; i < leafEntries.Count; i++)
			{
				var e = leafEntries[i];
				if (!EntryAllowsGameUnitSid(e, sid))
					continue;
				entry = e;
				return true;
			}
		}

		if (EntriesByGameUnitSid.TryGetValue(sid, out var explicitEntry))
		{
			entry = explicitEntry;
			return true;
		}

		return false;
	}

	internal static bool TryResolveHomm3UnitSidForUnitsPath(string unitsPath, out string unitSid)
	{
		unitSid = null;
		if (string.IsNullOrWhiteSpace(unitsPath))
			return false;
		if (!TryResolveHomm3BattleEntry(unitsPath, null, out var entry)
		    && !TryResolveHomm3MapEntry(unitsPath, out entry))
			return false;
		unitSid = PrimaryGameUnitSid(entry);
		return !string.IsNullOrEmpty(unitSid);
	}

	private static string PrimaryGameUnitSid(Entry entry)
	{
		if (entry == null)
			return null;
		if (entry.GameUnitSids != null)
		{
			for (var i = 0; i < entry.GameUnitSids.Count; i++)
			{
				var sid = entry.GameUnitSids[i];
				if (!string.IsNullOrWhiteSpace(sid))
					return sid.Trim();
			}
		}
		var battleLeaf = LeafSid(entry.BattleNorm);
		if (!string.IsNullOrEmpty(battleLeaf))
			return battleLeaf;
		var mapLeaf = LeafSid(entry.MapNorm);
		return string.IsNullOrEmpty(mapLeaf) ? null : mapLeaf;
	}

	/// <summary>Stem prefix for <see cref="Homm3LabBattleAudioPlayer"/> — matches <c>stage_homm3_unit_audio.py</c> (<c>HOMM3_&lt;homm3_lab folder&gt;_</c>).</summary>
	internal static string ResolveHomm3LabAudioStemPrefix(Entry e)
	{
		if (e == null)
			return null;
		var ap = e.AudioStemPrefix;
		if (!string.IsNullOrEmpty(ap))
			return ap.EndsWith("_", StringComparison.Ordinal) ? ap : ap + "_";
		var labSid = TryHomm3LabSidFromPrefabPath(e.BattlePrefabAssetPath);
		if (!string.IsNullOrEmpty(labSid))
			return "HOMM3_" + labSid + "_";
		var leaf = LeafSid(e.BattleNorm);
		return string.IsNullOrEmpty(leaf) ? null : "HOMM3_" + leaf + "_";
	}

	internal static string TryHomm3LabSidFromPrefabPath(string battlePrefabAssetPath)
	{
		if (string.IsNullOrEmpty(battlePrefabAssetPath))
			return null;
		var p = battlePrefabAssetPath.Trim().Replace('\\', '/');
		const string needle = "/homm3_lab/";
		var i = p.IndexOf(needle, StringComparison.OrdinalIgnoreCase);
		if (i < 0)
			return null;
		var rest = p.Substring(i + needle.Length);
		var slash = rest.IndexOf('/');
		if (slash <= 0)
			return null;
		return rest.Substring(0, slash);
	}

	private static string LeafSid(string unitsPath)
	{
		if (string.IsNullOrEmpty(unitsPath))
			return string.Empty;
		var p = unitsPath.Trim().Replace('\\', '/').TrimEnd('/');
		var slash = p.LastIndexOf('/');
		var leaf = slash >= 0 ? p.Substring(slash + 1) : p;
		if (leaf.EndsWith("_map", StringComparison.Ordinal))
			leaf = leaf.Substring(0, leaf.Length - "_map".Length);
		return leaf;
	}

	internal static bool TryResolveHomm3BattleEntry(string bathPath, ManualLogSource log, out Entry entry)
	{
		entry = null;
		TryLoadTable(log);
		if (string.IsNullOrEmpty(bathPath))
			return false;
		var p = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(bathPath.Trim().Replace('\\', '/'));
		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		return BattleEntriesByUnitsPath.TryGetValue(p, out entry) && entry != null;
	}

	internal static bool TryResolveHomm3MapEntry(string unitsPath, out Entry entry)
	{
		entry = null;
		TryLoadTable(null);
		if (string.IsNullOrEmpty(unitsPath))
			return false;
		var p = unitsPath.Trim().Replace('\\', '/');
		if (!p.StartsWith("units/", StringComparison.Ordinal))
			p = "units/" + p;
		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		return MapEntriesByUnitsPath.TryGetValue(p, out entry) && entry != null;
	}

	internal const string SkinnedBattleLaneMarkerName = "__homm3_skinned_battle_lane__";
	internal const string SkinWeightsUnlimitedMarkerName = "__homm3_skin_weights_unlimited__";

	/// <summary>Recognizes either the legacy billboard lane or the explicit owned-skinned battle lane.</summary>
	internal static bool LooksLikeHomm3BundleBattleInstance(GameObject b)
	{
		if (b == null || !b)
			return false;
		var n = b.name ?? string.Empty;
		var hasBattleName = string.Equals(n, "battle", StringComparison.Ordinal)
		                    || n.StartsWith("battle(", StringComparison.Ordinal)
		                    || n.StartsWith("battle (", StringComparison.Ordinal);
		if (!hasBattleName && !IsHomm3SkinnedBattleInstance(b))
			return false;
		return b.transform.Find("billboard/quad") != null || IsHomm3SkinnedBattleInstance(b);
	}

	/// <summary>
	/// Leftover HoMM3 billboard donor (not an owned skinned mesh). Preview must not copy its local pose.
	/// </summary>
	internal static bool LooksLikeHomm3BillboardPreviewDonor(GameObject go)
	{
		if (go == null || !go || !go.transform)
			return false;
		if (IsHomm3SkinnedBattleInstance(go))
			return false;
		return go.transform.Find("billboard/quad") != null;
	}

	/// <summary>Requires the explicit lab marker plus a complete skinned renderer and controller, avoiding native skinned donors.</summary>
	internal static bool IsHomm3SkinnedBattleInstance(GameObject b)
	{
		if (b == null || !b)
			return false;
		var marker = b.transform.Find(SkinnedBattleLaneMarkerName);
		if (marker == null || !marker)
			return false;
		var skin = b.GetComponentInChildren<SkinnedMeshRenderer>(true);
		if (skin == null || !skin || skin.sharedMesh == null || !skin.sharedMesh)
			return false;
		var bones = skin.bones;
		if (bones == null || bones.Length == 0)
			return false;
		for (var i = 0; i < bones.Length; i++)
			if (bones[i] == null || !bones[i])
				return false;
		var animator = b.GetComponentInChildren<Animator>(true);
		return animator != null
		       && animator
		       && animator.runtimeAnimatorController != null;
	}

	internal static bool IsOwnedSkinnedPrefabPath(string prefabPath)
	{
		if (string.IsNullOrEmpty(prefabPath))
			return false;
		return prefabPath.Replace('\\', '/').IndexOf("/OwnedSkinned/", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	internal static bool IsOwnedSkinnedBattleEntry(Entry e)
	{
		return e != null
		       && (IsOwnedSkinnedPrefabPath(e.BattlePrefabAssetPath)
		           || IsOwnedSkinnedPrefabPath(e.MapPrefabAssetPath));
	}

	internal static bool IsOwnedSkinnedUnitSid(string unitSid)
	{
		return TryResolveHomm3BattleEntryForUnitSid(unitSid, null, out var bySid)
		       && IsOwnedSkinnedBattleEntry(bySid);
	}

	private static int _skinnedMapPresentationLogs;

	/// <summary>
	/// Adventure-map owned-skinned presentation. Skipping billboard finish is not enough: the native
	/// shell is a clone of the donor map prefab (live log: <c>troglodyte_upg_alt_map</c>), and the
	/// owned mesh keeps battle-prefab layers. Copy donor map renderer flags onto the owned visual,
	/// then hide donor drivers so the player sees the owned mesh, not the dungeon stand-in.
	/// </summary>
	static void FinishOwnedSkinnedAdventureMapPresentation(
		GameObject shell,
		GameObject visual,
		GameObject template,
		GameObject scaleDonor,
		Entry entry,
		ManualLogSource log,
		bool fitScale)
	{
		if (!shell || !visual)
			return;

		var visualRoot = visual.transform;
		var donorRenderer = FindBestNativeMapTransplantRenderer(shell, visualRoot);
		if (!donorRenderer && scaleDonor && scaleDonor != shell)
			donorRenderer = FindBestNativeMapTransplantRenderer(scaleDonor, null);
		var hexLitDonor = donorRenderer ? donorRenderer.gameObject : (scaleDonor ? scaleDonor : shell);

		OwnedSkinnedMapFitCacheKey cacheKey = default;
		var cacheable = fitScale && TryCreateOwnedSkinnedMapFitCacheKey(
			template, shell, visual, entry, out cacheKey);
		var cacheHit = false;
		OwnedSkinnedMapFit cachedFit = default;
		if (cacheable && OwnedSkinnedMapFitCache.TryGetValue(cacheKey, out cachedFit))
		{
			if (cachedFit.Template && cachedFit.Template == template
			    && IsFinitePositive(cachedFit.LocalScale.x) && IsFinitePositive(cachedFit.LocalScale.y)
			    && IsFinitePositive(cachedFit.LocalScale.z)
			    && !float.IsNaN(cachedFit.FeetOffsetFromFloor) && !float.IsInfinity(cachedFit.FeetOffsetFromFloor))
				cacheHit = true;
			else
				OwnedSkinnedMapFitCache.Remove(cacheKey);
		}

		var fitApplied = false;
		if (fitScale)
		{
			if (cacheHit)
			{
				visual.transform.localScale = Vector3.one;
				EnsureOwnedSkinnedDeliveryOrientation(visual, log);
				SampleOwnedSkinnedIdlePose(visual);
				visual.transform.localScale = cachedFit.LocalScale;
				fitApplied = true;
			}
			else
				fitApplied = ApplySkinnedAdventureMapVisualScale(scaleDonor ? scaleDonor : shell, visual, entry, log);
		}
		EnsureSkinnedAdventureMapIdle(visual, entry, log, hexLitDonor, preserveAdventureHexFog: true);
		var nativeFogShader = VerifyOwnedSkinnedMapUsesNativeHexLit(visual, log);
		var feetAligned = cacheHit
			? ApplyOwnedSkinnedFeetFloorOffset(visual, cachedFit.FeetOffsetFromFloor)
			: AlignOwnedSkinnedFeetToDonor(null, visual);
		if (cacheable && !cacheHit && fitApplied && feetAligned
		    && TryGetOwnedSkinnedHexFloorY(visual, out var floorY))
		{
			var feetOffset = visual.transform.position.y - floorY;
			if (!float.IsNaN(feetOffset) && !float.IsInfinity(feetOffset))
				OwnedSkinnedMapFitCache[cacheKey] = new OwnedSkinnedMapFit(template, visual.transform.localScale, feetOffset);
		}
		// The shell is a clone of the donor <unit>_map prefab; its scale_roll child carries the unit's authored
		// map yaw (toward the camera). Our visual is that child's sibling, so it takes the same yaw.
		TryApplyOwnedSkinnedNativeModelFacing(shell, visual, "map", log);

		if (donorRenderer)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donorRenderer, visual);
		else
		{
			visual.layer = shell.layer;
			var renderers = visual.GetComponentsInChildren<Renderer>(true);
			for (var i = 0; i < renderers.Length; i++)
			{
				if (!renderers[i])
					continue;
				renderers[i].gameObject.layer = shell.layer;
			}
			log?.LogError(
				"Homm3Import: owned skinned map visual '"
				+ (visual.name ?? "?")
				+ "' has no donor renderer for map flags; copied shell layer "
				+ shell.layer
				+ " only.");
		}

		PrepareNativeShellFogProbeRenderers(shell, visualRoot);
		Homm3OwnedSkinnedMapFogProbe.TryAttach(shell, visual, log);
		BindOwnedSkinnedMapDeathAnimator(shell, visual, log);

		if (_skinnedMapPresentationLogs >= 24)
			return;
		_skinnedMapPresentationLogs++;
		log?.LogInfo(
			"Homm3Import: owned skinned map presentation shell='"
			+ (shell.name ?? "?")
			+ "' visual='"
			+ (visual.name ?? "?")
			+ "' donor="
			+ (donorRenderer ? DescribeMapRenderer(donorRenderer) + ":" + (donorRenderer.name ?? "?") : "(none)")
			+ " visualLayer="
			+ visual.layer
			+ " visualRenderers="
			+ visual.GetComponentsInChildren<Renderer>(true).Length
			+ " nativeHexLitFog="
			+ nativeFogShader
			+ ".");
	}

	static int _ownedSkinnedMapStubShaderLogs;
	static int _ownedSkinnedMapDeathBindLogs;
	static int _ownedSkinnedMapDeathBindErrors;

	/// <summary>Source marker pinned by tools/validate_homm3_map_squad_death_contract.py.</summary>
	internal const string OwnedSkinnedMapDeathAnimatorBindMarker = "homm3.mapSquadDeath.ownedAnimatorBind.v1";

	/// <summary>
	/// Vanilla adventure-map death contract (docs/homm3_map_squad_death_contract.md): the native squad
	/// drawer (live <c>ezp</c>, mono <c>SquadDrawer</c>) caches <c>GetComponentInChildren&lt;Animator&gt;()</c>
	/// of the instantiated map prefab once in <c>Init</c>; on a Killed release (<c>fdh.bjiv</c> -> <c>ezp.bigh</c>)
	/// it sets trigger <c>die</c> + bool <c>isDead</c> on that Animator and destroys the squad after
	/// <c>UnitViewConfig.deathTimeOffset + 2</c> s. Our map prefab is a donor-map clone whose hidden donor
	/// Animator comes before the owned visual in depth-first order, so the game would kill the invisible donor
	/// while the owned mesh kept idling. The donor renderers stay as fog probes; only their Animators go, so
	/// the one Animator the drawer can bind is the owned visual's (its stock-controller override already
	/// carries die/isDead -> DYING.die 0 -> Unit_Death). DestroyImmediate: the game instantiates this template
	/// in the same frame it is returned. A shell whose first Animator is still not owned logs an error; there
	/// is no second death path.
	/// </summary>
	static bool BindOwnedSkinnedMapDeathAnimator(GameObject shell, GameObject visual, ManualLogSource log)
	{
		if (!shell || !visual)
			return false;
		var visualRoot = visual.transform;
		var removed = 0;
		var animators = shell.GetComponentsInChildren<Animator>(true);
		for (var i = 0; animators != null && i < animators.Length; i++)
		{
			var animator = animators[i];
			if (!animator || IsUnderTransform(animator.transform, visualRoot))
				continue;
			UnityEngine.Object.DestroyImmediate(animator);
			removed++;
		}

		var bound = shell.GetComponentInChildren<Animator>(true);
		if (!bound || !IsUnderTransform(bound.transform, visualRoot) || !bound.runtimeAnimatorController)
		{
			if (_ownedSkinnedMapDeathBindErrors < 24)
			{
				_ownedSkinnedMapDeathBindErrors++;
				log?.LogError(
					"Homm3Import: owned skinned map death bind failed on shell='"
					+ (shell.name ?? "?")
					+ "': first Animator is "
					+ (bound ? "'" + (bound.name ?? "?") + "' controller=" + (bound.runtimeAnimatorController ? bound.runtimeAnimatorController.name : "(none)") : "(none)")
					+ ", not the owned visual '"
					+ (visual.name ?? "?")
					+ "'; the native squad drawer will not play the owned death clip ("
					+ OwnedSkinnedMapDeathAnimatorBindMarker
					+ ").");
			}
			return false;
		}

		if (_ownedSkinnedMapDeathBindLogs < 8)
		{
			_ownedSkinnedMapDeathBindLogs++;
			log?.LogInfo(
				"Homm3Import: owned skinned map death bind shell='"
				+ (shell.name ?? "?")
				+ "' removedDonorAnimators="
				+ removed
				+ " bound='"
				+ (bound.name ?? "?")
				+ "' controller='"
				+ bound.runtimeAnimatorController.name
				+ "' ("
				+ OwnedSkinnedMapDeathAnimatorBindMarker
				+ ").");
		}
		return true;
	}

	/// <summary>
	/// Adventure-map fog of war is shader-global: <c>FogOfWarRenderer</c> enables the global
	/// <c>HEX_FOG_OF_WAR_ENABLED</c> keyword and the <c>FogOfWar_Map</c> textures, so any renderer
	/// drawn with the native Hex/Lit (5 passes: Lit, ShadowCaster, Prepass, DepthOnly, Silhouette)
	/// is fogged, and the squad controller only toggles the root GameObject. Owned bundles embed a
	/// same-named single-pass "Hex/Lit" stub with no fog variants, which drew squads through the
	/// fog while the Hex/Lit rebind was refused. The rebind (<see cref="EnsureSkinnedBattleRuntimeCompatibility"/>)
	/// is the one mechanism that joins native fog; this only proves the result and fails loud.
	/// </summary>
	static bool VerifyOwnedSkinnedMapUsesNativeHexLit(GameObject visual, ManualLogSource log)
	{
		if (!visual)
			return false;
		var ok = true;
		var skins = visual.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		for (var i = 0; skins != null && i < skins.Length; i++)
		{
			var skin = skins[i];
			if (!skin)
				continue;
			var materials = skin.sharedMaterials;
			for (var j = 0; materials != null && j < materials.Length; j++)
			{
				var material = materials[j];
				var shader = material ? material.shader : null;
				var passes = shader ? shader.passCount : 0;
				if (shader && string.Equals(shader.name, "Hex/Lit", StringComparison.Ordinal) && passes > 1)
					continue;
				ok = false;
				if (_ownedSkinnedMapStubShaderLogs >= 24)
					continue;
				_ownedSkinnedMapStubShaderLogs++;
				log?.LogError(
					"Homm3Import: owned skinned map visual '"
					+ (visual.name ?? "?")
					+ "' material '"
					+ (material ? material.name ?? "?" : "(null)")
					+ "' draws with shader '"
					+ (shader ? shader.name ?? "?" : "(null)")
					+ "' passes="
					+ passes
					+ "; not the native Hex/Lit, so adventure-map fog of war does not apply to it "
					+ "(see the Hex/Lit rebind line above).");
			}
		}
		return ok;
	}

	private static bool ApplySkinnedAdventureMapVisualScale(GameObject vanilla, GameObject visual, Entry entry, ManualLogSource log)
	{
		if (!visual)
			return false;
		// Map squads are the battle model at the native map fraction: stock <unit>_map prefabs reuse the
		// battle mesh under a smaller scale node (median adventureMapToBattleHeightRatio over all stock
		// pairs). Fitting the map to the full battle target made every owned squad ~1.4x its stock size.
		if (entry != null && entry.BattleHeightHexes.HasValue && _battleWorldHeightPerHex.HasValue
		    && _adventureMapToBattleHeightRatio.HasValue)
		{
			visual.transform.localScale = Vector3.one;
			EnsureOwnedSkinnedDeliveryOrientation(visual, log);
			SampleOwnedSkinnedIdlePose(visual);
			var target = entry.BattleHeightHexes.Value * _battleWorldHeightPerHex.Value * _adventureMapToBattleHeightRatio.Value;
			if (!TryGetRenderableWorldBounds(visual, out var skinnedBounds) || skinnedBounds.size.y < 1e-4f)
			{
				log?.LogError("Homm3Import skinned map fit: owned mesh has no measurable height.");
				return false;
			}
			var fit = target / skinnedBounds.size.y;
			if (!IsFinitePositive(fit))
			{
				log?.LogError("Homm3Import skinned map fit: invalid hex factor " + fit + ".");
				return false;
			}

			ApplyUniformWorldHeightFit(visual, skinnedBounds.size.y, target, log,
				"hex-map mapRatio=" + _adventureMapToBattleHeightRatio.Value.ToString("F3"));
			return AlignOwnedSkinnedFeetToDonor(vanilla, visual);
		}
		FitSkinnedMeshToDonorWorldHeight(vanilla, visual, log);
		return false;
	}

	private static bool TryCreateOwnedSkinnedMapFitCacheKey(
		GameObject template,
		GameObject shell,
		GameObject visual,
		Entry entry,
		out OwnedSkinnedMapFitCacheKey key)
	{
		key = default;
		if (!template || !shell || !visual || entry == null
		    || !entry.BattleHeightHexes.HasValue || !_battleWorldHeightPerHex.HasValue
		    || !_adventureMapToBattleHeightRatio.HasValue)
			return false;

		key = new OwnedSkinnedMapFitCacheKey(
			template.GetInstanceID(),
			entry,
			_battleWorldHeightPerHex.Value,
			_adventureMapToBattleHeightRatio.Value,
			QualitySettings.skinWeights,
			shell.transform,
			visual.transform);
		return true;
	}

	private static bool IsFinitePositive(float value)
	{
		return !float.IsNaN(value) && !float.IsInfinity(value) && value > 0f;
	}

	private static bool TryGetOwnedSkinnedHexFloorY(GameObject skinned, out float floorY)
	{
		floorY = 0f;
		if (!skinned)
			return false;
		var hexRoot = skinned.transform.parent;
		if (hexRoot && IsOwnedSkinnedOrientationNode(hexRoot))
			hexRoot = hexRoot.parent;
		floorY = hexRoot ? hexRoot.position.y : 0f;
		return !float.IsNaN(floorY) && !float.IsInfinity(floorY);
	}

	private static bool ApplyOwnedSkinnedFeetFloorOffset(GameObject skinned, float feetOffsetFromFloor)
	{
		if (!TryGetOwnedSkinnedHexFloorY(skinned, out var floorY)
		    || float.IsNaN(feetOffsetFromFloor) || float.IsInfinity(feetOffsetFromFloor))
			return false;
		var p = skinned.transform.position;
		p.y = floorY + feetOffsetFromFloor;
		skinned.transform.position = p;
		return true;
	}

	internal static void SampleOwnedSkinnedIdlePose(GameObject instance)
	{
		if (!instance)
			return;
		var animators = instance.GetComponentsInChildren<Animator>(true);
		for (var i = 0; i < animators.Length; i++)
		{
			var animator = animators[i];
			if (!animator)
				continue;
			animator.enabled = true;
			animator.applyRootMotion = false;
			animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
			animator.Update(0f);
		}
	}

	private static Mesh _renderableBoundsBakeScratch;

	/// <summary>
	/// World AABB of what a skinned renderer draws in its current pose: <see cref="SkinnedMeshRenderer.BakeMesh(Mesh, bool)"/>
	/// (bones + blend shapes) with useScale=true, so the baked vertices are in the renderer transform's own
	/// local space. This is the same silhouette the vanilla calibration measured (native_battle_height.json,
	/// exact posed vertices). <c>localBounds</c> is not used: owned bundles ship UpdateWhenOffscreen with an empty
	/// AABB, so Unity answers from the serialized per-bone AABBs (which include the full blend-shape envelope,
	/// shrinking and floating DEF-retarget units) in root-bone space (misplacing mount rigs whose root bone is
	/// translated). Gate: tools/validate_homm3_owned_unit_presentation_contract.py.
	/// </summary>
	private static bool TryGetBakedSkinWorldBounds(SkinnedMeshRenderer skin, out Bounds world)
	{
		world = default;
		if (!skin || !skin.sharedMesh)
			return false;
		if (!_renderableBoundsBakeScratch)
		{
			_renderableBoundsBakeScratch = new Mesh();
			_renderableBoundsBakeScratch.name = "__homm3_renderable_bounds_bake__";
			_renderableBoundsBakeScratch.hideFlags = HideFlags.HideAndDontSave;
		}
		skin.BakeMesh(_renderableBoundsBakeScratch, true);
		var verts = _renderableBoundsBakeScratch.vertices;
		if (verts == null || verts.Length == 0)
			return false;
		var m = skin.transform.localToWorldMatrix;
		var any = false;
		for (var i = 0; i < verts.Length; i++)
		{
			var p = m.MultiplyPoint3x4(verts[i]);
			if (!any)
			{
				world = new Bounds(p, Vector3.zero);
				any = true;
			}
			else
				world.Encapsulate(p);
		}
		return any;
	}

	internal static bool TryGetRenderableWorldBounds(GameObject go, out Bounds merged)
	{
		merged = default;
		if (!go)
			return false;
		var any = false;
		var skins = go.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		for (var i = 0; i < skins.Length; i++)
		{
			var skin = skins[i];
			if (!skin || !skin.enabled)
				continue;
			// No mesh draws nothing; there is no bone-AABB fallback (see TryGetBakedSkinWorldBounds).
			if (!TryGetBakedSkinWorldBounds(skin, out var world))
				continue;
			if (!any)
			{
				merged = world;
				any = true;
			}
			else
				merged.Encapsulate(world);
		}
		if (any)
			return true;
		var renderers = go.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (!renderer || !renderer.enabled)
				continue;
			if (!any)
			{
				merged = renderer.bounds;
				any = true;
			}
			else
				merged.Encapsulate(renderer.bounds);
		}
		return any;
	}

	private static Material _cachedNativeHexLitSheet;

	internal static void FitSkinnedMeshToDonorWorldHeight(GameObject donor, GameObject skinned, ManualLogSource log)
	{
		if (!skinned)
			return;
		skinned.transform.localScale = Vector3.one;
		EnsureOwnedSkinnedDeliveryOrientation(skinned, log);
		SampleOwnedSkinnedIdlePose(skinned);
		if (!TryGetRenderableWorldBounds(skinned, out var skinnedBounds) || skinnedBounds.size.y < 1e-4f)
		{
			log?.LogError("Homm3Import skinned fit: owned mesh has no measurable height.");
			return;
		}
		if (!donor || !TryGetRenderableWorldBounds(donor, out var donorBounds) || donorBounds.size.y < 1e-4f)
		{
			log?.LogError("Homm3Import skinned fit: donor has no measurable world height; leaving owned mesh at localScale 1.");
			AlignOwnedSkinnedFeetToDonor(null, skinned);
			return;
		}
		ApplyUniformWorldHeightFit(skinned, skinnedBounds.size.y, donorBounds.size.y, log, "donor");
		AlignOwnedSkinnedFeetToDonor(donor, skinned);
	}

	/// <summary>
	/// Battle-size an owned skinned instance. When the import entry declares <c>battleHeightHexes</c> and the
	/// table declares <c>battleWorldHeightPerHex</c>, the mesh is fit to that product (HoMM3-proportional sizing,
	/// logged once per fit as source=hex). Otherwise the donor's renderer height is used, as before. The
	/// hex-based path is the only one that makes units comparable to each other: donor bounds depend on
	/// whatever stock prefab happened to be the presentation shell.
	/// </summary>
	internal static void FitSkinnedBattleMesh(GameObject donor, GameObject skinned, Entry entry, ManualLogSource log)
	{
		if (!skinned)
			return;
		if (entry == null || !entry.BattleHeightHexes.HasValue || !_battleWorldHeightPerHex.HasValue)
		{
			FitSkinnedMeshToDonorWorldHeight(donor, skinned, log);
			return;
		}
		skinned.transform.localScale = Vector3.one;
		EnsureOwnedSkinnedDeliveryOrientation(skinned, log);
		SampleOwnedSkinnedIdlePose(skinned);
		if (!TryGetRenderableWorldBounds(skinned, out var skinnedBounds) || skinnedBounds.size.y < 1e-4f)
		{
			log?.LogError("Homm3Import skinned fit: owned mesh has no measurable height.");
			return;
		}
		var hexes = entry.BattleHeightHexes.Value;
		var target = hexes * _battleWorldHeightPerHex.Value;
		var fit = target / skinnedBounds.size.y;
		if (float.IsNaN(fit) || float.IsInfinity(fit) || fit <= 0f)
		{
			log?.LogError("Homm3Import skinned fit: invalid hex factor " + fit + " for '" + entry.BattleResPath + "'.");
			return;
		}
		skinned.transform.localScale = Vector3.one * fit;
		AlignOwnedSkinnedFeetToDonor(donor, skinned);
		var donorY = donor && TryGetRenderableWorldBounds(donor, out var donorBounds) ? donorBounds.size.y : float.NaN;
		log?.LogInfo(
			"Homm3Import skinned fit source=hex entry='" + entry.BattleResPath
			+ "' hexes=" + hexes.ToString("F2")
			+ " perHex=" + _battleWorldHeightPerHex.Value.ToString("F3")
			+ " targetY=" + target.ToString("F3")
			+ " meshY=" + skinnedBounds.size.y.ToString("F3")
			+ " donorY=" + donorY.ToString("F3")
			+ " localScale=" + fit.ToString("F4") + ".");
	}

	/// <summary>
	/// Stand an owned skinned preview mesh where a vanilla 3D mesh stands.
	/// Copies the 3D donor's local pose, fits height to that donor, then centers
	/// visual mass on the donor bounds (or the preview-slot origin). Does not plant
	/// feet on parent Y — that hex-floor plant hid previews off-camera.
	/// Refuses leftover billboard pose plus preview-background AABB slot fitting.
	/// </summary>
	internal static void PlaceOwnedSkinnedPreviewAtVanillaMeshPose(
		GameObject vanillaDonor,
		GameObject skinned,
		ManualLogSource log)
	{
		if (!skinned)
			return;
		var slot = skinned.transform;
		if (!slot)
			return;

		if (vanillaDonor
		    && vanillaDonor.transform
		    && vanillaDonor.GetInstanceID() != skinned.GetInstanceID()
		    && !LooksLikeHomm3BillboardPreviewDonor(vanillaDonor))
		{
			slot.localPosition = vanillaDonor.transform.localPosition;
			slot.localRotation = vanillaDonor.transform.localRotation;
			slot.localScale = Vector3.one;
			EnsureOwnedSkinnedDeliveryOrientation(skinned, log);
			SampleOwnedSkinnedIdlePose(skinned);
			if (TryGetRenderableWorldBounds(skinned, out var skinnedBounds) && skinnedBounds.size.y > 1e-4f
			    && TryGetRenderableWorldBounds(vanillaDonor, out var donorBounds) && donorBounds.size.y > 1e-4f)
				ApplyUniformWorldHeightFit(skinned, skinnedBounds.size.y, donorBounds.size.y, log, "preview-donor");
			// The copied root pose is only half of the native facing: the vanilla model turns its mesh on its
			// scale_roll child (+90 on battle prefabs). Take that yaw before centering, since it moves the bounds.
			TryApplyOwnedSkinnedNativeModelFacing(vanillaDonor, skinned, "preview", log);
			AlignOwnedSkinnedPreviewToDonorCenter(vanillaDonor, skinned);
			log?.LogInfo(
				"Homm3Import skinned preview pose: copied vanilla 3D mesh pose and centered visual mass name='"
				+ skinned.name
				+ "' localPos="
				+ slot.localPosition.ToString("F3")
				+ ".");
			return;
		}

		if (vanillaDonor && vanillaDonor.GetInstanceID() == skinned.GetInstanceID())
		{
			AlignOwnedSkinnedPreviewToParentSlot(skinned);
			log?.LogInfo(
				"Homm3Import skinned preview pose: centered already-placed mesh on preview slot name='"
				+ skinned.name
				+ "' localPos="
				+ slot.localPosition.ToString("F3")
				+ ".");
			return;
		}

		slot.localPosition = Vector3.zero;
		slot.localRotation = Quaternion.identity;
		slot.localScale = Vector3.one;
		TryApplyOwnedSkinnedBattlePrefabFacing(skinned, "preview-synthetic", log);
		AlignOwnedSkinnedPreviewToParentSlot(skinned);
		log?.LogWarning(
			"Homm3Import skinned preview pose: no vanilla 3D donor; centered on preview-slot origin name='"
			+ skinned.name
			+ "'.");
	}

	private static void AlignOwnedSkinnedPreviewToDonorCenter(GameObject donor, GameObject skinned)
	{
		if (!donor || !skinned)
			return;
		if (!TryGetRenderableWorldBounds(donor, out var donorBounds))
			return;
		if (!TryGetRenderableWorldBounds(skinned, out var skinnedBounds))
			return;
		skinned.transform.position += donorBounds.center - skinnedBounds.center;
	}

	private static void AlignOwnedSkinnedPreviewToParentSlot(GameObject skinned)
	{
		if (!skinned || !skinned.transform.parent)
			return;
		if (!TryGetRenderableWorldBounds(skinned, out var skinnedBounds))
			return;
		skinned.transform.position += skinned.transform.parent.position - skinnedBounds.center;
	}

	private static bool AlignOwnedSkinnedFeetToDonor(GameObject donor, GameObject skinned)
	{
		if (!skinned)
			return false;
		if (!TryGetRenderableWorldBounds(skinned, out var skinnedBounds))
			return false;
		// Battle's native visual is unit_cutout; that billboard AABB is not the hex floor.
		// Plant onto the hex container (Unit / map shell), skipping an inserted Orientation parent.
		var hexRoot = skinned.transform.parent;
		if (hexRoot && IsOwnedSkinnedOrientationNode(hexRoot))
			hexRoot = hexRoot.parent;
		var targetMinY = hexRoot ? hexRoot.position.y : 0f;
		var p = skinned.transform.position;
		p.y += targetMinY - skinnedBounds.min.y;
		skinned.transform.position = p;
		return true;
	}

	internal static void EnsureOwnedSkinnedDeliveryOrientation(GameObject skinned, ManualLogSource log)
	{
		if (!skinned)
			return;

		// Zero the prefab's baked wrap before measuring fits; every lane then sets this same child to the
		// native presentation yaw minus OwnedSkinnedBindFacingYaw (OwnedSkinnedOrientationYawFor): battle side
		// heading (TryApplyOwnedSkinnedSideFacing), the native model's scale_roll yaw on the map and vanilla-donor
		// preview (TryApplyOwnedSkinnedNativeModelFacing), the battle-prefab +90 in the synthetic preview.
		var self = skinned.transform;
		var neutralized = 0;
		var transforms = skinned.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (!t || t == self || !IsOwnedSkinnedOrientationNode(t))
				continue;
			if (t.localRotation == Quaternion.identity)
				continue;
			t.localRotation = Quaternion.identity;
			neutralized++;
		}

		log?.LogInfo(
			"Homm3Import skinned orientation: idle-0 bind already faces Unity forward; leaving native identity yaw name='"
			+ skinned.name
			+ "' neutralizedWrap="
			+ neutralized
			+ ".");
	}

	static int _ownedSkinnedNativeFacingLogs;

	/// <summary>
	/// Fleet asset convention: an owned skinned unit's idle-0 mesh faces this yaw inside its Orientation node.
	/// The capture/idle-0 lanes wrap the fitted bind at one hex side clockwise of +Z (lab prefab limb-line median
	/// about -55 over the fleet), and the battle side heading has always compensated it (left 150 = native +90
	/// minus this). Every lane therefore sets Orientation to the native presentation yaw minus this value, so all
	/// lanes agree with battle. Measured per unit by tools/validate_homm3_owned_skinned_facing_contract.py.
	/// </summary>
	internal const float OwnedSkinnedBindFacingYaw = -60f;

	/// <summary>Native Olden Era battle prefabs turn their mesh +90 on the scale_roll child (165 of 176).</summary>
	internal const float NativeBattleScaleRollYaw = 90f;

	internal static float OwnedSkinnedOrientationYawFor(float nativePresentationYaw)
	{
		return nativePresentationYaw - OwnedSkinnedBindFacingYaw;
	}

	/// <summary>
	/// World rotation of an owned skinned unit's body frame (idle-0 forward = +Z): its Orientation /
	/// MocapDeliveryRoot node turned by <see cref="OwnedSkinnedBindFacingYaw"/>. A host with no such node
	/// (the finder fell back to the root) is its own body frame.
	/// </summary>
	internal static Quaternion OwnedSkinnedBodyRotation(Transform orientation)
	{
		var name = orientation.name;
		if (name == "Orientation" || name == "MocapDeliveryRoot")
			return orientation.rotation * Quaternion.Euler(0f, OwnedSkinnedBindFacingYaw, 0f);
		return orientation.rotation;
	}

	/// <summary>
	/// Native Olden Era unit prefabs face their mesh along the first child's +Z and put the presentation yaw
	/// on that child (<c>scale_roll</c> / <c>Scale_roll</c> / <c>Scale_roll_pos</c>): +90 on 165 of 176 battle
	/// prefabs, an authored per-unit yaw of roughly 120-240 degrees (toward the camera) on <c>_map</c> prefabs.
	/// Native code never rotates the prefab root for a map squad (SquadDrawer.Init), so a swap that keeps only
	/// the root pose and leaves our Orientation at identity faces the unit along the shell's +Z, away from the
	/// camera. This sets our Orientation node to the native child's yaw minus the fleet bind facing
	/// (<see cref="OwnedSkinnedOrientationYawFor"/>), the same rule as battle. The native X-mirror scale on some
	/// map prefabs does not change a +Z forward and is not copied. Fails closed (LogError, no substitute yaw)
	/// when either node is missing. Battle facing is separate (<see cref="TryApplyOwnedSkinnedSideFacing"/>).
	/// Contract: tools/validate_homm3_owned_skinned_facing_contract.py.
	/// </summary>
	internal static bool TryApplyOwnedSkinnedNativeModelFacing(GameObject nativeModelRoot, GameObject skinned, string lane, ManualLogSource log)
	{
		if (!nativeModelRoot || !skinned)
			return false;
		var nativeNode = FindNativeModelFacingNode(nativeModelRoot, skinned);
		var node = FindOwnedSkinnedSideFacingNode(skinned);
		if (!nativeNode || !node)
		{
			log?.LogError(
				"Homm3Import skinned native facing (" + lane + "): "
				+ (!nativeNode ? "native model '" + (nativeModelRoot.name ?? "?") + "' has no scale_roll child" : "")
				+ (!nativeNode && !node ? "; " : "")
				+ (!node ? "no Orientation/MocapDeliveryRoot child on '" + (skinned.name ?? "?") + "'" : "")
				+ "; the owned unit keeps its bind yaw and may face away from the camera.");
			return false;
		}
		var forward = nativeNode.localRotation * Vector3.forward;
		var nativeYaw = Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg;
		var yaw = OwnedSkinnedOrientationYawFor(nativeYaw);
		node.localRotation = Quaternion.Euler(0f, yaw, 0f);
		if (_ownedSkinnedNativeFacingLogs < 32)
		{
			_ownedSkinnedNativeFacingLogs++;
			log?.LogInfo(
				"Homm3Import skinned native facing (" + lane + "): name='"
				+ (skinned.name ?? "?")
				+ "' native='"
				+ (nativeModelRoot.name ?? "?") + "/" + (nativeNode.name ?? "?")
				+ "' node='"
				+ (node.name ?? "?")
				+ "' nativeYaw="
				+ nativeYaw.ToString("0.0")
				+ " yaw="
				+ yaw.ToString("0.0")
				+ ".");
		}
		return true;
	}

	/// <summary>
	/// Synthetic preview (no vanilla 3D model to copy): the native preview spawns the battle prefab, whose
	/// scale_roll carries +90, so our Orientation takes that presentation yaw under the fleet rule.
	/// </summary>
	internal static bool TryApplyOwnedSkinnedBattlePrefabFacing(GameObject skinned, string lane, ManualLogSource log)
	{
		var node = FindOwnedSkinnedSideFacingNode(skinned);
		if (!node)
		{
			log?.LogError(
				"Homm3Import skinned facing (" + lane + "): no Orientation/MocapDeliveryRoot child on '"
				+ (skinned ? skinned.name ?? "?" : "?")
				+ "'; the owned unit keeps its bind yaw.");
			return false;
		}
		node.localRotation = Quaternion.Euler(0f, OwnedSkinnedOrientationYawFor(NativeBattleScaleRollYaw), 0f);
		return true;
	}

	private static Transform FindNativeModelFacingNode(GameObject nativeModelRoot, GameObject skinned)
	{
		var root = nativeModelRoot.transform;
		var own = skinned.transform;
		for (var i = 0; i < root.childCount; i++)
		{
			var child = root.GetChild(i);
			if (!child || child == own || own.IsChildOf(child))
				continue;
			var name = (child.name ?? string.Empty).Trim();
			if (name.StartsWith("scale_roll", StringComparison.OrdinalIgnoreCase))
				return child;
		}
		return null;
	}

	internal static bool TryApplyOwnedSkinnedSideFacing(GameObject skinned, bool leftSide, ManualLogSource log)
	{
		if (!skinned)
			return false;
		var node = FindOwnedSkinnedSideFacingNode(skinned);
		if (!node)
		{
			log?.LogError(
				"Homm3Import skinned side facing: no Orientation/MocapDeliveryRoot child on '"
				+ (skinned.name ?? "?")
				+ "'; native ecz identity leaves both sides facing the same way.");
			return false;
		}
		// Native side heading +90 / -90 under the fleet rule: left 150 / right -30 (unchanged values).
		var yaw = OwnedSkinnedOrientationYawFor(leftSide ? NativeBattleScaleRollYaw : -NativeBattleScaleRollYaw);
		node.localRotation = Quaternion.Euler(0f, yaw, 0f);
		log?.LogInfo(
			"Homm3Import skinned side facing: name='"
			+ (skinned.name ?? "?")
			+ "' node='"
			+ (node.name ?? "?")
			+ "' leftSide="
			+ leftSide
			+ " yaw="
			+ yaw.ToString("0")
			+ ".");
		return true;
	}

	private static Transform FindOwnedSkinnedSideFacingNode(GameObject skinned)
	{
		if (!skinned)
			return null;
		var self = skinned.transform;
		Transform fallback = null;
		var transforms = skinned.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (!t || t == self || !IsOwnedSkinnedOrientationNode(t))
				continue;
			if (string.Equals(t.name, "Orientation", StringComparison.Ordinal))
				return t;
			if (!fallback)
				fallback = t;
		}
		return fallback;
	}

	private static bool IsOwnedSkinnedOrientationNode(Transform t)
	{
		if (!t)
			return false;
		return string.Equals(t.name, "Orientation", StringComparison.Ordinal)
		       || string.Equals(t.name, "MocapDeliveryRoot", StringComparison.Ordinal);
	}

	private static bool HasOwnedSkinnedDeliveryOrientation(GameObject skinned)
	{
		if (!skinned)
			return false;
		var self = skinned.transform;
		if (IsOwnedSkinnedOrientationNode(self.parent))
			return true;
		var transforms = skinned.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (!t || t == self)
				continue;
			if (IsOwnedSkinnedOrientationNode(t))
				return true;
		}
		return false;
	}

	private static int _skinnedFitLogs;
	private static bool _skinWeightsUnlimitedLogged;

	private static void ApplyUniformWorldHeightFit(GameObject skinned, float currentWorldHeight, float targetWorldHeight, ManualLogSource log, string source)
	{
		var fit = targetWorldHeight / currentWorldHeight;
		if (float.IsNaN(fit) || float.IsInfinity(fit) || fit <= 0f)
		{
			log?.LogError("Homm3Import skinned fit: invalid factor " + fit + " source=" + source + ".");
			return;
		}
		skinned.transform.localScale = Vector3.one * fit;
		if (_skinnedFitLogs >= 24)
			return;
		_skinnedFitLogs++;
		log?.LogInfo(
			"Homm3Import skinned fit source="
			+ source
			+ " currentY="
			+ currentWorldHeight.ToString("F3")
			+ " targetY="
			+ targetWorldHeight.ToString("F3")
			+ " localScale="
			+ fit.ToString("F4")
			+ " name='"
			+ skinned.name
			+ "'.");
	}

	/// <summary>UI unit-preview lanes (detail window, synthetic preview mesh) only.</summary>
	internal static void PrepareOwnedSkinnedIdleInstance(GameObject visual, Entry entry, ManualLogSource log, GameObject hexLitDonor = null)
	{
		EnsureSkinnedAdventureMapIdle(visual, entry, log, hexLitDonor, uiPreviewLane: true);
	}

	private static void EnsureSkinnedAdventureMapIdle(GameObject visual, Entry entry, ManualLogSource log, GameObject hexLitDonor = null, bool preserveAdventureHexFog = false, bool uiPreviewLane = false)
	{
		if (!visual)
			return;
		foreach (var animator in visual.GetComponentsInChildren<Animator>(true))
		{
			if (!animator)
				continue;
			animator.applyRootMotion = false;
			animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
			animator.enabled = true;
		}
		EnsureSkinnedBattleRuntimeCompatibility(visual, hexLitDonor, entry, log, preserveAdventureHexFog, attachUnitLookVfx: false, uiPreviewLane: uiPreviewLane);
		// Idle vanilla-style particles play wherever the idle plays (user direction 2026-09-26).
		Homm3MeshFx.TryAttachForSkinnedPresentation(
			visual, entry, uiPreviewLane ? "ui-preview" : "adventure-map", log);
	}

	/// <summary>
	/// Keeps the owned skinned lane independent from editor-only shader support and renderer culling.
	/// Bundle materials reference the native Hex/Lit GUID, which the Unity lab cannot serialize; at
	/// runtime they become FallbackError. Resolve <c>Hex/Lit</c> by name (same pattern as
	/// <see cref="Homm3MapBuildingMeshProjectedFx"/>) and prefer it over any donor shader — the
	/// presentation/native donor may be unit_cutout, which is a flat billboard shader and must
	/// never be applied to a 3D skinned mesh.
	/// </summary>
	internal static bool EnsureSkinnedBattleRuntimeCompatibility(GameObject instance, GameObject donor, Entry entry, ManualLogSource log, bool preserveAdventureHexFog = false, bool attachUnitLookVfx = true, bool uiPreviewLane = false)
	{
		if (!IsHomm3SkinnedBattleInstance(instance))
			return false;

		var skins = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		var animator = instance.GetComponentInChildren<Animator>(true);
		if (skins == null || skins.Length == 0 || animator == null || !animator)
			return false;

		animator.enabled = true;
		animator.applyRootMotion = false;
		animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
		var unlimitedMarker = instance.transform.Find(SkinWeightsUnlimitedMarkerName);
		if (unlimitedMarker != null && unlimitedMarker)
		{
			var previousSkinWeights = QualitySettings.skinWeights;
			QualitySettings.skinWeights = SkinWeights.Unlimited;
			for (var i = 0; i < skins.Length; i++)
			{
				if (skins[i] == null || !skins[i])
					continue;
				skins[i].quality = SkinQuality.Auto;
			}
			if (QualitySettings.skinWeights != SkinWeights.Unlimited)
				log?.LogError("Homm3Import: explicit skin-weight capability marker was present, but Unity did not retain SkinWeights.Unlimited (previous=" + previousSkinWeights + ").");
			else if (!_skinWeightsUnlimitedLogged)
			{
				_skinWeightsUnlimitedLogged = true;
				log?.LogInfo("Homm3Import: explicit skin-weight capability marker enabled SkinWeights.Unlimited; marked renderers use SkinQuality.Auto.");
			}
		}
		for (var i = 0; i < skins.Length; i++)
		{
			if (skins[i] != null && skins[i])
				skins[i].updateWhenOffscreen = true;
		}
		// def_retarget unit-look VFX (billboard/ground flipbooks, effect lights, uvAtlas snap);
		// a prefab without __homm3_vfx_* nodes gets nothing. Independent of the Hex/Lit rebind below.
		// Battle only: the adventure-map idle (EnsureSkinnedAdventureMapIdle) passes false.
		if (attachUnitLookVfx)
			Homm3UnitLookVfxRuntime.TryAttach(instance, log);

		var hexLit = ResolveOwnedSkinnedHexLitShader(donor, log);
		if (hexLit == null)
		{
			log?.LogWarning(
				"Homm3Import: owned skinned lane could not resolve Hex/Lit; leaving materials unchanged "
				+ "(refuse unit_cutout / non-Hex/Lit donor shaders).");
			return true;
		}

		// Shader.Find("Hex/Lit") is a shader asset, not a native property sheet: clone a loaded
		// native Hex/Lit material instead. Combat Init must not ResManager-load donors.
		// The installed Hex/Lit declares no _BumpMap/_NormalMap/_MetallicGlossMap (DXBC read,
		// docs/homm3_prebaked_lighting.md), so the donor gate is "a native Hex/Lit sheet with
		// _MainTex"; requiring the PBR slots refused every owned skinned unit.
		var donorMaterial = TryGetHexLitDonorMaterial(donor);
		if (!OwnedSkinnedHexLitSheetUsable(donorMaterial))
			donorMaterial = _cachedNativeHexLitSheet;
		if (!OwnedSkinnedHexLitSheetUsable(donorMaterial)
		    && EsquirePikemanVisuals.TryFindLoadedUnitStyleHexLitMapDonor(log, out var loadedHexLit)
		    && OwnedSkinnedHexLitSheetUsable(loadedHexLit))
			donorMaterial = loadedHexLit;
		if (!OwnedSkinnedHexLitSheetUsable(donorMaterial))
		{
			log?.LogError(
				"Homm3Import: owned skinned Hex/Lit rebind refused: no native Hex/Lit sheet is loaded.");
			LogSkinnedBattleLaneState(instance, log);
			return true;
		}
		// A UI-preview donor is a per-preview material *instance* ("twinkle_mushroom_mat (Instance)")
		// whose per-material state belongs to the preview camera. It must never become the shared
		// sheet that battle / adventure-map clones start from (2026-09-26: battle units invisible
		// after a detail preview had cached its sheet).
		if (!uiPreviewLane)
			_cachedNativeHexLitSheet = donorMaterial;
		var lane = uiPreviewLane ? "ui-preview" : preserveAdventureHexFog ? "adventure-map" : "battle";
		LogOwnedSkinnedHexLitDonorState(donorMaterial, lane, log);

		var changedMaterials = 0;
		for (var i = 0; i < skins.Length; i++)
		{
			var skin = skins[i];
			if (!skin)
				continue;
			var materials = skin.sharedMaterials;
			if (materials == null || materials.Length == 0)
				continue;
			var changed = false;
			for (var j = 0; j < materials.Length; j++)
			{
				var material = materials[j];
				if (material == null || !OwnedSkinnedMaterialNeedsHexLit(material))
					continue;
				try
				{
					var fallback = new Material(donorMaterial)
					{
						name = material.name + "_runtime_native"
					};
					EsquirePikemanVisuals.SanitizeMapMaterialForOpaqueMesh(fallback);
					// Opaque Hex/Lit like vanilla 3D units. Alpha-clip stays off so the mesh is
					// not hole-punched. Adventure-map FoW uses Hex/Lit dither + _HexFade; battle
					// turns dither off because combat is not adventure fog.
					fallback.SetFloat("_RenderMode", 1f);
					fallback.SetFloat("_CullMode", 2f);
					fallback.SetFloat("_SrcBlend", 1f);
					fallback.SetFloat("_DstBlend", 0f);
					fallback.SetFloat("_ZWrite", 1f);
					fallback.SetFloat("_ZTest", 4f);
					fallback.SetFloat("_AlphaClipEnabled", 0f);
					fallback.DisableKeyword("HEX_ALPHA_CLIP_ENABLED");
					if (!preserveAdventureHexFog)
					{
						fallback.SetFloat("_DitherFadeEnabled", 0f);
						fallback.DisableKeyword("HEX_DITHER_FADE_ENABLED");
					}
					fallback.renderQueue = 2450;
					// Never trust the bundle sheet's color: observed black at runtime despite white
					// serialized values.
					fallback.SetColor("_Color", Color.white);
					fallback.SetColor("_AlbedoColor", Color.white);
					if (!uiPreviewLane)
						ResetOwnedSkinnedHexLitInstanceState(fallback);
					// The clone stays per instance (not shared per entry/lane): native Hex/Lit fog and fade,
					// MeshFx and the visible-state probe may write per-renderer material state, so one
					// shared sheet could leak one unit's state into every copy. Only the texture lookups
					// are cached (OwnedSkinnedBundleTextureCache), and the normal/metal maps are looked up
					// only when this Hex/Lit declares a slot for them (the installed one declares none).
					var bundleTexture = TryLoadOwnedSkinnedBundleTexture(entry, material, log);
					var wantsPbrMaps = fallback.HasProperty("_BumpMap") || fallback.HasProperty("_NormalMap")
					                   || fallback.HasProperty("_MetallicGlossMap");
					var bundleNormal = wantsPbrMaps
						? TryLoadOwnedSkinnedBundleNamedTexture(entry, material, log, "normal.png")
						: null;
					var bundleMetallicGloss = wantsPbrMaps
						? TryLoadOwnedSkinnedBundleNamedTexture(entry, material, log, "metallicgloss.png")
						: null;
					ApplyOwnedSkinnedHexLitPbr(fallback, bundleTexture, bundleNormal, bundleMetallicGloss, log);
					// Vanilla-style body glow (homm3_mesh_fx battle_emission rows): after the sanitise
					// above has blacked _EmissionColor, so it is never overwritten by this rebind.
					Homm3MeshFx.TryApplyBodyEmission(fallback, entry, lane, log);
					// Vanilla-style body motion (battle_body_displacement rows): Hex/Lit FLAG displacement masked
					// by this mesh's baked COLOR_0.r; refused when the skin's mesh has no colour stream.
					Homm3MeshFx.TryApplyBodyDisplacement(fallback, skin, entry, lane, log);
					// Emission never touches _MainTex, so the albedo check reads the final binding.
					VerifyOwnedSkinnedAlbedoBound(fallback, bundleTexture, entry, lane, log);
					materials[j] = fallback;
					changed = true;
					changedMaterials++;
				}
				catch (Exception ex)
				{
					log?.LogError("Homm3Import: skinned material Hex/Lit rebind failed for '" + material.name + "': " + ex.Message);
				}
			}
			if (changed)
				skin.sharedMaterials = materials;
		}

		if (changedMaterials > 0)
			log?.LogInfo(
				"Homm3Import: rebound " + changedMaterials
				+ " owned skinned material(s) to runtime Hex/Lit; donorBase="
				+ (donorMaterial != null ? "yes" : "no")
				+ ".");
		if (!uiPreviewLane)
			VerifyOwnedSkinnedHexLitVisibleState(instance, entry, lane, log);
		LogSkinnedBattleLaneState(instance, log);
		return true;
	}

	// Visibility reference: the installed native unit sheets (Esquire_mat, twinkle_*_mat,
	// lightweaver_mat, troglodyte_mt ...; UnityPy read of resources.assets 2026-09-26: 1169 of 1171
	// Hex/Lit materials) all serialize these values. The Hex/Lit Lit-pass vertex shader applies
	// UnityPerMaterial._PreviewScreenOffset (cb2[11]) to clip-space xy in *every* variant
	// (clip.xy += clip.w * offset.xy), not only under HEX_UI_PREVIEW_CAMERA, and the dither/cutout
	// fade variants discard on _HexFade. The UI preview renders its model through per-renderer
	// material instances, so a sheet cloned from a preview donor carries preview-only state that
	// moves or fades a battle/map draw off screen.
	private static readonly string[] OwnedSkinnedHexLitZeroVectors = { "_PreviewScreenOffset", "_HexFade", "_UvScroll", "_TerrainBlendParams" };
	private static readonly string[] OwnedSkinnedHexLitZeroFloats = { "_StencilWriteMask", "_OffsetFactor", "_OffsetUnits", "_HighlightTag" };
	private static readonly string[] OwnedSkinnedHexLitForbiddenKeywords =
	{
		"HEX_UI_PREVIEW_CAMERA",
		"HEX_CUTOUT_FADE_ENABLED",
		"HEX_WORLD_SPACE_FADE",
		"HEX_BLEND_INTO_TERRAIN",
		"HEX_BLEND_INTO_TERRAIN_POSITION",
		"HEX_BLEND_INTO_TERRAIN_COLOR",
		"HEX_VERTEX_DISPLACEMENT_FLAG",
		"HEX_VERTEX_DISPLACEMENT_TREE",
	};

	/// <summary>
	/// Battle / adventure-map clone: reset every per-material value a donor instance may carry from
	/// another render context to the native unit sheet's serialized value (see reference above).
	/// </summary>
	private static void ResetOwnedSkinnedHexLitInstanceState(Material material)
	{
		if (!material)
			return;
		for (var i = 0; i < OwnedSkinnedHexLitZeroVectors.Length; i++)
		{
			if (material.HasProperty(OwnedSkinnedHexLitZeroVectors[i]))
				material.SetVector(OwnedSkinnedHexLitZeroVectors[i], Vector4.zero);
		}
		for (var i = 0; i < OwnedSkinnedHexLitZeroFloats.Length; i++)
		{
			if (material.HasProperty(OwnedSkinnedHexLitZeroFloats[i]))
				material.SetFloat(OwnedSkinnedHexLitZeroFloats[i], 0f);
		}
		for (var i = 0; i < OwnedSkinnedHexLitForbiddenKeywords.Length; i++)
			material.DisableKeyword(OwnedSkinnedHexLitForbiddenKeywords[i]);
		// Fade mode enum (None 0, Dither 1, WorldSpace 2, Cutout 3): only None or Dither is native for units.
		if (material.HasProperty("_DitherFadeEnabled") && material.GetFloat("_DitherFadeEnabled") > 1.5f)
			material.SetFloat("_DitherFadeEnabled", 0f);
	}

	private static int _ownedSkinnedHexLitDonorLogs;

	private static void LogOwnedSkinnedHexLitDonorState(Material donor, string lane, ManualLogSource log)
	{
		if (!donor || log == null)
			return;
		var offset = SafeGetVector(donor, "_PreviewScreenOffset");
		var fade = SafeGetVector(donor, "_HexFade");
		var carriesPreviewState = offset.sqrMagnitude > 1e-12f || fade.sqrMagnitude > 1e-12f
		                          || HasMaterialKeyword(donor, "HEX_UI_PREVIEW_CAMERA");
		if (!carriesPreviewState && _ownedSkinnedHexLitDonorLogs >= 12)
			return;
		_ownedSkinnedHexLitDonorLogs++;
		var line = "Homm3Import: owned skinned Hex/Lit donor lane=" + lane
		           + " donor='" + (donor.name ?? "?") + "' previewScreenOffset=" + offset.ToString("F4")
		           + " hexFade=" + fade.ToString("F4") + " rq=" + donor.renderQueue
		           + " keywords=[" + string.Join(",", donor.shaderKeywords ?? Array.Empty<string>()) + "]";
		if (carriesPreviewState && lane != "ui-preview")
			log.LogWarning(line + " carries per-context state; the clone resets it to the native unit sheet values.");
		else
			log.LogInfo(line + ".");
	}

	private static Vector4 SafeGetVector(Material material, string property)
	{
		try
		{
			return material && material.HasProperty(property) ? material.GetVector(property) : Vector4.zero;
		}
		catch
		{
			return Vector4.zero;
		}
	}

	/// <summary>
	/// Fail-loud self-check: every rebound battle / adventure-map owned sheet must match a visible
	/// native unit sheet on the values that decide whether the draw lands on screen.
	/// </summary>
	private static void VerifyOwnedSkinnedHexLitVisibleState(GameObject instance, Entry entry, string lane, ManualLogSource log)
	{
		if (!instance || log == null)
			return;
		var mismatches = new List<string>();
		var checkedMaterials = 0;
		var skins = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		for (var i = 0; i < skins.Length; i++)
		{
			var skin = skins[i];
			if (!skin)
				continue;
			var materials = skin.sharedMaterials;
			for (var j = 0; materials != null && j < materials.Length; j++)
			{
				var m = materials[j];
				if (!m || !(m.name ?? string.Empty).EndsWith("_runtime_native", StringComparison.Ordinal))
					continue;
				checkedMaterials++;
				var where = skin.name + "[" + j + "] ";
				if (!EsquirePikemanVisuals.IsNativeHexLitShader(m.shader))
					mismatches.Add(where + "shader is not the native multi-pass Hex/Lit");
				for (var k = 0; k < OwnedSkinnedHexLitZeroVectors.Length; k++)
				{
					var v = SafeGetVector(m, OwnedSkinnedHexLitZeroVectors[k]);
					if (v.sqrMagnitude > 1e-12f)
						mismatches.Add(where + OwnedSkinnedHexLitZeroVectors[k] + "=" + v.ToString("F4") + " (native 0)");
				}
				for (var k = 0; k < OwnedSkinnedHexLitZeroFloats.Length; k++)
				{
					var name = OwnedSkinnedHexLitZeroFloats[k];
					if (m.HasProperty(name) && Mathf.Abs(m.GetFloat(name)) > 1e-6f)
						mismatches.Add(where + name + "=" + m.GetFloat(name) + " (native 0)");
				}
				RequireFloat(m, "_ZWrite", 1f, where, mismatches);
				RequireFloat(m, "_ZTest", 4f, where, mismatches);
				RequireFloat(m, "_SrcBlend", 1f, where, mismatches);
				RequireFloat(m, "_DstBlend", 0f, where, mismatches);
				if (m.HasProperty("_DitherFadeEnabled") && m.GetFloat("_DitherFadeEnabled") > 1.5f)
					mismatches.Add(where + "_DitherFadeEnabled=" + m.GetFloat("_DitherFadeEnabled") + " (native None/Dither)");
				if (m.HasProperty("_Color") && m.GetColor("_Color").a < 0.999f)
					mismatches.Add(where + "_Color.a=" + m.GetColor("_Color").a + " (native 1)");
				for (var k = 0; k < OwnedSkinnedHexLitForbiddenKeywords.Length; k++)
				{
					// Material IsKeywordEnabled(string) throws MissingMethodException (ReadOnlySpan) on this interop.
					var keyword = OwnedSkinnedHexLitForbiddenKeywords[k];
					if (!HasMaterialKeyword(m, keyword))
						continue;
					if (string.Equals(keyword, Homm3MeshFx.FlagDisplacementKeyword, StringComparison.Ordinal)
					    && Homm3MeshFx.IsExpectedBodyDisplacementApplied(m, skin, entry, lane))
						continue;
					mismatches.Add(where + "keyword " + keyword + " enabled");
				}
				if (m.renderQueue < 2000 || m.renderQueue > 2500)
					mismatches.Add(where + "renderQueue=" + m.renderQueue + " (native opaque 2000..2500)");
				if (!skin.enabled)
					mismatches.Add(where + "renderer disabled");
			}
		}
		if (mismatches.Count == 0)
			return;
		log.LogError(
			"Homm3Import: owned skinned Hex/Lit visibility self-check FAILED lane=" + lane
			+ " entry='" + (entry?.BattleResPath ?? "?") + "' instance='" + instance.name + "' checked=" + checkedMaterials
			+ " | " + string.Join(" | ", mismatches));
	}

	private static void RequireFloat(Material m, string property, float expected, string where, List<string> mismatches)
	{
		if (m.HasProperty(property) && Mathf.Abs(m.GetFloat(property) - expected) > 1e-4f)
			mismatches.Add(where + property + "=" + m.GetFloat(property) + " (native " + expected + ")");
	}

	/// <summary>
	/// Prefer <c>Shader.Find("Hex/Lit")</c>. Optional donor scan is secondary and must already be
	/// Hex/Lit — never the first supported donor shader (unit_cutout is supported and invisible on
	/// skinned meshes). Combat Init must not ResManager-load presentation donors just for this;
	/// pass <c>null</c> and rely on Shader.Find.
	/// </summary>
	private static Shader ResolveOwnedSkinnedHexLitShader(GameObject donor, ManualLogSource log)
	{
		try
		{
			var found = Shader.Find("Hex/Lit");
			if (found != null && found && found.isSupported
			    && string.Equals(found.name, "Hex/Lit", StringComparison.Ordinal))
			{
				log?.LogInfo("Homm3Import: owned skinned lane resolved Hex/Lit via Shader.Find.");
				return found;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Hex/Lit Shader.Find failed: " + ex.Message);
		}

		if (!donor)
			return null;

		try
		{
			var donorRenderers = donor.GetComponentsInChildren<Renderer>(true);
			for (var i = 0; i < donorRenderers.Length; i++)
			{
				var material = donorRenderers[i] ? donorRenderers[i].sharedMaterial : null;
				if (material == null || material.shader == null || !material.shader)
					continue;
				if (!material.shader.isSupported)
					continue;
				if (!string.Equals(material.shader.name, "Hex/Lit", StringComparison.Ordinal))
					continue;
				log?.LogInfo(
					"Homm3Import: owned skinned lane resolved Hex/Lit from donor material '"
					+ (material.name ?? "?") + "'.");
				return material.shader;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Hex/Lit donor scan failed: " + ex.Message);
		}

		return null;
	}

	/// <summary>A loaded native Hex/Lit sheet that can carry the unit's base colour.</summary>
	private static bool OwnedSkinnedHexLitSheetUsable(Material material)
	{
		// Native identity, not the name: the owned bundle's 1-pass "Hex/Lit" stub must never be a donor.
		return material
		       && EsquirePikemanVisuals.IsNativeHexLitShader(material.shader)
		       && material.HasProperty("_MainTex");
	}

	private static bool _ownedSkinnedHexLitNoPbrSlotsLogged;

	private static bool OwnedSkinnedMaterialNeedsHexLit(Material material)
	{
		if (material == null)
			return false;
		// Appended additive metal-shine pass (Homm3MetalShine): not a body sheet, never re-cloned to Hex/Lit.
		if ((material.name ?? string.Empty).StartsWith(Homm3MetalShine.MaterialPrefix, StringComparison.Ordinal))
			return false;
		var shader = material.shader;
		if (shader == null || !shader)
			return true;
		if (!shader.isSupported)
			return true;
		var name = shader.name ?? string.Empty;
		if (string.Equals(name, "Hex/Lit", StringComparison.Ordinal))
		{
			// Our own clone of a native sheet: already rebound (the installed Hex/Lit has no
			// normal/metal slots, so the map check below would re-clone it on every call).
			if ((material.name ?? string.Empty).EndsWith("_runtime_native", StringComparison.Ordinal))
				return false;
			// The generic lab lane rewrites the bundle material's shader GUID to the native
			// Hex/Lit, so the shader resolves at runtime — but the lab sheet only carries
			// albedo: the Etalon stock shader exposes no _BumpMap/_MetallicGlossMap slots, so
			// those binds silently no-op at build time and the sheet keeps metallic=1,
			// smoothness=0 defaults. That partial sheet renders as dull clay. A Hex/Lit
			// material missing its PBR maps still needs the rebind; a complete sheet skips it.
			var hasNormal = SafeGetTexture(material, "_BumpMap") != null || SafeGetTexture(material, "_NormalMap") != null;
			var hasMetallicGloss = SafeGetTexture(material, "_MetallicGlossMap") != null;
			return !hasNormal || !hasMetallicGloss;
		}
		// Bundle referenced the native Hex/Lit GUID the lab cannot carry → Unity Error/Fallback shader.
		if (name.IndexOf("FallbackError", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (name.IndexOf("InternalErrorShader", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (name.IndexOf("Hidden/InternalError", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		// glTF / PbrMetallicRoughness and any other non-Hex/Lit sheet skip OE fog and lighting.
		return true;
	}

	/// <summary>First supported Hex/Lit material on the donor (native presentation) hierarchy.</summary>
	private static Material TryGetHexLitDonorMaterial(GameObject donor)
	{
		if (!donor)
			return null;
		try
		{
			var donorRenderers = donor.GetComponentsInChildren<Renderer>(true);
			for (var i = 0; i < donorRenderers.Length; i++)
			{
				var material = donorRenderers[i] ? donorRenderers[i].sharedMaterial : null;
				if (material == null || material.shader == null || !material.shader)
					continue;
				if (!material.shader.isSupported)
					continue;
				if (!string.Equals(material.shader.name, "Hex/Lit", StringComparison.Ordinal))
					continue;
				return material;
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import: Hex/Lit donor material scan failed: " + ex.Message);
		}
		return null;
	}

	private static readonly string[] OwnedSkinnedClearedDonorMaps =
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
		"_GlossMap"
	};

	private static readonly Dictionary<string, Texture2D> OwnedSkinnedSidecarTextures =
		new(StringComparer.OrdinalIgnoreCase);
	// (bundle, prefab folder, material stem, file) -> resolved texture, or null for a settled miss.
	// Every owned skinned instance used to repeat the same bundle LoadAsset probes (hits and misses);
	// bundles in this lane are never unloaded and sidecars are static plugin files, so a lookup is
	// settled once per session. A destroyed cached texture is re-resolved.
	private static readonly Dictionary<string, Texture2D> OwnedSkinnedBundleTextureCache =
		new(StringComparer.Ordinal);
	internal const string OwnedSkinnedPbrSidecarFolder = "homm3_skinned_pbr";
	private const float OwnedSkinnedHexLitSmoothness = 0.35f;

	/// <summary>
	/// Fail-closed diag: the rebound clone's base map must be the unit's own albedo (by name, the
	/// bundle texture's asset name), never a texture the donor sheet brought along.
	/// </summary>
	private static void VerifyOwnedSkinnedAlbedoBound(Material material, Texture2D albedo, Entry entry, string lane, ManualLogSource log)
	{
		if (!material || !material.HasProperty("_MainTex"))
			return;
		var bound = material.GetTexture("_MainTex");
		if (!albedo)
		{
			if (bound)
				log?.LogError("Homm3Import: owned skinned albedo check failed lane=" + lane + " entry='" + entry?.BattlePrefabAssetPath
				              + "': no unit albedo but _MainTex='" + bound.name + "' (donor sheet kept).");
			return;
		}
		if (!bound || bound.name != albedo.name)
			log?.LogError("Homm3Import: owned skinned albedo check failed lane=" + lane + " entry='" + entry?.BattlePrefabAssetPath
			              + "': _MainTex='" + (bound ? bound.name : "(null)") + "' expected '" + albedo.name + "'.");
	}

	private static void ApplyOwnedSkinnedHexLitPbr(
		Material material,
		Texture2D albedo,
		Texture2D normal,
		Texture2D metallicGloss,
		ManualLogSource log)
	{
		if (!material)
			throw new InvalidOperationException("owned skinned Hex/Lit rebind produced a null material");
		for (var i = 0; i < OwnedSkinnedClearedDonorMaps.Length; i++)
		{
			var propertyName = OwnedSkinnedClearedDonorMaps[i];
			if (material.HasProperty(propertyName))
				material.SetTexture(propertyName, null);
		}

		// The clone starts from a donor unit's sheet; its albedo belongs to a different UV layout.
		// Without the unit's own texture the slot is cleared (flat white, visibly wrong) rather than
		// left showing the donor's sheet scrambled over this mesh.
		if (material.HasProperty("_MainTex"))
			material.SetTexture("_MainTex", albedo ? albedo : null);
		if (material.HasProperty("_BaseMap"))
			material.SetTexture("_BaseMap", albedo ? albedo : null);
		if (!albedo)
			log?.LogError("Homm3Import: owned skinned Hex/Lit rebind has no unit albedo for '" + material.name
			              + "'; donor base map cleared instead of shown over this mesh's UVs.");

		var hasNormalSlot = material.HasProperty("_BumpMap") || material.HasProperty("_NormalMap");
		if (!hasNormalSlot && !material.HasProperty("_MetallicGlossMap"))
		{
			// Installed Hex/Lit: base colour only reaches the screen; the look pipeline bakes normal
			// and metal detail into it (docs/homm3_prebaked_lighting.md).
			if (!_ownedSkinnedHexLitNoPbrSlotsLogged)
			{
				_ownedSkinnedHexLitNoPbrSlotsLogged = true;
				log?.LogInfo("Homm3Import: owned skinned Hex/Lit bound base colour only; this Hex/Lit declares no normal/metallic slots.");
			}
			return;
		}

		if (normal == null || metallicGloss == null)
			throw new InvalidOperationException(
				"owned skinned Hex/Lit metal bind refused: missing crusader_owned_skinned_normal.png or crusader_owned_skinned_metallicgloss.png");

		if (material.HasProperty("_BumpMap"))
			material.SetTexture("_BumpMap", normal);
		else if (material.HasProperty("_NormalMap"))
			material.SetTexture("_NormalMap", normal);
		else
			throw new InvalidOperationException("Hex/Lit has no _BumpMap/_NormalMap slot for the crusader normal atlas");
		material.EnableKeyword("_NORMALMAP");

		if (!material.HasProperty("_MetallicGlossMap"))
			throw new InvalidOperationException("Hex/Lit has no _MetallicGlossMap slot for the crusader metal atlas");
		material.SetTexture("_MetallicGlossMap", metallicGloss);
		material.EnableKeyword("_METALLICGLOSSMAP");
		if (material.HasProperty("_Metallic"))
			material.SetFloat("_Metallic", 1f);
		if (material.HasProperty("_Smoothness"))
			material.SetFloat("_Smoothness", OwnedSkinnedHexLitSmoothness);
		else if (material.HasProperty("_Glossiness"))
			material.SetFloat("_Glossiness", OwnedSkinnedHexLitSmoothness);
		log?.LogInfo(
			"Homm3Import: owned skinned Hex/Lit PBR bound albedo="
			+ (albedo ? albedo.name : "(null)")
			+ " normal=" + normal.name
			+ " metallicGloss=" + metallicGloss.name
			+ " smoothness=" + OwnedSkinnedHexLitSmoothness.ToString("0.##") + ".");
	}

	/// <summary>
	/// Loads the unit's albedo texture from its own bundle. The bundle material's runtime sheet
	/// cannot be trusted (FallbackError shader drops its texture ref), but the texture rides in the
	/// bundle as a dependency of the material and is addressable by its lab project path, the same
	/// convention that loads the battle prefab.
	/// </summary>
	private static Texture2D TryLoadOwnedSkinnedBundleTexture(Entry entry, Material sourceMaterial, ManualLogSource log)
	{
		return TryLoadOwnedSkinnedBundleNamedTexture(entry, sourceMaterial, log, "basecolor.jpg")
		       ?? TryLoadOwnedSkinnedBundleNamedTexture(entry, sourceMaterial, log, "basecolor.png");
	}

	private static Texture2D TryLoadOwnedSkinnedBundleNamedTexture(
		Entry entry,
		Material sourceMaterial,
		ManualLogSource log,
		string fileName)
	{
		if (entry == null || string.IsNullOrEmpty(entry.BundleName) || string.IsNullOrEmpty(entry.BattlePrefabAssetPath))
			return null;
		if (string.IsNullOrEmpty(fileName))
			throw new ArgumentException("owned skinned bundle texture file name is empty", nameof(fileName));
		var bundle = GetBundle(entry.BundleName, log);
		if (bundle == null)
			return null;
		var root = entry.BattlePrefabAssetPath;
		var slash = root.LastIndexOf('/');
		if (slash <= 0)
			return null;
		root = root.Substring(0, slash);
		var stem = sourceMaterial != null && !string.IsNullOrEmpty(sourceMaterial.name) ? sourceMaterial.name : "unit";
		if (stem.EndsWith("_runtime_native", StringComparison.Ordinal))
			stem = stem.Substring(0, stem.Length - "_runtime_native".Length);
		if (stem.EndsWith("_runtime", StringComparison.Ordinal))
			stem = stem.Substring(0, stem.Length - "_runtime".Length);
		var cacheKey = entry.BundleName + "|" + root + "|" + stem + "|" + fileName;
		if (OwnedSkinnedBundleTextureCache.TryGetValue(cacheKey, out var cachedTexture))
		{
			// A settled miss is stored as a managed null. Unity's overloaded == is also true for a
			// texture the engine has since freed (scene-change UnloadUnusedAssets drops an unreferenced
			// bundle texture), so testing that way turned a freed hit into a "miss" and the unit
			// rendered the donor's _MainTex through its own UVs (2026-09-26 castle swordsman
			// scramble: battle diag tex='troglodyte_v3_diffuse'). A freed hit is re-resolved;
			// bundle LoadAsset reloads it.
			if (ReferenceEquals(cachedTexture, null))
				return null;
			if (cachedTexture)
				return cachedTexture;
			OwnedSkinnedBundleTextureCache.Remove(cacheKey);
			log?.LogInfo("Homm3Import: owned skinned cached texture was unloaded; re-resolving '" + cacheKey + "'.");
		}
		var resolved = ResolveOwnedSkinnedBundleNamedTexture(entry, bundle, root, stem, fileName, log);
		OwnedSkinnedBundleTextureCache[cacheKey] = resolved;
		return resolved;
	}

	private static Texture2D ResolveOwnedSkinnedBundleNamedTexture(
		Entry entry,
		AssetBundle bundle,
		string root,
		string stem,
		string fileName,
		ManualLogSource log)
	{
		var candidates = new[]
		{
			root + "/" + stem + "_" + fileName,
			root.ToLowerInvariant() + "/" + stem.ToLowerInvariant() + "_" + fileName,
		};
		foreach (var candidate in candidates)
		{
			try
			{
				var texture = bundle.LoadAsset<Texture2D>(candidate);
				if (texture && texture)
				{
					log?.LogInfo("Homm3Import: owned skinned lane loaded bundle texture '" + candidate + "'.");
					return texture;
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: owned skinned bundle texture load failed for '" + candidate + "': " + ex.Message);
			}
		}

		var sidecar = TryLoadOwnedSkinnedSidecarTexture(entry, stem, fileName, log);
		if (sidecar)
			return sidecar;

		log?.LogWarning(
			"Homm3Import: owned skinned lane could not load bundle texture for '"
			+ stem
			+ "' (tried: "
			+ string.Join(", ", candidates)
			+ ").");
		return null;
	}

	private static Texture2D TryLoadOwnedSkinnedSidecarTexture(
		Entry entry,
		string stem,
		string fileName,
		ManualLogSource log)
	{
		var labSid = TryLabSidFromOwnedSkinnedPrefab(entry != null ? entry.BattlePrefabAssetPath : null);
		if (string.IsNullOrEmpty(labSid) || string.IsNullOrEmpty(stem) || string.IsNullOrEmpty(fileName))
			return null;
		var relative = OwnedSkinnedPbrSidecarFolder + "/" + labSid + "/" + stem + "_" + fileName;
		if (OwnedSkinnedSidecarTextures.TryGetValue(relative, out var cached) && cached)
			return cached;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(relative);
		if (string.IsNullOrEmpty(path) || !File.Exists(path))
			return null;
		try
		{
			var bytes = File.ReadAllBytes(path);
			if (bytes == null || bytes.Length == 0)
				return null;
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			var texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: true, linear: true)
			{
				name = stem + "_" + fileName,
				wrapMode = TextureWrapMode.Repeat,
				filterMode = FilterMode.Bilinear
			};
			if (!ImageConversion.LoadImage(texture, il2cppBytes, markNonReadable: true) || !texture)
			{
				UnityEngine.Object.Destroy(texture);
				log?.LogError("Homm3Import: owned skinned sidecar PNG failed to decode '" + relative + "'.");
				return null;
			}
			OwnedSkinnedSidecarTextures[relative] = texture;
			log?.LogInfo("Homm3Import: owned skinned lane loaded sidecar texture '" + relative + "'.");
			return texture;
		}
		catch (Exception ex)
		{
			log?.LogError(
				"Homm3Import: owned skinned sidecar load failed for '" + relative + "': " + ex.Message);
			return null;
		}
	}

	private static string TryLabSidFromOwnedSkinnedPrefab(string battlePrefabAssetPath)
	{
		if (string.IsNullOrWhiteSpace(battlePrefabAssetPath))
			return null;
		var normalized = battlePrefabAssetPath.Replace('\\', '/');
		const string marker = "/homm3_lab/";
		var index = normalized.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
		if (index < 0)
			return null;
		var rest = normalized.Substring(index + marker.Length);
		var slash = rest.IndexOf('/');
		var leaf = slash >= 0 ? rest.Substring(0, slash) : rest;
		return string.IsNullOrWhiteSpace(leaf) ? null : leaf.Trim();
	}

	private static int _skinnedLaneDiagRemaining = 8;

	private static void LogSkinnedBattleLaneState(GameObject instance, ManualLogSource log)
	{
		if (instance == null || !instance || !Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag"))
			return;
		if (_skinnedLaneDiagRemaining <= 0)
			return;
		_skinnedLaneDiagRemaining--;
		log?.LogInfo("Homm3Import skinned-lane diag: " + DescribeSkinnedBattleLaneState(instance));
	}

	/// <summary>Dumps the skinned-lane renderer/material/transform state for combat invisibility debugging.</summary>
	internal static string DescribeSkinnedBattleLaneState(GameObject instance)
	{
		if (!instance)
			return "(null instance)";
		try
		{
			var sb = new StringBuilder(512);
			sb.Append("instance='").Append(instance.name ?? "?").Append("'");
			try
			{
				sb.Append(" active=").Append(instance.activeInHierarchy);
			}
			catch
			{
				sb.Append(" active=?");
			}

			sb.Append(" layer=").Append(instance.layer);
			try
			{
				sb.Append(" pos=").Append(instance.transform.position.ToString("0.###"))
					.Append(" rot=").Append(instance.transform.eulerAngles.ToString("0.#"))
					.Append(" lossyScale=").Append(instance.transform.lossyScale.ToString("0.####"));
			}
			catch
			{
				sb.Append(" xform=?");
			}

			var parent = instance.transform.parent;
			sb.Append(" parent='").Append(parent ? parent.name ?? "?" : "?").Append("'");
			var skins = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
			for (var k = 0; k < skins.Length; k++)
			{
				var skin = skins[k];
				sb.Append(" | skin").Append(k);
				if (!skin)
				{
					sb.Append("=(null)");
					continue;
				}

				var mesh = skin.sharedMesh;
				var mat = skin.sharedMaterial;
				sb.Append(" en=").Append(skin.enabled)
					.Append(" act=").Append(skin.gameObject.activeInHierarchy)
					.Append(" vis=").Append(SafeIsVisible(skin))
					.Append(" lyr=").Append(skin.gameObject.layer)
					.Append(" mesh='").Append(mesh ? mesh.name ?? "?" : "?").Append("'")
					.Append(" bones=").Append(skin.bones != null ? skin.bones.Length : 0);
				try
				{
					sb.Append(" bCenter=").Append(skin.bounds.center.ToString("0.###"))
						.Append(" bSize=").Append(skin.bounds.size.ToString("0.###"));
				}
				catch
				{
					sb.Append(" bnds=?");
				}

				sb.Append(" mat='").Append(mat ? mat.name ?? "?" : "?").Append("'")
					.Append(" shader='").Append(mat && mat.shader ? mat.shader.name ?? "?" : "?").Append("'")
					.Append(" rq=").Append(mat ? mat.renderQueue.ToString() : "?");
				if (mat)
				{
					var tex = SafeGetTexture(mat, "_MainTex");
					sb.Append(" tex='").Append(tex ? tex.name ?? "?" : "(null)").Append("'")
						.Append(" texType=").Append(tex ? tex.GetType().Name : "?");
					var bump = SafeGetTexture(mat, "_BumpMap") ?? SafeGetTexture(mat, "_NormalMap");
					var metal = SafeGetTexture(mat, "_MetallicGlossMap");
					sb.Append(" bump='").Append(bump ? bump.name ?? "?" : "(null)").Append("'")
						.Append(" metal='").Append(metal ? metal.name ?? "?" : "(null)").Append("'");
					try
					{
						sb.Append(" colorA=").Append(mat.color.a.ToString("0.###"));
					}
					catch
					{
						sb.Append(" colorA=?");
					}
				}
			}

			var animator = instance.GetComponentInChildren<Animator>(true);
			if (animator)
			{
				var ctrl = animator.runtimeAnimatorController;
				sb.Append(" | anim en=").Append(animator.enabled)
					.Append(" ctrl='").Append(ctrl ? ctrl.name ?? "?" : "(null)").Append("'");
				try
				{
					sb.Append(" init=").Append(animator.isInitialized);
				}
				catch
				{
					sb.Append(" init=?");
				}
			}

			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "describe failed: " + ex.Message;
		}
	}

	private static Texture SafeGetTexture(Material material, string propertyName)
	{
		if (material == null)
			return null;
		try
		{
			// GetTexture on an undeclared property logs a stack-traced warning (978 in one map
			// load's Player.log: the installed Hex/Lit has no _BumpMap/_NormalMap/_MetallicGlossMap).
			if (!material.HasProperty(propertyName))
				return null;
			return material.GetTexture(propertyName);
		}
		catch
		{
			return null;
		}
	}

	/// <summary>
	/// The owned body's horizontal forward in the battle root's local space: the body frame
	/// (<see cref="OwnedSkinnedBodyRotation"/> of the Orientation node, which carries the side heading
	/// left 150 / right -30) brought into the root. The lane marker is a constant +90 on both sides and
	/// is not the body forward: on the right side the body faces the opposite way, so turning the root by
	/// the marker left right-side attackers facing away from their target (skinnedDelta -180).
	/// </summary>
	private static bool TryGetOwnedSkinnedBodyForwardInRoot(GameObject battleRoot, out Vector3 forwardLocal)
	{
		forwardLocal = Vector3.zero;
		var node = FindOwnedSkinnedSideFacingNode(battleRoot);
		if (!node)
			return false;
		var bodyInRoot = Quaternion.Inverse(battleRoot.transform.rotation) * OwnedSkinnedBodyRotation(node);
		forwardLocal = bodyInRoot * Vector3.forward;
		forwardLocal.y = 0f;
		if (forwardLocal.sqrMagnitude <= 1e-6f)
			return false;
		forwardLocal.Normalize();
		return true;
	}

	internal static bool TryApplySkinnedBattleTargetFacing(GameObject battleRoot, Vector3 targetPosition)
	{
		if (!IsHomm3SkinnedBattleInstance(battleRoot))
			return false;
		var direction = targetPosition - battleRoot.transform.position;
		direction.y = 0f;
		if (direction.sqrMagnitude <= 1e-6f)
			return false;
		if (!TryGetOwnedSkinnedBodyForwardInRoot(battleRoot, out var bodyForward))
		{
			Plugin.LogSource?.LogError(
				"Homm3Import skinned target facing: no Orientation/MocapDeliveryRoot body frame on '"
				+ (battleRoot.name ?? "?")
				+ "'; attack facing not applied.");
			return false;
		}
		var forwardCorrection = Quaternion.FromToRotation(bodyForward, Vector3.forward);
		battleRoot.transform.rotation = Quaternion.LookRotation(direction.normalized, Vector3.up) * forwardCorrection;
		return true;
	}

	/// <summary>
	/// Diagnostic: signed yaw (degrees) between the owned body's current forward (the body frame, same
	/// as <see cref="TryApplySkinnedBattleTargetFacing"/>) and the horizontal direction to
	/// <paramref name="targetPosition"/>. ~0 means the mesh already faces the target; ±180 means
	/// it faces away. Logged per attack to verify the vanilla facing convention holds.
	/// </summary>
	internal static float MeasureSkinnedTargetFacingDelta(GameObject battleRoot, Vector3 targetPosition)
	{
		if (!IsHomm3SkinnedBattleInstance(battleRoot) || !battleRoot.transform)
			return float.NaN;
		var direction = targetPosition - battleRoot.transform.position;
		direction.y = 0f;
		if (direction.sqrMagnitude <= 1e-6f)
			return float.NaN;
		if (!TryGetOwnedSkinnedBodyForwardInRoot(battleRoot, out var meshForwardLocal))
			return float.NaN;
		var currentForward = battleRoot.transform.rotation * meshForwardLocal;
		currentForward.y = 0f;
		if (currentForward.sqrMagnitude <= 1e-6f)
			return float.NaN;
		return Vector3.SignedAngle(currentForward.normalized, direction.normalized, Vector3.up);
	}

	internal static void PostfixResGetProjectileGameObject(string resPath, ref GameObject result)
	{
		if (string.IsNullOrWhiteSpace(resPath))
			return;
		var path = NormResourcePath(resPath);
		if (!ProjectileBundleByResourcePath.TryGetValue(path, out var bundleName))
			return;
		if (!ProjectileAssetByResourcePath.TryGetValue(path, out var assetPath))
			return;

		var key = bundleName + "::" + assetPath;
		var visual = LoadProjectileVisualTemplate(key, bundleName, assetPath);
		if (!visual)
			return;

		if (result && result)
		{
			AttachProjectileVisualToShell(result, visual, path);
			Plugin.LogSource?.LogInfo(
				"Homm3Import: attached projectile visual '"
				+ path
				+ "' to existing shell '"
				+ (result.name ?? "?")
				+ "'.");
			return;
		}

		result = visual;
		Plugin.LogSource?.LogInfo("Homm3Import: supplied bare projectile visual '" + path + "' from " + bundleName + " (no shell result).");
	}

	static GameObject LoadProjectileVisualTemplate(string key, string bundleName, string assetPath)
	{
		if (ProjectileTemplates.TryGetValue(key, out var cached) && cached)
			return cached;
		var bundle = GetBundle(bundleName, Plugin.LogSource);
		if (bundle == null)
			return null;
		try
		{
			var go = bundle.LoadAsset<GameObject>(assetPath);
			if (go && go)
			{
				ProjectileTemplates[key] = go;
				return go;
			}

			Plugin.LogSource?.LogWarning("Homm3Import: projectile asset missing in bundle " + bundleName + ": " + assetPath);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import: projectile LoadAsset failed for '" + assetPath + "': " + ex.Message);
		}

		return null;
	}

	static void AttachProjectileVisualToShell(GameObject shell, GameObject visualTemplate, string resourcePath)
	{
		if (!shell || !visualTemplate)
			return;
		var shellId = shell.GetInstanceID();
		if (!ProjectileVisualsAttachedByShellId.TryGetValue(shellId, out var attached))
		{
			attached = new HashSet<string>(StringComparer.Ordinal);
			ProjectileVisualsAttachedByShellId[shellId] = attached;
		}

		if (attached.Contains(resourcePath))
			return;
		attached.Add(resourcePath);

		var visual = UnityEngine.Object.Instantiate(visualTemplate);
		visual.name = "OfflineUnlock_" + resourcePath.Replace('/', '_');
		visual.transform.SetParent(shell.transform, false);
		visual.transform.localPosition = Vector3.zero;
		visual.transform.localRotation = Quaternion.identity;
		visual.transform.localScale = CompensateProjectileVisualScale(shell.transform, Vector3.one);
		ApplyProjectileVisualPresentation(shell, visual, resourcePath);
		Homm3BattleBillboardCameraFacing.TryAttach(visual, Plugin.LogSource);
	}

	static Vector3 CompensateProjectileVisualScale(Transform shell, Vector3 desiredWorldScale)
	{
		try
		{
			var parentScale = shell.lossyScale;
			return new Vector3(
				Mathf.Abs(parentScale.x) > 0.0001f ? desiredWorldScale.x / parentScale.x : desiredWorldScale.x,
				Mathf.Abs(parentScale.y) > 0.0001f ? desiredWorldScale.y / parentScale.y : desiredWorldScale.y,
				Mathf.Abs(parentScale.z) > 0.0001f ? desiredWorldScale.z / parentScale.z : desiredWorldScale.z);
		}
		catch
		{
			return desiredWorldScale;
		}
	}

	static void ApplyProjectileVisualPresentation(GameObject shell, GameObject visual, string resourcePath)
	{
		if (!shell || !visual)
			return;
		try
		{
			SyncLayerRecursive(visual.transform, shell.layer);
			var renderers = visual.GetComponentsInChildren<Renderer>(true);
			foreach (var r in renderers)
			{
				if (!r)
					continue;
				r.enabled = true;
				r.shadowCastingMode = ShadowCastingMode.Off;
				r.receiveShadows = false;
				try
				{
					r.sortingOrder = 500;
				}
				catch { }

				var mats = r.materials;
				if (mats == null)
					continue;
				foreach (var mat in mats)
				{
					if (!mat)
						continue;
					mat.renderQueue = 3000;
					if (mat.HasProperty("_Color"))
					{
						var color = mat.color;
						if (color.a < 0.99f)
						{
							color.a = 1f;
							mat.color = color;
						}
					}
				}
			}

			if (_projectileVisualPresentationDiagRemaining > 0)
			{
				_projectileVisualPresentationDiagRemaining--;
				Plugin.LogSource?.LogInfo(
					"Homm3Import: projectile visual presentation '"
					+ resourcePath
					+ "' shell='"
					+ (shell.name ?? "?")
					+ "' shellLayer="
					+ shell.layer
					+ " shellScale="
					+ shell.transform.lossyScale.ToString("0.####")
					+ " visualLocalScale="
					+ visual.transform.localScale.ToString("0.####")
					+ " renderers="
					+ DescribeProjectileRenderers(visual));
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import: projectile visual presentation failed: " + ex.Message);
		}
	}

	static void SyncLayerRecursive(Transform root, int layer)
	{
		if (root == null)
			return;
		root.gameObject.layer = layer;
		for (var i = 0; i < root.childCount; i++)
			SyncLayerRecursive(root.GetChild(i), layer);
	}

	static string DescribeProjectileRenderers(GameObject visual)
	{
		try
		{
			var wa = visual.GetComponentsInChildren<Renderer>(true);
			if (wa == null || wa.Length == 0)
				return "none";
			var parts = new List<string>();
			foreach (var r in wa)
			{
				if (!r)
					continue;
				var b = r.bounds;
				var mat = r.sharedMaterial;
				parts.Add(
					r.GetType().Name
					+ " go='"
					+ (r.gameObject.name ?? "?")
					+ "' en="
					+ r.enabled
					+ " act="
					+ r.gameObject.activeInHierarchy
					+ " lyr="
					+ r.gameObject.layer
					+ " vis="
					+ SafeIsVisible(r)
					+ " bCenter="
					+ b.center.ToString("0.###")
					+ " bSize="
					+ b.size.ToString("0.###")
					+ " mat="
					+ (mat ? mat.name : "?")
					+ " zj="
					+ (mat && mat.shader ? mat.shader.name : "?")
					+ " rq="
					+ (mat ? mat.renderQueue.ToString() : "?"));
			}
			return string.Join(" | ", parts);
		}
		catch (Exception ex)
		{
			return "describe failed: " + ex.Message;
		}
	}

	static bool SafeIsVisible(Renderer r)
	{
		try
		{
			return r.isVisible;
		}
		catch
		{
			return false;
		}
	}

	internal static bool TryAttachProjectileVisualToShell(GameObject shell, string resourcePath, bool hideExistingRenderers)
	{
		if (!shell || string.IsNullOrWhiteSpace(resourcePath))
			return false;
		var path = NormResourcePath(resourcePath);
		if (!ProjectileBundleByResourcePath.TryGetValue(path, out var bundleName))
			return false;
		if (!ProjectileAssetByResourcePath.TryGetValue(path, out var assetPath))
			return false;
		var visual = LoadProjectileVisualTemplate(bundleName + "::" + assetPath, bundleName, assetPath);
		if (!visual)
			return false;
		if (hideExistingRenderers)
		{
			try
			{
				foreach (var r in shell.GetComponentsInChildren<Renderer>(true))
				{
					if (r && r)
						r.enabled = false;
				}
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning("Homm3Import: failed hiding donor projectile renderers: " + ex.Message);
			}
		}
		AttachProjectileVisualToShell(shell, visual, path);
		Plugin.LogSource?.LogInfo("Homm3Import: attached queued projectile visual '" + path + "' to shell '" + (shell.name ?? "?") + "'.");
		return true;
	}

	static string NormResourcePath(string path)
	{
		var p = path.Trim().Replace('\\', '/');
		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		return p;
	}

	internal static bool TryGetBattleTemplate(Entry e, ManualLogSource log, out GameObject template)
	{
		template = null;
		var b = GetBundle(e.BundleName, log);
		if (b == null)
			return false;
		var key = e.BundleName + "::" + e.BattlePrefabAssetPath;
		if (BattleTemplates.TryGetValue(key, out var c) && c)
		{
			template = c;
			return true;
		}

		try
		{
			var go = LoadBundleGameObject(b, e.BattlePrefabAssetPath, log, "battle");
			if (go && go)
			{
				BattleTemplates[key] = go;
				template = go;
				return true;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: LoadAsset battle failed: " + ex.Message);
		}

		return false;
	}

	static GameObject LoadBundleGameObject(AssetBundle bundle, string assetPath, ManualLogSource log, string kind)
	{
		if (!bundle || string.IsNullOrEmpty(assetPath))
			return null;
		try
		{
			var go = bundle.LoadAsset<GameObject>(assetPath);
			if (go && go)
				return go;
			var normalized = assetPath.Replace('\\', '/');
			var lower = normalized.ToLowerInvariant();
			if (!string.Equals(normalized, lower, StringComparison.Ordinal))
			{
				go = bundle.LoadAsset<GameObject>(lower);
				if (go && go)
					return go;
			}

			var names = bundle.GetAllAssetNames();
			if (names != null)
			{
				for (var i = 0; i < names.Length; i++)
				{
					var name = names[i];
					if (string.IsNullOrEmpty(name))
						continue;
					if (!string.Equals(name.Replace('\\', '/'), lower, StringComparison.OrdinalIgnoreCase))
						continue;
					go = bundle.LoadAsset<GameObject>(name);
					if (go && go)
						return go;
				}
			}

			LogBundlePrefabMiss(bundle, assetPath, kind, names, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: LoadAsset " + kind + " failed for '" + assetPath + "': " + ex.Message);
		}

		return null;
	}

	static void LogBundlePrefabMiss(AssetBundle bundle, string requested, string kind, string[] names, ManualLogSource log)
	{
		if (log == null)
			return;
		var prefabs = new List<string>();
		if (names != null)
		{
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrEmpty(name))
					continue;
				if (name.IndexOf(".prefab", StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				if (name.IndexOf("/sounds/", StringComparison.OrdinalIgnoreCase) >= 0)
					continue;
				prefabs.Add(name);
				if (prefabs.Count >= 12)
					break;
			}
		}

		log.LogError(
			"Homm3Import: bundle '"
			+ (bundle ? bundle.name : "?")
			+ "' has no "
			+ kind
			+ " GameObject '"
			+ requested
			+ "'; visual prefabs=["
			+ (prefabs.Count == 0 ? "(none)" : string.Join(", ", prefabs))
			+ "].");
	}

	internal static void ApplyRuntimeBattleSpriteScale(GameObject instance)
	{
		if (!instance)
			return;
		if (IsHomm3SkinnedBattleInstance(instance))
			return;
		var quad = instance.transform.Find("billboard/quad");
		if (!quad)
			quad = instance.GetComponentInChildren<MeshRenderer>(true)?.transform;
		if (!quad)
			return;

		var scale = quad.localScale;
		scale.x *= BattleSpriteRuntimeScale;
		scale.y *= BattleSpriteRuntimeScale;
		quad.localScale = scale;

		var position = quad.localPosition;
		position.x *= BattleSpriteRuntimeScale;
		position.y *= BattleSpriteRuntimeScale;
		quad.localPosition = position;
	}

	internal static bool TryGetMapTemplate(Entry e, ManualLogSource log, out GameObject template)
	{
		template = null;
		var b = GetBundle(e.BundleName, log);
		if (b == null)
			return false;
		var key = e.BundleName + "::" + e.MapPrefabAssetPath;
		if (MapTemplates.TryGetValue(key, out var c) && c)
		{
			MapTemplateEntriesByInstanceId[c.GetInstanceID()] = e;
			template = c;
			return true;
		}

		try
		{
			var go = LoadBundleGameObject(b, e.MapPrefabAssetPath, log, "map");
			if (go && go)
			{
				MapTemplates[key] = go;
				MapTemplateEntriesByInstanceId[go.GetInstanceID()] = e;
				template = go;
				return true;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: LoadAsset map failed: " + ex.Message);
		}

		return false;
	}

	static List<Material> TryGetScopedMapFrameMaterials(Entry e, ManualLogSource log)
	{
		if (e == null)
			return null;
		var key = e.BundleName + "::" + e.MapPrefabAssetPath;
		if (MapFrameMaterialsByTemplateKey.TryGetValue(key, out var cached))
		{
			if (HasUsableCachedMaterials(cached))
				return cached;
			MapFrameMaterialsByTemplateKey.Remove(key);
			LogUnitMapFrameCacheInvalidated(log, "material", key);
		}

		var result = new List<Material>();
		var b = GetBundle(e.BundleName, log);
		if (b != null)
		{
			void Add(Material m)
			{
				if (!IsHomm3MapFrameMaterial(m))
					return;
				for (var i = 0; i < result.Count; i++)
				{
					if (result[i] && result[i].GetInstanceID() == m.GetInstanceID())
						return;
				}

				result.Add(m);
			}

			try
			{
				var map = b.LoadAsset<GameObject>(e.MapPrefabAssetPath);
				if (map)
				{
					foreach (var r in map.GetComponentsInChildren<Renderer>(true))
					{
						if (!r)
							continue;
						var mats = r.sharedMaterials;
						if (mats == null)
							continue;
						for (var i = 0; i < mats.Length; i++)
							Add(mats[i]);
					}
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: scoped map-frame prefab material lookup failed for bundle '" + e.BundleName + "': " + ex.Message);
			}

			try
			{
				var names = b.GetAllAssetNames();
				if (names != null)
				{
					for (var i = 0; i < names.Length; i++)
					{
						var assetName = names[i];
						if (!BundleAssetNameMatchesFramePrefix(assetName, "map_frame_")
						    && !BundleAssetNameMatchesFramePrefix(assetName, "homm3_frame_"))
							continue;
						try
						{
							var material = b.LoadAsset<Material>(assetName);
							Add(material);
						}
						catch
						{
							// Ignore individual load failures; prefab scan may already have the material.
						}
					}
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: scoped map-frame bundle material lookup failed for bundle '" + e.BundleName + "': " + ex.Message);
			}
		}

		MapFrameMaterialsByTemplateKey[key] = result;
		if (result.Count > 0)
			log?.LogInfo("Homm3Import: scoped " + result.Count + " map frame material asset(s) for bundle '" + e.BundleName + "'.");
		return result;
	}

	static bool HasUsableCachedMaterials(List<Material> materials)
	{
		if (materials == null || materials.Count == 0)
			return false;
		for (var i = 0; i < materials.Count; i++)
			if (!materials[i])
				return false;
		return true;
	}

	static bool IsHomm3MapFrameMaterial(Material m)
	{
		return m
		       && !string.IsNullOrEmpty(m.name)
		       && (m.name.StartsWith("map_frame_", StringComparison.Ordinal)
		           || m.name.StartsWith("homm3_frame_", StringComparison.Ordinal));
	}

	internal static AssetBundle TryGetLoadedBundle(string bundleName, ManualLogSource log = null) =>
		GetBundle(bundleName, log);

	static AssetBundle GetBundle(string bundleName, ManualLogSource log)
	{
		if (Bundles.TryGetValue(bundleName, out var existing) && existing)
			return existing;
		var path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", _bundleSubdir, bundleName);
		if (!File.Exists(path))
			path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", bundleName);
		if (!File.Exists(path))
		{
			log?.LogWarning("Homm3Import: bundle file not found: " + bundleName);
			return null;
		}

		try
		{
			var b = AssetBundle.LoadFromFile(path);
			if (b != null)
				Bundles[bundleName] = b;
			return b;
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3Import: LoadFromFile failed: " + ex.Message);
			return null;
		}
	}

	internal static bool TryGetHomm3LabAudioClip(string bundleName, string stem, out AudioClip clip)
	{
		clip = null;
		if (string.IsNullOrEmpty(bundleName) || string.IsNullOrEmpty(stem))
			return false;
		EnsureHomm3LabBundleAudioIndexed(bundleName, Plugin.LogSource);
		return Homm3LabAudioClipsByBundle.TryGetValue(bundleName, out var d)
		       && d != null
		       && d.TryGetValue(stem, out clip)
		       && clip;
	}

	internal static void PrewarmBattleEntryAssets(Entry entry, ManualLogSource log)
	{
		if (entry == null)
			return;
		TryGetBattleTemplate(entry, log, out _);
		var labSid = TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
		if (!string.IsNullOrEmpty(labSid))
			Homm3BattleArrayBillboard.PrewarmManifestForLabSid(labSid, log);
		if (!string.IsNullOrEmpty(entry.BundleName))
			EnsureHomm3LabBundleAudioIndexed(entry.BundleName, log);
	}

	static void EnsureHomm3LabBundleAudioIndexed(string bundleName, ManualLogSource log)
	{
		if (string.IsNullOrEmpty(bundleName))
			return;
		lock (Homm3LabAudioIndexGate)
		{
			if (Homm3LabAudioIndexedBundles.Contains(bundleName))
				return;
			Homm3LabAudioIndexedBundles.Add(bundleName);
			var dict = new Dictionary<string, AudioClip>(StringComparer.OrdinalIgnoreCase);
			var entry = TryEntryByBundleName(bundleName);
			var labSid = TryHomm3LabSidFromPrefabPath(entry?.BattlePrefabAssetPath);
			var stemPrefix = ResolveHomm3LabAudioStemPrefix(entry);
			if (!string.IsNullOrEmpty(labSid)
			    && !string.IsNullOrEmpty(stemPrefix)
			    && Homm3UpscaledBattleSfx.TryFillLabClips(labSid, stemPrefix, dict, log))
			{
				log?.LogInfo(
					"Homm3Import: using UniverSR cache for '" + labSid + "' (" + dict.Count
					+ " stems) instead of bundle AudioClips.");
			}
			else
			{
				var b = GetBundle(bundleName, log);
				if (b != null)
					IndexHomm3LabAudioClipsFromBundle(b, dict, log);
			}

			Homm3LabAudioClipsByBundle[bundleName] = dict;
		}
	}

	static void IndexHomm3LabAudioClipsFromBundle(AssetBundle bundle, Dictionary<string, AudioClip> dest, ManualLogSource log)
	{
		try
		{
			// Do not LoadAllAssets() on battle bundles — it hydrates Texture2DArray and causes a main-thread hitch.
			try
			{
				var names = bundle.GetAllAssetNames();
				if (names != null)
				{
					for (var i = 0; i < names.Length; i++)
					{
						var path = names[i];
						if (string.IsNullOrEmpty(path)
						    || path.IndexOf("HOMM3_", StringComparison.OrdinalIgnoreCase) < 0)
							continue;
						AudioClip clip = null;
						try
						{
							clip = bundle.LoadAsset<AudioClip>(path);
						}
						catch
						{
							continue;
						}

						if (!clip)
							continue;
						dest[clip.name] = clip;
					}
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: targeted HOMM3_* audio load failed: " + ex.Message);
			}

			if (dest.Count == 0)
				HarvestHomm3LabSfxFromSoundPrefabs(bundle, dest, log);

			if (log != null && dest.Count > 0)
				log.LogInfo("Homm3Import: indexed " + dest.Count + " HOMM3_* AudioClip(s) for bundle '" + bundle.name + "'.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: lane B audio clip indexing failed: " + ex.Message);
		}
	}

	static void HarvestHomm3LabSfxFromSoundPrefabs(AssetBundle bundle, Dictionary<string, AudioClip> dest, ManualLogSource log)
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
				if (string.IsNullOrEmpty(nm) || nm.IndexOf("HOMM3_", StringComparison.OrdinalIgnoreCase) < 0)
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
					if (path.IndexOf("homm3_lab", StringComparison.OrdinalIgnoreCase) < 0
					    && path.IndexOf("HOMM3_", StringComparison.OrdinalIgnoreCase) < 0)
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

			if (dest.Count == 0 && log != null && n > 0)
				log.LogWarning(
					"Homm3Import: bundle has asset names but no HOMM3_* clips on sound prefabs (run Homm3BattleSoundPrefabsBuild after stage_homm3_unit_audio).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: sound-prefab clip harvest failed: " + ex.Message);
		}
	}

	internal static void EnsureHomm3LabBattleAudioPlayerTypeRegistered(ManualLogSource log)
	{
		if (Homm3LabBattleAudioPlayerRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3LabBattleAudioPlayer>();
			Homm3LabBattleAudioPlayerRegistered = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3LabBattleAudioPlayer Il2Cpp register failed: " + ex.Message);
		}
	}

	internal static void EnsureHomm3LabClipAudioDriverTypeRegistered(ManualLogSource log)
	{
		if (Homm3LabClipDriverRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3LabClipAudioDriver>();
			Homm3LabClipDriverRegistered = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3LabClipAudioDriver Il2Cpp register failed: " + ex.Message);
		}
	}
}

public sealed class Homm3MapNativeShellTemplateGuard : MonoBehaviour
{
	bool _configured;

	public Homm3MapNativeShellTemplateGuard(IntPtr ptr)
		: base(ptr)
	{
	}

	internal void Configure()
	{
		_configured = true;
	}

	void Start()
	{
		UpdateTemplateState();
	}

	void OnTransformParentChanged()
	{
		UpdateTemplateState();
	}

	void LateUpdate()
	{
		UpdateTemplateState();
	}

	void UpdateTemplateState()
	{
		if (!gameObject)
			return;
		if (!_configured)
			Configure();

		var parented = transform && transform.parent;
		if (parented)
		{
			var skinnedVisual = transform.Find(Homm3ImportVisuals.MapPrefabVisualChildName);
			if (skinnedVisual && Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(skinnedVisual.gameObject))
			{
				Homm3ImportVisuals.RestoreOwnedSkinnedMapFogProbe(gameObject, undoTemplateHide: true);
				UnityEngine.Object.Destroy(this);
				return;
			}
			Homm3ImportVisuals.ApplyNativeShellDrawVisibility(gameObject, gameObject.activeInHierarchy);
			if (gameObject.activeInHierarchy)
				UnityEngine.Object.Destroy(this);
			return;
		}

		Homm3ImportVisuals.SuppressNativeShellTemplateDrawOnly(gameObject);
	}
}
