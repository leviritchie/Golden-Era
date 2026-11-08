using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using BepInEx.Logging;
using Il2CppInterop.Runtime;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.PostProcessing;
using UnityEngine.SceneManagement;
using LightingSettings = Hex.Render.LightingSettings;

namespace OfflineUnlockMod;

/// <summary>
/// Camera-registered 3D town scene (docs/conflux_town3d_pilot.md, "Plugin integration"): per-fraction
/// catalog <c>homm3_town_scene_meshes/scene3d/&lt;fraction&gt;/catalog.json</c> + bundle, built by
/// tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py. Each catalog layer is a prefab whose root is
/// the reference town camera's frame. Legacy v1 catalogs follow the live camera to register with the 2D backdrop;
/// full-3D v2 catalogs seat the root at the native camera's authored rest pose while the camera pans through the
/// world. The frustum ratio preserves default-frame registration for any FOV / aspect. Layers that
/// stay 2D get their camera distance from <c>layerDepths</c> so they sort against the meshes as painted.
/// Key light and fog go through the city's own <c>Hex.Render.LightingSettings</c> post-process volume: the Hex
/// pipeline (bdr::kqq -> bdw::ktg) rewrites the main light's rotation and <c>RenderSettings.fog</c> from that
/// volume on every camera render, so writing the sun transform or RenderSettings directly never holds. The lane
/// overrides <c>lightZenithAngle</c> / <c>lightAzimuthAngle</c> (catalog key, fitted to the HoMM3 painting) and
/// <c>fogEnabled</c> on each such volume's instanced profile, adds a fill directional light, and restores all on clear.
/// Full-3D catalogs (<c>"fullScene3d": true</c>, docs/homm3_conflux_full_3d_town.md) add one environment prefab
/// (terrain, water, sky, scatter) under the same root, hide the HotA backdrop and plate quads, draw no decoration and
/// no 2D layer at all: every reachable layer must have a prefab or the apply throws.
/// Gate: <see cref="LauncherConfig.Homm3TownScene3d"/>. Fail-closed for catalogued fractions.
/// V2 rest-pose seating proof tier: source/static only; not deployed or runtime-proven.
/// Optional v2 <c>referenceCamera.framing</c> (town_full3d_framing.v1, tools/homm3_town_scene_meshes/town_full3d_framing.py):
/// zooms the native MainCamera (fieldOfView narrowed by <c>zoom</c>; the root keeps its native-FOV scale), turns the
/// root by <c>aimRotation</c> about the rest camera, and swaps the controller's SoCityCameraSettings for a clone whose
/// sweep nodes (about the rest camera) and cursor angles are scaled by <c>panScale</c>; all restored on clear or for a
/// fraction without framing. Proof tier: source/static only. Whether the native controller rebuilds its sweep spline
/// from the swapped settings is runtime-unproven (logged as a warning when the clone is assigned).
/// </summary>
internal static class Homm3TownScene3d
{
	internal const string CatalogSchema = "homm3_town_scene3d_catalog.v1";
	internal const string RestPoseCatalogSchema = "homm3_town_scene3d_catalog.v2";
	internal const string RelativeFolder = "homm3_town_scene_meshes/scene3d/";
	internal const string RootName = "OfflineUnlockTownScene3D";
	internal const string FillLightName = "OfflineUnlockTownScene3DFill";
	internal const string EnvironmentInstanceName = "OfflineUnlockTownScene3DEnvironment";
	private const string EnvironmentCacheKey = "\u0000environment";
	private const string SkyPiecePrefix = "Sky_";
	private const string FxPiecePrefix = "Fx_";
	// The full-3D sky dome sits ~97 prefab units from the camera (docs/homm3_conflux_full_3d_town.md, item 7).
	private const float FullSceneMinFarClip = 120f;
	// Drawn before every opaque mesh; Sprites/Default does not write depth, so everything else covers it.
	private const int SkyRenderQueue = 1000;
	// Mesh-lane prefix so the compositor's collider fit uses renderer bounds (not the unit-quad bounds).
	internal const string BodyChildName = Homm3TownSceneMeshBundle.MeshChildPrefix + "Body";
	private const string MeshPiecePrefix = "Mesh_";
	private const string LogPrefix = "HoMM3 town scene 3D: ";


	internal sealed class SceneCatalog
	{
		internal string Fraction;
		internal string BundleFile;
		internal long BundleBytes;
		internal float ReferenceFov;
		internal float ReferenceAspect;
		internal bool RestPoseSeating;
		internal string RestSourceLevelFile;
		internal string RestSourceLevelSha256;
		internal bool RestSourceValidated;
		internal Vector3 RestLocalPosition;
		internal Quaternion RestLocalRotation;
		internal bool HasFraming;
		internal float FramingZoom = 1f;
		internal Quaternion FramingAim = Quaternion.identity;
		internal float FramingPanScale = 1f;
		internal Vector3 KeyLocalDir;
		internal Vector3 FillLocalDir;
		internal Color FillLinear;
		internal bool FogOff;
		internal bool FullScene3d;
		internal string EnvironmentPrefabKey;
		// Opt-in SSR water (catalog waterLook.screenSpaceReflection, town_full3d_ssr_water.v1): the shader reads the camera depth texture.
		internal bool RequiresCameraDepthTexture;
		internal string SsrShader;
		internal readonly HashSet<string> SsrPieces = new(StringComparer.Ordinal);
		// Opt-in continuous sky (catalog skyLook, town_full3d_sky_continuous.v1): the one Sky_ piece keeps its bundle
		// panorama shader (docs/homm3_town_sky_continuous.md); null = the sprite-material sky dome.
		internal string SkyShader;
		internal string SkyPiece;
		// Opt-in cloth wave (catalog clothLook, town_full3d_cloth.v1, docs/homm3_town_cloth_wave.md): each declared
		// Mesh_Cloth_* piece gets the native Hex/Lit FLAG vertex wave with its prefab-frame vectors.
		internal readonly Dictionary<string, ClothWave> ClothByPiece = new(StringComparer.Ordinal);
		internal readonly Dictionary<string, string> PrefabKeyByLayer = new(StringComparer.Ordinal);
		internal readonly Dictionary<string, float> LayerDepths = new(StringComparer.Ordinal);
		internal AssetBundle Bundle;
		internal bool PayloadValidated;
		// Unity bundle/prefab ownership is process-scoped here; faction-scoped loading does not imply eviction.
		internal readonly Dictionary<string, GameObject> Prefabs = new(StringComparer.Ordinal);
	}

	internal sealed class ClothWave
	{
		internal string LayerId;
		internal Vector3 Power;       // prefab frame
		internal Vector3 Direction;   // prefab frame
		internal float Speed;
	}

	private static readonly Dictionary<string, SceneCatalog> Catalogs = new(StringComparer.Ordinal);
	private static readonly HashSet<string> MissingCatalogs = new(StringComparer.Ordinal);
	private sealed class VolumeOverride
	{
		internal PostProcessVolume Volume;
		internal PostProcessProfile InstancedByUs;
		internal LightingSettings Settings;
		internal bool ZenithState;
		internal float Zenith;
		internal bool AzimuthState;
		internal float Azimuth;
		internal bool FogState;
		internal bool Fog;
	}

	private static readonly List<VolumeOverride> VolumeOverrides = new();
	private static Material _cleanDonor;
	/// <summary>Hex/Lit's Lit-pass cull property (installed shader: Enum(UnityEngine.Rendering.CullMode), default 2).</summary>
	private const string HexLitCullModeProperty = "_CullMode";
	/// <summary>Hex/Lit's per-material weight for the ContourLines pass (installed shader default 1).</summary>
	private const string HexLitContourOpacityProperty = "_ContourLinesOpacity";
	private static readonly List<Material> OwnedSkyMaterials = new();
	private static Camera _farClipCamera;
	private static float _farClipOriginal;
	// SSR water: the camera whose depthTextureMode we widened, and its mode before.
	private static Camera _depthTextureCamera;
	private static DepthTextureMode _depthTextureOriginal;
	internal const string SsrSchema = "town_full3d_ssr_water.v1";
	internal const string SkySchema = "town_full3d_sky_continuous.v1";
	internal const string ClothSchema = "town_full3d_cloth.v1";
	private const string ClothPiecePrefix = "Mesh_Cloth_";
	private const string SkyPanoramaShaderSuffix = "/SkyPanorama";
	private const string SkyTimeOffsetProperty = "_TimeOffset";
	// Framing: the camera whose native FOV we narrowed, and the controller whose settings we swapped for a clone.
	private static Camera _framingCamera;
	private static float _framingNativeFov;
	private static Component _panController;
	private static PropertyInfo _panSettingsProperty;
	private static UnityEngine.Object _panOriginalSettings;
	private static UnityEngine.Object _panClone;
	private static bool _panSplineCaveatLogged;
	internal const string FramingSchema = "town_full3d_framing.v1";
	internal static bool IsEnabled()
	{
		var cfg = LauncherConfigReader.TryLoad();
		return cfg != null && cfg.Homm3TownScene3d;
	}

	/// <summary>True when the flag is on and this fraction ships a scene catalog (throws if it is malformed).</summary>
	internal static bool IsActiveFor(string fraction) =>
		IsEnabled() && !string.IsNullOrEmpty(fraction) && TryGetCatalog(fraction, out _);

	/// <summary>True when the fraction's scene catalog is full-3D (no HotA 2D presentation at all).</summary>
	internal static bool IsFullScene3d(string fraction) =>
		IsActiveFor(fraction) && Catalogs[fraction].FullScene3d;

	internal static bool HasLayer(string fraction, string layerId) =>
		IsActiveFor(fraction) && Catalogs[fraction].PrefabKeyByLayer.ContainsKey(layerId ?? string.Empty);

	/// <summary>Camera distance for a HotA layer that stays 2D in a scene-3D fraction (fail-closed if unlisted).</summary>
	internal static float LayerQuadDistanceOrThrow(string fraction, string layerId)
	{
		var catalog = Catalogs[fraction];
		if (!catalog.LayerDepths.TryGetValue(layerId ?? string.Empty, out var depth))
			throw new InvalidOperationException(LogPrefix + "catalog for '" + fraction + "' has no layerDepths entry for '"
				+ layerId + "'; rebuild with build_town_scene3d_bundle.py.");
		return depth;
	}

	internal static bool TryGetCatalog(string fraction, out SceneCatalog catalog)
	{
		if (Catalogs.TryGetValue(fraction, out catalog))
			return true;
		if (MissingCatalogs.Contains(fraction))
			return false;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeFolder + fraction + "/catalog.json");
		if (path == null || !File.Exists(path))
		{
			MissingCatalogs.Add(fraction);
			return false;
		}
		catalog = ParseCatalogOrThrow(fraction, path);
		Catalogs[fraction] = catalog;
		return true;
	}

	private static string ResolvePluginFolder(string relativeFolder)
	{
		var root = BepInEx.Paths.PluginPath;
		var nested = Path.GetFullPath(Path.Combine(root, "OfflineUnlockMod", relativeFolder));
		if (Directory.Exists(nested))
			return nested;
		var flat = Path.GetFullPath(Path.Combine(root, relativeFolder));
		return Directory.Exists(flat) ? flat : null;
	}

	/// <summary>
	/// Main-menu gate: parse every catalog and verify every bundle file and recorded byte length, without loading
	/// Unity assets. Runtime load timing and native-memory impact remain unverified.
	/// </summary>
	internal static void ValidateCatalogPayloadsOrFail(ManualLogSource log)
	{
		// ResolvePluginAssetPath only answers files (File.Exists), so the folder is resolved here against the
		// same two roots; 2026-09-26 the file-only lookup made this gate throw on every enabled launch.
		var dir = ResolvePluginFolder(RelativeFolder.TrimEnd('/'));
		if (dir == null)
			throw new DirectoryNotFoundException("homm3TownScene3d is enabled but " + RelativeFolder
				+ " is missing; run tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py and redeploy.");
		var count = 0;
		foreach (var sub in Directory.GetDirectories(dir))
		{
			var fraction = Path.GetFileName(sub);
			if (!TryGetCatalog(fraction, out var catalog))
				throw new FileNotFoundException("homm3TownScene3d: scene folder without catalog.json", sub);
			ResolveBundlePathOrThrow(catalog);
			count++;
		}
		if (count == 0)
			throw new InvalidOperationException("homm3TownScene3d is enabled but no scene catalog is staged.");
		log?.LogInfo(LogPrefix + "validated metadata and bundle files for " + count
			+ " scene catalog(s); prefab loading is deferred until a selected faction's town presentation is applied.");
	}

	/// <summary>Explicit all-faction runtime diagnostic; never call from the main-menu path.</summary>
	internal static void ValidateAllPayloadsOrFail(ManualLogSource log)
	{
		var dir = ResolvePluginFolder(RelativeFolder.TrimEnd('/'));
		if (dir == null)
			throw new DirectoryNotFoundException("homm3TownScene3d is enabled but " + RelativeFolder
				+ " is missing; run tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py and redeploy.");
		var count = 0;
		foreach (var sub in Directory.GetDirectories(dir))
		{
			var fraction = Path.GetFileName(sub);
			if (!TryGetCatalog(fraction, out var catalog))
				throw new FileNotFoundException("homm3TownScene3d: scene folder without catalog.json", sub);
			ResolveBundlePathOrThrow(catalog);
			LoadCatalogPrefabsOrThrow(catalog);
			catalog.PayloadValidated = true;
			count++;
		}
		if (count == 0)
			throw new InvalidOperationException("homm3TownScene3d is enabled but no scene catalog is staged.");
		log?.LogInfo(LogPrefix + "deep-validated all prefabs for " + count + " scene catalog(s).");
	}

	/// <summary>
	/// Load and cache only this fraction's declared prefabs before the caller mutates town presentation.
	/// First-use timing and native-memory retention are runtime-unverified; unvisited factions remain unloaded.
	/// </summary>
	internal static void ValidateFactionPayloadOrFail(string fraction)
	{
		if (!TryGetCatalog(fraction, out var catalog))
		{
			var missing = new FileNotFoundException(LogPrefix + "selected city fraction '" + fraction
				+ "' has no scene catalog; no 2D fallback is available.", fraction);
			Plugin.LogSource?.LogFatal(LogPrefix + "first-use payload load failed for '" + fraction
				+ "' before presentation changes: " + missing);
			throw missing;
		}
		if (catalog.PayloadValidated)
			return;

		var timer = Stopwatch.StartNew();
		try
		{
			ResolveBundlePathOrThrow(catalog);
			var loaded = LoadCatalogPrefabsOrThrow(catalog);
			catalog.PayloadValidated = true;
			timer.Stop();
			Plugin.LogSource?.LogInfo(LogPrefix + "first-use loaded " + loaded + " prefab(s) for '" + fraction
				+ "' before presentation changes in " + timer.ElapsedMilliseconds + " ms.");
		}
		catch (Exception ex)
		{
			timer.Stop();
			Plugin.LogSource?.LogFatal(LogPrefix + "first-use payload load failed for '" + fraction
				+ "' before presentation changes; no 2D fallback is available: " + ex);
			throw;
		}
	}

	private static int LoadCatalogPrefabsOrThrow(SceneCatalog catalog)
	{
		var loaded = 0;
		foreach (var pair in catalog.PrefabKeyByLayer)
		{
			LoadPrefabOrThrow(catalog, pair.Key);
			loaded++;
		}
		if (catalog.FullScene3d)
		{
			LoadPrefabByKeyOrThrow(catalog, EnvironmentCacheKey, catalog.EnvironmentPrefabKey);
			loaded++;
		}
		return loaded;
	}

	private static void ValidateRestPoseSourceOrThrow(SceneCatalog catalog)
	{
		var path = Path.Combine(Application.dataPath, catalog.RestSourceLevelFile);
		if (!File.Exists(path))
			throw new FileNotFoundException(LogPrefix + "v2 rest-pose source scene asset is missing: " + path, path);
		using var stream = File.OpenRead(path);
		using var sha = SHA256.Create();
		var actual = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
		if (!string.Equals(actual, catalog.RestSourceLevelSha256, StringComparison.OrdinalIgnoreCase))
			throw new InvalidOperationException(LogPrefix + "v2 rest-pose source scene asset changed for '" + catalog.Fraction
				+ "' (" + path + "); regenerate the camera extraction and town catalog before seating the scene.");
	}

	/// <summary>Owned root in the catalog's camera frame, with frustum-ratio scaling.</summary>
	internal static GameObject EnsureRoot(Scene scene, Camera camera, string fraction)
	{
		var catalog = Catalogs[fraction];
		// This check belongs to town activation, not main-menu preload: a game asset update must refuse this
		// scene with a clear presentation error rather than terminating the whole game in PrewarmAtMainMenuOrFail.
		if (catalog.RestPoseSeating && !catalog.RestSourceValidated)
		{
			ValidateRestPoseSourceOrThrow(catalog);
			catalog.RestSourceValidated = true;
		}
		var root = FindRoot(scene);
		if (root == null)
		{
			root = new GameObject(RootName);
			SceneManager.MoveGameObjectToScene(root, scene);
		}
		EnsureFraming(camera, catalog);
		PlaceRoot(root.transform, camera, catalog);
		if (catalog.ClothByPiece.Count > 0)
			RefreshClothWaves(root, catalog);   // the root's aspect scale feeds the world-space wave vectors
		if (catalog.FullScene3d)
			EnsureFarClip(camera);
		if (catalog.FullScene3d && catalog.RequiresCameraDepthTexture)
			EnsureCameraDepthTexture(camera);
		return root;
	}

	/// <summary>
	/// SSR water reads _CameraDepthTexture: request it on the town camera while the scene is shown (restored in Clear).
	/// Built-in-renderer semantics. The game renders with the Hex scriptable pipeline, whose own Hex/Sea river binds
	/// _CameraDepthTexture / _CameraColorTexture; whether that pipeline honours depthTextureMode or fills those
	/// textures in the town scene is runtime-unproven (source/static only).
	/// </summary>
	private static void EnsureCameraDepthTexture(Camera camera)
	{
		if (camera == null)
			throw new InvalidOperationException(LogPrefix + "SSR water needs the town camera's depth texture but there is no camera.");
		if (_depthTextureCamera != camera)
		{
			RestoreCameraDepthTexture();
			_depthTextureCamera = camera;
			_depthTextureOriginal = camera.depthTextureMode;
		}
		if ((camera.depthTextureMode & DepthTextureMode.Depth) != 0)
			return;
		camera.depthTextureMode |= DepthTextureMode.Depth;
		Plugin.LogSource?.LogInfo(LogPrefix + "camera depthTextureMode " + _depthTextureOriginal + " -> "
			+ camera.depthTextureMode + " for the SSR water (catalog waterLook.screenSpaceReflection.requiresCameraDepthTexture).");
	}

	private static void RestoreCameraDepthTexture()
	{
		if (_depthTextureCamera != null)
			_depthTextureCamera.depthTextureMode = _depthTextureOriginal;
		_depthTextureCamera = null;
	}

	/// <summary>The camera's FOV before framing narrowed it (the frame the root's scale is registered to).</summary>
	private static float NativeFov(Camera camera) =>
		_framingCamera != null && _framingCamera == camera ? _framingNativeFov : camera.fieldOfView;

	private static void EnsureFraming(Camera camera, SceneCatalog catalog)
	{
		if (!catalog.HasFraming)
		{
			RestoreFraming();
			return;
		}
		if (_framingCamera != camera)
		{
			RestoreFraming();
			_framingCamera = camera;
			_framingNativeFov = camera.fieldOfView;
		}
		var tan = Mathf.Tan(_framingNativeFov * 0.5f * Mathf.Deg2Rad) / catalog.FramingZoom;
		var fov = 2f * Mathf.Atan(tan) * Mathf.Rad2Deg;
		if (Mathf.Abs(camera.fieldOfView - fov) > 0.0001f)
		{
			Plugin.LogSource?.LogInfo(LogPrefix + "framing '" + catalog.Fraction + "': camera fov "
				+ _framingNativeFov.ToString("0.###", CultureInfo.InvariantCulture) + " -> "
				+ fov.ToString("0.###", CultureInfo.InvariantCulture) + " (zoom "
				+ catalog.FramingZoom.ToString("0.###", CultureInfo.InvariantCulture) + ").");
			camera.fieldOfView = fov;
		}
		if (Mathf.Abs(catalog.FramingPanScale - 1f) > 0.0001f)
			EnsurePanScale(RestPosePivotOrThrow(camera.transform), catalog);
		else
			RestorePanSettings();
	}

	/// <summary>
	/// Clone the controller's SoCityCameraSettings (a shared asset: never mutated) with the sweep nodes scaled about
	/// the rest camera and the cursor angles scaled, and assign the clone. Idempotent per controller.
	/// </summary>
	private static void EnsurePanScale(Transform pivot, SceneCatalog catalog)
	{
		var type = ModActions.GetHexType(GameSymbols.FactoryCityScene.CityCameraControllerTypeName)
			?? throw new InvalidOperationException(LogPrefix + "framing: BhCityCameraController type missing.");
		var native = pivot.GetComponent(Il2CppType.From(type))
			?? throw new InvalidOperationException(LogPrefix + "framing: CityCamera pivot has no BhCityCameraController.");
		var controller = (Component)Activator.CreateInstance(type, native.Pointer);
		var settingsProperty = type.GetProperty(GameSymbols.FactoryCityScene.CityCameraSettingsMember)
			?? throw new InvalidOperationException(LogPrefix + "framing: BhCityCameraController has no settings member.");
		var current = settingsProperty.GetValue(controller) as UnityEngine.Object
			?? throw new InvalidOperationException(LogPrefix + "framing: BhCityCameraController.settings is null.");
		if (_panController != null && _panController.Pointer == controller.Pointer
		    && _panClone != null && current.Pointer == _panClone.Pointer)
			return;
		RestorePanSettings();
		current = settingsProperty.GetValue(controller) as UnityEngine.Object
			?? throw new InvalidOperationException(LogPrefix + "framing: BhCityCameraController.settings is null.");
		var settingsType = current.GetType();
		var cloneBase = UnityEngine.Object.Instantiate(current);
		cloneBase.name = current.name + " (framed)";
		var clone = (UnityEngine.Object)Activator.CreateInstance(settingsType, cloneBase.Pointer);
		var s = catalog.FramingPanScale;
		foreach (var member in new[] { GameSymbols.FactoryCityScene.CityCameraDeltaHorizontalAngleMember,
			         GameSymbols.FactoryCityScene.CityCameraDeltaVerticalAngleMember })
		{
			var angle = settingsType.GetProperty(member)
				?? throw new InvalidOperationException(LogPrefix + "framing: SoCityCameraSettings has no " + member + ".");
			angle.SetValue(clone, (float)angle.GetValue(clone) * s);
		}
		var nodesProperty = settingsType.GetProperty(GameSymbols.FactoryCityScene.CityCameraPositionNodesMember)
			?? throw new InvalidOperationException(LogPrefix + "framing: SoCityCameraSettings has no positionNodes.");
		// Instantiate deep-copies the serialized list, so the clone's nodes are its own and the shared asset keeps its values.
		var nodes = nodesProperty.GetValue(clone)
			?? throw new InvalidOperationException(LogPrefix + "framing: SoCityCameraSettings.positionNodes is null.");
		var original = nodesProperty.GetValue(current);
		var listType = nodes.GetType();
		var countProperty = listType.GetProperty("Count")
			?? throw new InvalidOperationException(LogPrefix + "framing: positionNodes has no Count.");
		var item = listType.GetProperty("Item")
			?? throw new InvalidOperationException(LogPrefix + "framing: positionNodes has no indexer.");
		if (original is Il2CppSystem.Object a && nodes is Il2CppSystem.Object b && a.Pointer == b.Pointer)
			throw new InvalidOperationException(LogPrefix + "framing: the settings clone shares its positionNodes list with the asset.");
		var count = (int)countProperty.GetValue(nodes);
		if (count < 2)
			throw new InvalidOperationException(LogPrefix + "framing: positionNodes has " + count + " nodes.");
		var rest = pivot.TransformPoint(catalog.RestLocalPosition);
		for (var i = 0; i < count; i++)
		{
			var node = (Vector3)item.GetValue(nodes, new object[] { i });
			item.SetValue(nodes, rest + (node - rest) * s, new object[] { i });
		}
		settingsProperty.SetValue(controller, clone);
		_panController = controller;
		_panSettingsProperty = settingsProperty;
		_panOriginalSettings = current;
		_panClone = clone;
		Plugin.LogSource?.LogInfo(LogPrefix + "framing '" + catalog.Fraction + "': camera settings '" + current.name
			+ "' -> scaled clone (panScale " + s.ToString("0.###", CultureInfo.InvariantCulture) + ", " + count
			+ " sweep nodes about the rest camera).");
		if (!_panSplineCaveatLogged)
		{
			_panSplineCaveatLogged = true;
			Plugin.LogSource?.LogWarning(LogPrefix + "framing: whether BhCityCameraController rebuilds its sweep spline "
				+ "from the swapped settings is runtime-unproven; if it cached the spline, the sweep keeps its native extent.");
		}
	}

	private static void RestorePanSettings()
	{
		// Unity null: false once the controller unloaded with its scene, which leaves nothing to restore.
		if (_panController != null && _panSettingsProperty != null && _panOriginalSettings != null)
			_panSettingsProperty.SetValue(_panController, _panOriginalSettings);
		if (_panClone != null)
			UnityEngine.Object.Destroy(_panClone);
		_panController = null;
		_panSettingsProperty = null;
		_panOriginalSettings = null;
		_panClone = null;
	}

	private static void RestoreFraming()
	{
		if (_framingCamera != null)
			_framingCamera.fieldOfView = _framingNativeFov;
		_framingCamera = null;
		RestorePanSettings();
	}

	private static void EnsureFarClip(Camera camera)
	{
		if (camera.farClipPlane >= FullSceneMinFarClip)
			return;
		if (_farClipCamera != camera)
		{
			_farClipCamera = camera;
			_farClipOriginal = camera.farClipPlane;
		}
		Plugin.LogSource?.LogInfo(LogPrefix + "camera far clip " + camera.farClipPlane.ToString("0.##", CultureInfo.InvariantCulture)
			+ " -> " + FullSceneMinFarClip.ToString("0.##", CultureInfo.InvariantCulture) + " for the full-3D sky dome.");
		camera.farClipPlane = FullSceneMinFarClip;
	}

	/// <summary>
	/// Full-3D environment (terrain, water, sky, scatter) under the root, instantiated once and kept. Mesh_ pieces
	/// are Hex/Lit like layer bodies but get no Body role and no collider (clicks stay on buildings); Sky_ pieces an
	/// opaque sky drawn first; Fx_ pieces the sprite material. Any other root child is refused.
	/// </summary>
	internal static GameObject EnsureEnvironment(GameObject root, string fraction, Material donor,
		Func<Texture2D, Material> spriteMaterial)
	{
		var catalog = Catalogs[fraction];
		if (!catalog.FullScene3d)
			throw new InvalidOperationException(LogPrefix + "'" + fraction + "' is not a full-3D catalog.");
		var existing = root.transform.Find(EnvironmentInstanceName);
		if (existing != null)
			return existing.gameObject;
		var prefab = LoadPrefabByKeyOrThrow(catalog, EnvironmentCacheKey, catalog.EnvironmentPrefabKey);
		var instance = UnityEngine.Object.Instantiate(prefab, root.transform, false);
		instance.name = EnvironmentInstanceName;
		instance.transform.localPosition = Vector3.zero;
		instance.transform.localRotation = Quaternion.identity;
		instance.transform.localScale = Vector3.one;
		int lit = 0, sky = 0, fx = 0, skyPanorama = 0;
		for (var i = 0; i < instance.transform.childCount; i++)
		{
			var child = instance.transform.GetChild(i);
			var name = child != null ? child.name ?? string.Empty : string.Empty;
			if (name.StartsWith(MeshPiecePrefix, StringComparison.Ordinal))
			{
				RebindLitPieceOrThrow(child, donor);
				lit++;
			}
			else if (name.StartsWith(SkyPiecePrefix, StringComparison.Ordinal))
			{
				var renderers = child.GetComponentsInChildren<MeshRenderer>(true);
				if (renderers.Length == 0)
					throw new InvalidOperationException(LogPrefix + "environment sky piece '" + name + "' has no renderer.");
				if (catalog.SkyPiece != null && string.Equals(name, catalog.SkyPiece, StringComparison.Ordinal))
				{
					KeepSkyPanoramaOrThrow(name, renderers, catalog);
					skyPanorama++;
					sky++;
					continue;
				}
				for (var r = 0; r < renderers.Length; r++)
				{
					var bundled = renderers[r].sharedMaterial;
					var bundledShader = bundled != null && bundled.shader != null ? bundled.shader.name : null;
					if (bundledShader != null && bundledShader.EndsWith(SkyPanoramaShaderSuffix, StringComparison.Ordinal))
						throw new InvalidOperationException(LogPrefix + "environment sky piece '" + name + "' uses '" + bundledShader
							+ "' but the catalog's skyLook does not declare it (it would be drawn as a sprite dome).");
					var material = new Material(spriteMaterial(PaintedTextureOrThrow(renderers[r])))
					{
						name = "OfflineUnlockTownScene3DSky." + name,
						renderQueue = SkyRenderQueue
					};
					OwnedSkyMaterials.Add(material);
					renderers[r].sharedMaterial = material;
					renderers[r].shadowCastingMode = ShadowCastingMode.Off;
					renderers[r].receiveShadows = false;
				}
				sky++;
			}
			else if (name.StartsWith(FxPiecePrefix, StringComparison.Ordinal))
			{
				var renderers = child.GetComponentsInChildren<MeshRenderer>(true);
				for (var r = 0; r < renderers.Length; r++)
				{
					renderers[r].sharedMaterial = spriteMaterial(PaintedTextureOrThrow(renderers[r]));
					renderers[r].shadowCastingMode = ShadowCastingMode.Off;
					renderers[r].receiveShadows = false;
				}
				fx++;
			}
			else
			{
				throw new InvalidOperationException(LogPrefix + "environment prefab '" + catalog.EnvironmentPrefabKey
					+ "' has root child '" + name + "' outside Mesh_/Sky_/Fx_.");
			}
		}
		if (lit == 0 || sky == 0)
			throw new InvalidOperationException(LogPrefix + "environment prefab '" + catalog.EnvironmentPrefabKey
				+ "' needs Mesh_ terrain and a Sky_ dome (Mesh_=" + lit + " Sky_=" + sky + ").");
		if (catalog.SkyPiece != null && (skyPanorama != 1 || sky != 1))
			throw new InvalidOperationException(LogPrefix + "catalog skyLook declares the one sky '" + catalog.SkyPiece
				+ "' but the environment prefab has Sky_=" + sky + " with " + skyPanorama + " panorama piece(s): the sky must be a single surface.");
		var ssr = CheckSsrWaterOrThrow(instance, catalog);
		// The prefab's own colliders are disabled: picking is Homm3TownScene3dPick's job (buildings pick by MeshColliders
		// on their drawn meshes, environment Mesh_ pieces get its pick occluders on layer 31).
		var colliders = instance.GetComponentsInChildren<Collider>(true);
		for (var i = 0; i < colliders.Length; i++)
			colliders[i].enabled = false;
		Plugin.LogSource?.LogInfo(LogPrefix + "applied environment '" + catalog.EnvironmentPrefabKey + "' Mesh_=" + lit
			+ " Sky_=" + sky + " skyPanorama=" + skyPanorama + " Fx_=" + fx + " ssrWater=" + ssr
			+ " collidersDisabled=" + colliders.Length + ".");
		return instance;
	}

	/// <summary>
	/// The declared continuous sky keeps its bundle material (Homm3Town/SkyPanorama: direction-only lookup, depth at the
	/// far plane); every renderer under it must carry exactly the catalog's shader. No shadows.
	/// </summary>
	private static void KeepSkyPanoramaOrThrow(string name, MeshRenderer[] renderers, SceneCatalog catalog)
	{
		for (var r = 0; r < renderers.Length; r++)
		{
			var material = renderers[r].sharedMaterial;
			var shaderName = material != null && material.shader != null ? material.shader.name : null;
			if (!string.Equals(shaderName, catalog.SkyShader, StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "environment sky piece '" + name + "' renderer '" + renderers[r].name
					+ "' has shader '" + (shaderName ?? "<null>") + "', not the catalog skyLook shader '" + catalog.SkyShader + "'.");
			renderers[r].shadowCastingMode = ShadowCastingMode.Off;
			renderers[r].receiveShadows = false;
			// The shader's clock is _Time.y (time since level load) + _TimeOffset: zero it at apply so a drifting
			// panorama (_DriftDegPerSec != 0) starts on the painting at the rest pose. Static skies are unaffected.
			material.SetFloat(SkyTimeOffsetProperty, -Time.timeSinceLevelLoad);
		}
	}

	/// <summary>
	/// Fail closed both ways: an SSR water material (a shader named */SsrWater) needs the catalog's waterLook.screenSpaceReflection
	/// depth-texture declaration naming that shader, and every declared SSR piece must carry one. Returns the number
	/// of SSR renderers.
	/// </summary>
	private static int CheckSsrWaterOrThrow(GameObject instance, SceneCatalog catalog)
	{
		var count = 0;
		var seen = new HashSet<string>(StringComparer.Ordinal);
		var renderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var material = renderers[i].sharedMaterial;
			var shaderName = material != null && material.shader != null ? material.shader.name : null;
			if (shaderName == null || !shaderName.EndsWith("/SsrWater", StringComparison.Ordinal))
				continue;
			var holder = renderers[i].transform.parent;
			var piece = holder != null ? holder.name : renderers[i].name;
			if (!catalog.RequiresCameraDepthTexture || !string.Equals(shaderName, catalog.SsrShader, StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "environment piece '" + piece + "' uses SSR shader '" + shaderName
					+ "' but the catalog does not declare waterLook.screenSpaceReflection for it (the camera depth texture would not be requested).");
			seen.Add(piece);
			count++;
		}
		foreach (var piece in catalog.SsrPieces)
			if (!seen.Contains(piece))
				throw new InvalidOperationException(LogPrefix + "catalog waterLook.screenSpaceReflection declares piece '" + piece
					+ "' but the environment prefab has no SSR renderer under it.");
		return count;
	}

	private static Texture2D PaintedTextureOrThrow(MeshRenderer renderer)
	{
		var raw = renderer.sharedMaterial != null ? renderer.sharedMaterial.mainTexture : null;
		var tex = raw ? raw.TryCast<Texture2D>() : null;
		if (tex == null)
			throw new InvalidOperationException(LogPrefix + "painted part '" + renderer.name + "' has no texture.");
		return tex;
	}

	/// <summary>Hex/Lit rebind of one Mesh_ piece with its own baked albedo, no atlas tiling, no shadows.</summary>
	private static void RebindLitPieceOrThrow(Transform piece, Material donor)
	{
		if (!Homm3TownSceneMeshBundle.TryRebindRenderersToCityDonor(piece.gameObject, donor, Plugin.LogSource))
			throw new InvalidOperationException(LogPrefix + "Hex/Lit rebind failed for '" + piece.name + "'.");
		var renderers = piece.GetComponentsInChildren<MeshRenderer>(true);
		for (var r = 0; r < renderers.Length; r++)
		{
			var mats = renderers[r].sharedMaterials;
			for (var m = 0; m < mats.Length; m++)
			{
				// The baked albedo covers the whole UV square: drop the donor atlas tiling and tint.
				if (mats[m].HasProperty("_MainTex"))
				{
					mats[m].SetTextureScale("_MainTex", Vector2.one);
					mats[m].SetTextureOffset("_MainTex", Vector2.zero);
				}
				if (mats[m].HasProperty("_Color"))
					mats[m].SetColor("_Color", Color.white);
				// Back-face culling pinned, not inherited from whichever Hex/Lit donor the city scene offers: the
				// full-3D relief / solids are wound toward the rest camera and proven offline under Cull Back
				// (the lab replica matches, docs/homm3_town_depth_building_solids.md).
				if (!mats[m].HasProperty(HexLitCullModeProperty))
					throw new InvalidOperationException(LogPrefix + "Hex/Lit clone on '" + piece.name + "' has no "
						+ HexLitCullModeProperty + ".");
				mats[m].SetFloat(HexLitCullModeProperty, (float)CullMode.Back);
				// No runtime outline: the full-screen Hidden/Hex/ContourLines pass draws a dark line at every depth
				// step, and painted layers stacked back to front step in depth along every object's outline (and
				// between an object's own segments), which is painted art, not a silhouette to ink.
				if (mats[m].HasProperty(HexLitContourOpacityProperty))
					mats[m].SetFloat(HexLitContourOpacityProperty, 0f);
			}
			// The bake divides by key + fill + trilight without shadows (docs/conflux_town3d_pilot.md).
			renderers[r].shadowCastingMode = ShadowCastingMode.Off;
			renderers[r].receiveShadows = false;
		}
	}

	/// <summary>
	/// The native Hex/Lit FLAG vertex wave on one rebound Mesh_Cloth_ piece (town_full3d_cloth.v1): posWS += _FlagPower *
	/// sin(dot(posWS, _FlagDirection) + _Time.y * _FlagSpeed) * COLOR.r, the mesh's vertex colour red being the weight
	/// (0 at the hoist). A piece without a colour stream, a clone without the FLAG properties, or a keyword that does
	/// not stick is refused: half a wave (or the whole piece sliding) is worse than none.
	/// </summary>
	private static void ApplyClothWaveOrThrow(Transform piece, ClothWave wave)
	{
		var renderers = piece.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers.Length == 0)
			throw new InvalidOperationException(LogPrefix + "cloth piece '" + piece.name + "' has no MeshRenderer.");
		for (var r = 0; r < renderers.Length; r++)
		{
			var filter = renderers[r].GetComponent<MeshFilter>();
			var mesh = filter != null ? filter.sharedMesh : null;
			if (mesh == null || !mesh.HasVertexAttribute(VertexAttribute.Color))
				throw new InvalidOperationException(LogPrefix + "cloth piece '" + piece.name
					+ "' has no vertex colour stream (the wave weight did not ship).");
			var mats = renderers[r].sharedMaterials;
			for (var m = 0; m < mats.Length; m++)
			{
				var mat = mats[m];
				foreach (var prop in ClothWaveProperties)
					if (!mat.HasProperty(prop))
						throw new InvalidOperationException(LogPrefix + "Hex/Lit clone on cloth piece '" + piece.name
							+ "' has no " + prop + ".");
				mat.SetFloat("_VertexDisplacementType", Homm3MeshFx.FlagDisplacementType);
				mat.SetFloat("_FlagSpeed", wave.Speed);
				mat.DisableKeyword(Homm3MeshFx.TreeDisplacementKeyword);
				mat.EnableKeyword(Homm3MeshFx.FlagDisplacementKeyword);
				SetClothVectors(renderers[r].transform, mat, wave);
				if (!HasKeyword(mat, Homm3MeshFx.FlagDisplacementKeyword)
				    || Mathf.Abs(mat.GetFloat("_VertexDisplacementType") - Homm3MeshFx.FlagDisplacementType) > 1e-4f)
					throw new InvalidOperationException(LogPrefix + "Hex/Lit FLAG wave did not stick on cloth piece '"
						+ piece.name + "'.");
			}
		}
	}

	private static readonly string[] ClothWaveProperties = { "_VertexDisplacementType", "_FlagDirection", "_FlagPower", "_FlagSpeed" };

	/// <summary>
	/// The catalog's prefab-frame wave in world space for this renderer: power by localToWorld (a displacement), direction by
	/// the inverse transpose (a phase gradient: dot(posWS, D_world) = dot(posLocal, D_local) + const). The root's aspect
	/// scale is non-uniform, so both change whenever the root is placed.
	/// </summary>
	private static void SetClothVectors(Transform renderer, Material mat, ClothWave wave)
	{
		var p = renderer.TransformVector(wave.Power);
		var d = ClothDirectionWorld(renderer.worldToLocalMatrix, wave.Direction);
		mat.SetVector("_FlagPower", new Vector4(p.x, p.y, p.z, 0f));
		mat.SetVector("_FlagDirection", new Vector4(d.x, d.y, d.z, 0f));
	}

	/// <summary>(worldToLocalMatrix)^T * d written out: the inverse transpose of localToWorld applied to a gradient.</summary>
	private static Vector3 ClothDirectionWorld(Matrix4x4 w2l, Vector3 d) =>
		new(w2l.m00 * d.x + w2l.m10 * d.y + w2l.m20 * d.z,
			w2l.m01 * d.x + w2l.m11 * d.y + w2l.m21 * d.z,
			w2l.m02 * d.x + w2l.m12 * d.y + w2l.m22 * d.z);

	private static void RefreshClothWaves(GameObject root, SceneCatalog catalog)
	{
		var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
		for (var r = 0; r < renderers.Length; r++)
		{
			var holder = renderers[r] != null ? renderers[r].transform.parent : null;
			if (holder == null || holder.name == null || !holder.name.StartsWith(ClothPiecePrefix, StringComparison.Ordinal)
			    || !catalog.ClothByPiece.TryGetValue(holder.name, out var wave))
				continue;
			var mats = renderers[r].sharedMaterials;
			for (var m = 0; m < mats.Length; m++)
				SetClothVectors(renderers[r].transform, mats[m], wave);
		}
	}

	private static bool HasKeyword(Material material, string keyword)
	{
		var keywords = material.shaderKeywords;
		if (keywords == null)
			return false;
		for (var i = 0; i < keywords.Length; i++)
			if (string.Equals(keywords[i], keyword, StringComparison.Ordinal))
				return true;
		return false;
	}

	internal static GameObject FindRoot(Scene scene)
	{
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			if (roots[i] != null && string.Equals(roots[i].name, RootName, StringComparison.Ordinal))
				return roots[i];
		}
		return null;
	}

	private static void PlaceRoot(Transform root, Camera camera, SceneCatalog catalog)
	{
		if (camera.orthographic)
			throw new InvalidOperationException(LogPrefix + "town camera is orthographic; the scene is registered to a perspective camera.");
		var cam = camera.transform;
		var tanRef = Mathf.Tan(catalog.ReferenceFov * 0.5f * Mathf.Deg2Rad);
		var tanRt = Mathf.Tan(NativeFov(camera) * 0.5f * Mathf.Deg2Rad);
		var ky = tanRt / tanRef;
		var kx = ky * camera.aspect / catalog.ReferenceAspect;
		root.SetParent(null, worldPositionStays: false);
		if (catalog.RestPoseSeating)
		{
			var pivot = RestPosePivotOrThrow(cam);
			root.position = pivot.TransformPoint(catalog.RestLocalPosition);
			root.rotation = pivot.rotation * catalog.RestLocalRotation * catalog.FramingAim;
		}
		else
		{
			// V1 catalogs intentionally track the live camera to stay registered with the 2D backdrop.
			root.position = cam.position;
			root.rotation = Quaternion.LookRotation(cam.forward, cam.up);
		}
		root.localScale = new Vector3(kx, ky, 1f);
	}

	private static Transform RestPosePivotOrThrow(Transform camera)
	{
		var pivot = camera.parent;
		if (!string.Equals(camera.name, "MainCamera", StringComparison.Ordinal)
		    || pivot == null || !string.Equals(pivot.name, "CityCamera", StringComparison.Ordinal)
		    || pivot.parent != null
		    || !string.Equals(camera.gameObject.scene.name, GameSymbols.FactoryCityScene.FactoryUnitySceneName,
			    StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "v2 rest-pose seating requires the cityFactory root CityCamera/MainCamera hierarchy.");
		var scale = pivot.lossyScale;
		if (Mathf.Abs(scale.x - 1f) > 0.001f || Mathf.Abs(scale.y - 1f) > 0.001f
		    || Mathf.Abs(scale.z - 1f) > 0.001f)
			throw new InvalidOperationException(LogPrefix + "v2 rest-pose seating requires an unscaled native CityCamera pivot.");
		return pivot;
	}

	/// <summary>Instantiate (or reuse) one layer's prefab under the root and rebind its materials.</summary>
	internal static GameObject EnsureLayer(GameObject root, string fraction, string layerId, Material donor,
		Func<Texture2D, Material> spriteMaterial, string instanceName)
	{
		var existing = root.transform.Find(instanceName);
		if (existing != null)
			return existing.gameObject;
		var catalog = Catalogs[fraction];
		var prefab = LoadPrefabOrThrow(catalog, layerId);
		var instance = UnityEngine.Object.Instantiate(prefab, root.transform, false);
		instance.name = instanceName;
		instance.transform.localPosition = Vector3.zero;
		instance.transform.localRotation = Quaternion.identity;
		instance.transform.localScale = Vector3.one;

		var body = new GameObject(BodyChildName);
		body.transform.SetParent(instance.transform, false);
		var pieces = new List<Transform>();
		for (var i = 0; i < instance.transform.childCount; i++)
		{
			var child = instance.transform.GetChild(i);
			if (child != null && child.name != null && child.name.StartsWith(MeshPiecePrefix, StringComparison.Ordinal))
				pieces.Add(child);
		}
		if (pieces.Count == 0)
			throw new InvalidOperationException(LogPrefix + "prefab for '" + layerId + "' has no " + MeshPiecePrefix + " piece.");
		var clothPieces = 0;
		for (var i = 0; i < pieces.Count; i++)
		{
			pieces[i].SetParent(body.transform, worldPositionStays: false);
			RebindLitPieceOrThrow(pieces[i], donor);
			if (!pieces[i].name.StartsWith(ClothPiecePrefix, StringComparison.Ordinal))
				continue;
			if (!catalog.ClothByPiece.TryGetValue(pieces[i].name, out var wave)
			    || !string.Equals(wave.LayerId, layerId, StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "layer '" + layerId + "' ships cloth piece '" + pieces[i].name
					+ "' that the catalog's clothLook does not declare for it.");
			ApplyClothWaveOrThrow(pieces[i], wave);
			clothPieces++;
		}
		var clothDeclared = 0;
		foreach (var kv in catalog.ClothByPiece)
			if (string.Equals(kv.Value.LayerId, layerId, StringComparison.Ordinal))
				clothDeclared++;
		if (clothPieces != clothDeclared)
			throw new InvalidOperationException(LogPrefix + "layer '" + layerId + "' clothLook declares " + clothDeclared
				+ " cloth pieces but its prefab has " + clothPieces + ".");

		// Skirts, holes and animated parts are painted HoMM3 pixels: unlit sprite presentation.
		var all = instance.GetComponentsInChildren<MeshRenderer>(true);
		for (var i = 0; i < all.Length; i++)
		{
			var renderer = all[i];
			if (renderer == null || renderer.transform.IsChildOf(body.transform))
				continue;
			renderer.sharedMaterial = spriteMaterial(PaintedTextureOrThrow(renderer));
			renderer.shadowCastingMode = ShadowCastingMode.Off;
			renderer.receiveShadows = false;
		}
		Plugin.LogSource?.LogInfo(LogPrefix + "applied layer '" + layerId + "' prefab '" + catalog.PrefabKeyByLayer[layerId]
			+ "' pieces=" + pieces.Count + " painted=" + (all.Length - CountUnder(all, body.transform)) + ".");
		return instance;
	}

	private static int CountUnder(MeshRenderer[] renderers, Transform parent)
	{
		var n = 0;
		for (var i = 0; i < renderers.Length; i++)
			if (renderers[i] != null && renderers[i].transform.IsChildOf(parent))
				n++;
		return n;
	}

	/// <summary>World bounds of the mesh body (the part a click and SpawnEffect should follow).</summary>
	internal static Transform BodyOf(GameObject instance) =>
		instance != null ? instance.transform.Find(BodyChildName) : null;

	internal static void RemoveLayersExcept(GameObject root, HashSet<string> keepNames)
	{
		for (var i = root.transform.childCount - 1; i >= 0; i--)
		{
			var child = root.transform.GetChild(i);
			if (child != null && !keepNames.Contains(child.name))
				UnityEngine.Object.Destroy(child.gameObject);
		}
	}

	/// <summary>
	/// Hex/Lit donor with the fewest keywords (no emission / displacement / clip variant), so the baked albedo
	/// is shaded by the plain Lit formula the bake inverted. Must run before donor renderers are hidden.
	/// </summary>
	internal static Material CaptureCleanHexLitDonorOrThrow(Scene scene, Func<GameObject, bool> isOwned)
	{
		if (_cleanDonor != null && _cleanDonor.shader != null)
			return _cleanDonor;
		Material best = null;
		var bestKeywords = int.MaxValue;
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null || isOwned(root))
				continue;
			var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
			for (var r = 0; renderers != null && r < renderers.Length; r++)
			{
				var mats = renderers[r] != null ? renderers[r].sharedMaterials : null;
				for (var m = 0; mats != null && m < mats.Length; m++)
				{
					var mat = mats[m];
					if (mat == null || mat.shader == null)
						continue;
					var shaderName = mat.shader.name ?? string.Empty;
					if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0)
						continue;
					var kws = mat.shaderKeywords;
					var n = kws != null ? kws.Length : 0;
					if (n < bestKeywords)
					{
						best = mat;
						bestKeywords = n;
					}
				}
			}
		}
		if (best == null)
			throw new InvalidOperationException(LogPrefix + "no Hex/Lit donor material in the city scene.");
		_cleanDonor = best;
		var donorCull = best.HasProperty(HexLitCullModeProperty)
			? best.GetFloat(HexLitCullModeProperty).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
			: "absent";
		Plugin.LogSource?.LogInfo(LogPrefix + "Hex/Lit donor '" + best.name + "' keywords=["
			+ string.Join(",", best.shaderKeywords ?? Array.Empty<string>()) + "] donorCullMode=" + donorCull
			+ " (lit pieces pinned to " + (int)CullMode.Back + ").");
		return best;
	}

	/// <summary>Key light and fog via the city's LightingSettings volume, plus the fill light. Re-run on reposition.</summary>
	internal static void ApplyLighting(Scene scene, Camera camera, string fraction)
	{
		var catalog = Catalogs[fraction];
		var frame = camera.transform;
		if (catalog.RestPoseSeating)
		{
			RestPosePivotOrThrow(frame);
			var root = FindRoot(scene);
			if (root == null)
				throw new InvalidOperationException(LogPrefix + "v2 rest-pose scene root is missing during lighting apply.");
			frame = root.transform;
		}
		if (VolumeOverrides.Count == 0 || VolumeOverrides[0].Volume == null)
			CaptureLightingVolumesOrThrow(scene);

		// bdw::ktg: mainLight.rotation = AngleAxis(azimuth, up) * AngleAxis(zenith, right), so the light's
		// forward is (cos ze sin az, -sin ze, cos ze cos az).
		var key = CameraToWorld(frame, catalog.KeyLocalDir);
		var zenith = Mathf.Asin(Mathf.Clamp(-key.y, -1f, 1f)) * Mathf.Rad2Deg;
		var azimuth = Mathf.Atan2(key.x, key.z) * Mathf.Rad2Deg;
		// Field writes only: ParameterOverride<T>.Override(T) is a value-type generic instantiation the game never
		// calls, so IL2CPP likely compiled no body for it while the interop wrapper still resolves by name. The
		// process died (coreclr 0xc0000005, 2026-09-26) right after the "driving LightingSettings" line, i.e. here.
		for (var i = 0; i < VolumeOverrides.Count; i++)
		{
			var o = VolumeOverrides[i];
			o.Settings.lightZenithAngle.overrideState = true;
			o.Settings.lightZenithAngle.value = zenith;
			o.Settings.lightAzimuthAngle.overrideState = true;
			o.Settings.lightAzimuthAngle.value = azimuth;
			if (catalog.FogOff)
			{
				o.Settings.fogEnabled.overrideState = true;
				o.Settings.fogEnabled.value = false;
			}
		}

		var fill = FindRootNamed(scene, FillLightName);
		if (fill == null)
		{
			fill = new GameObject(FillLightName);
			SceneManager.MoveGameObjectToScene(fill, scene);
			var light = fill.AddComponent<Light>();
			light.type = LightType.Directional;
			light.shadows = LightShadows.None;
			var c = catalog.FillLinear;
			var intensity = Mathf.Max(c.r, Mathf.Max(c.g, c.b));
			if (intensity <= 0f)
				throw new InvalidOperationException(LogPrefix + "fill light colour is black.");
			// lightsUseLinearIntensity: final = color.linear * intensity.
			light.color = new Color(c.r / intensity, c.g / intensity, c.b / intensity, 1f).gamma;
			light.intensity = intensity;
		}
		fill.transform.rotation = Quaternion.LookRotation(CameraToWorld(frame, catalog.FillLocalDir), Vector3.up);
	}

	/// <summary>
	/// Every PostProcessVolume in the city scene whose profile carries LightingSettings gets an instanced profile
	/// (never the shared asset, which other towns and vanilla read). Fail-closed when the scene has none: without
	/// one the Hex pipeline keeps the donor's key and fog whatever the lane writes.
	/// </summary>
	private static void CaptureLightingVolumesOrThrow(Scene scene)
	{
		VolumeOverrides.Clear();
		var inv = CultureInfo.InvariantCulture;
		var roots = scene.GetRootGameObjects();
		for (var r = 0; r < roots.Length; r++)
		{
			if (roots[r] == null || IsOwnedName(roots[r].name))
				continue;
			var volumes = roots[r].GetComponentsInChildren<PostProcessVolume>(true);
			for (var v = 0; volumes != null && v < volumes.Length; v++)
			{
				var volume = volumes[v];
				if (volume == null)
					continue;
				var instancedByUs = !volume.HasInstantiatedProfile();
				if (!FindLightingSettings(instancedByUs ? volume.sharedProfile : volume.profile, out _))
					continue;
				var profile = volume.profile;
				if (!FindLightingSettings(profile, out var settings))
					throw new InvalidOperationException(LogPrefix + "instanced profile of volume '" + volume.name
						+ "' lost its LightingSettings.");
				VolumeOverrides.Add(new VolumeOverride
				{
					Volume = volume,
					InstancedByUs = instancedByUs ? profile : null,
					Settings = settings,
					ZenithState = settings.lightZenithAngle.overrideState,
					Zenith = settings.lightZenithAngle.value,
					AzimuthState = settings.lightAzimuthAngle.overrideState,
					Azimuth = settings.lightAzimuthAngle.value,
					FogState = settings.fogEnabled.overrideState,
					Fog = settings.fogEnabled.value,
				});
				Plugin.LogSource?.LogInfo(LogPrefix + "driving LightingSettings on volume '" + volume.name
					+ "' global=" + volume.isGlobal + " priority=" + volume.priority.ToString("0.##", inv)
					+ " zenith=" + settings.lightZenithAngle.value.ToString("0.#", inv)
					+ " azimuth=" + settings.lightAzimuthAngle.value.ToString("0.#", inv)
					+ " fog=" + settings.fogEnabled.value + " instancedByUs=" + instancedByUs + ".");
			}
		}
		if (VolumeOverrides.Count == 0)
			throw new InvalidOperationException(LogPrefix + "no PostProcessVolume with Hex.Render.LightingSettings in the city scene; "
				+ "the Hex pipeline would overwrite the key light and fog on every render.");
	}

	private static bool FindLightingSettings(PostProcessProfile profile, out LightingSettings settings)
	{
		settings = null;
		if (profile == null || profile.settings == null)
			return false;
		var list = profile.settings;
		for (var i = 0; i < list.Count; i++)
		{
			var item = list[i];
			var candidate = item != null ? item.TryCast<LightingSettings>() : null;
			if (candidate != null)
			{
				settings = candidate;
				return true;
			}
		}
		return false;
	}

	internal static void Clear()
	{
		for (var s = 0; s < SceneManager.sceneCount; s++)
		{
			var scene = SceneManager.GetSceneAt(s);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			var roots = scene.GetRootGameObjects();
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root != null && (string.Equals(root.name, RootName, StringComparison.Ordinal)
					|| string.Equals(root.name, FillLightName, StringComparison.Ordinal)))
					UnityEngine.Object.Destroy(root);
			}
		}
		for (var i = 0; i < VolumeOverrides.Count; i++)
		{
			var o = VolumeOverrides[i];
			if (o.Volume == null)
				continue; // unloaded with its scene
			if (o.InstancedByUs != null)
			{
				o.Volume.profile = null; // back to sharedProfile
				UnityEngine.Object.Destroy(o.InstancedByUs);
				continue;
			}
			o.Settings.lightZenithAngle.overrideState = o.ZenithState;
			o.Settings.lightZenithAngle.value = o.Zenith;
			o.Settings.lightAzimuthAngle.overrideState = o.AzimuthState;
			o.Settings.lightAzimuthAngle.value = o.Azimuth;
			o.Settings.fogEnabled.overrideState = o.FogState;
			o.Settings.fogEnabled.value = o.Fog;
		}
		VolumeOverrides.Clear();
		_cleanDonor = null;
		if (_farClipCamera != null)
			_farClipCamera.farClipPlane = _farClipOriginal;
		_farClipCamera = null;
		RestoreCameraDepthTexture();
		RestoreFraming();
		for (var i = 0; i < OwnedSkyMaterials.Count; i++)
		{
			if (OwnedSkyMaterials[i] != null)
				UnityEngine.Object.Destroy(OwnedSkyMaterials[i]);
		}
		OwnedSkyMaterials.Clear();
	}

	internal static bool IsOwnedName(string name) =>
		string.Equals(name, RootName, StringComparison.Ordinal)
		|| string.Equals(name, FillLightName, StringComparison.Ordinal);

	private static Vector3 CameraToWorld(Transform cam, Vector3 local) =>
		(cam.right * local.x + cam.up * local.y + cam.forward * local.z).normalized;

	private static GameObject FindRootNamed(Scene scene, string name)
	{
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
			if (roots[i] != null && string.Equals(roots[i].name, name, StringComparison.Ordinal))
				return roots[i];
		return null;
	}

	private static GameObject LoadPrefabOrThrow(SceneCatalog catalog, string layerId) =>
		LoadPrefabByKeyOrThrow(catalog, layerId, catalog.PrefabKeyByLayer[layerId]);

	private static GameObject LoadPrefabByKeyOrThrow(SceneCatalog catalog, string cacheKey, string key)
	{
		if (catalog.Prefabs.TryGetValue(cacheKey, out var cached) && cached)
			return cached;
		if (catalog.Bundle == null)
		{
			var path = ResolveBundlePathOrThrow(catalog);
			try
			{
				catalog.Bundle = AssetBundle.LoadFromFile(path);
			}
			catch (Exception ex)
			{
				throw new InvalidOperationException(LogPrefix + "AssetBundle.LoadFromFile failed for fraction '"
					+ catalog.Fraction + "', bundle '" + catalog.BundleFile + "' at " + path + ".", ex);
			}
			if (catalog.Bundle == null)
				throw new InvalidOperationException(LogPrefix + "AssetBundle.LoadFromFile returned null for fraction '"
					+ catalog.Fraction + "', bundle '" + catalog.BundleFile + "' at " + path + ".");
		}
		GameObject prefab;
		try
		{
			prefab = catalog.Bundle.LoadAsset<GameObject>(key);
		}
		catch (Exception ex)
		{
			var role = cacheKey == EnvironmentCacheKey ? "environment" : "layer '" + cacheKey + "'";
			throw new InvalidOperationException(LogPrefix + "failed to load " + role + " prefab '" + key + "' for fraction '"
				+ catalog.Fraction + "' from bundle '" + catalog.BundleFile + "'.", ex);
		}
		if (!prefab)
			throw new InvalidOperationException(LogPrefix + "prefab '" + key + "' missing for fraction '" + catalog.Fraction
				+ "' in bundle '" + catalog.BundleFile + "'.");
		catalog.Prefabs[cacheKey] = prefab;
		return prefab;
	}

	private static string ResolveBundlePathOrThrow(SceneCatalog catalog)
	{
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(
			RelativeFolder + catalog.Fraction + "/" + catalog.BundleFile);
		if (path == null || !File.Exists(path))
			throw new FileNotFoundException(LogPrefix + "bundle file missing for fraction '" + catalog.Fraction
				+ "' (bundle '" + catalog.BundleFile + "').", catalog.BundleFile);
		var actualBytes = new FileInfo(path).Length;
		if (actualBytes != catalog.BundleBytes)
			throw new InvalidDataException(LogPrefix + "bundle byte length mismatch for fraction '" + catalog.Fraction
				+ "' (bundle '" + catalog.BundleFile + "'): catalog=" + catalog.BundleBytes + " actual=" + actualBytes + ".");
		return path;
	}

	private static long ParseBundleBytesOrThrow(string text, string fraction, string path)
	{
		if (!long.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out var bytes) || bytes <= 0)
			throw new InvalidOperationException(LogPrefix + "catalog bundleBytes is invalid for fraction '" + fraction
				+ "' at " + path + ".");
		return bytes;
	}

	private static SceneCatalog ParseCatalogOrThrow(string fraction, string path)
	{
		var root = JObject.Parse(File.ReadAllText(path));
		var schema = Str(root, "schema");
		var restPoseSeating = string.Equals(schema, RestPoseCatalogSchema, StringComparison.Ordinal);
		if (!restPoseSeating && !string.Equals(schema, CatalogSchema, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog schema mismatch at " + path + ": " + (schema ?? "<null>"));
		if (!string.Equals(Str(root, "fraction"), fraction, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " is not for '" + fraction + "'.");
		var catalog = new SceneCatalog
		{
			Fraction = fraction,
			BundleFile = Str(root, "bundle") ?? throw new InvalidOperationException(LogPrefix + "catalog has no bundle."),
			BundleBytes = ParseBundleBytesOrThrow(Str(root, "bundleBytes"), fraction, path),
			FogOff = string.Equals(Str(root, "fog"), "off", StringComparison.Ordinal),
			RestPoseSeating = restPoseSeating
		};
		var fullText = Str(root, "fullScene3d");
		if (fullText != null)
		{
			if (!bool.TryParse(fullText, out var full))
				throw new InvalidOperationException(LogPrefix + "catalog fullScene3d is not a bool: " + fullText);
			catalog.FullScene3d = full;
		}
		if (restPoseSeating && !catalog.FullScene3d)
			throw new InvalidOperationException(LogPrefix + "v2 rest-pose catalog at " + path + " must be fullScene3d.");
		var phaseRevision = Str(root, "phaseRevision");
		if (catalog.FullScene3d)
		{
			if (phaseRevision == null)
				throw new InvalidOperationException(LogPrefix + "full-3D catalog at " + path + " lacks phaseRevision.");
			var digitCount = 0;
			while (digitCount < phaseRevision.Length && phaseRevision[digitCount] >= '0'
			       && phaseRevision[digitCount] <= '9')
				digitCount++;
			if (digitCount == 0 || !int.TryParse(phaseRevision.Substring(0, digitCount), NumberStyles.None,
				    CultureInfo.InvariantCulture, out var revision))
				throw new InvalidOperationException(LogPrefix + "full-3D catalog at " + path + " has invalid phaseRevision.");
			for (var i = digitCount; i < phaseRevision.Length; i++)
				if (phaseRevision[i] < 'a' || phaseRevision[i] > 'z')
					throw new InvalidOperationException(LogPrefix + "full-3D catalog at " + path + " has invalid phaseRevision.");
			if (revision >= 6 && !restPoseSeating)
				throw new InvalidOperationException(LogPrefix + "phase-6 full-3D catalog at " + path
					+ " must use v2 rest-pose seating, not legacy camera-follow v1.");
			if (revision < 6 && restPoseSeating)
				throw new InvalidOperationException(LogPrefix + "v2 rest-pose catalog at " + path
					+ " must declare phaseRevision 6 or later.");
		}
		var backdrop = Str(root, "backdrop");
		if (catalog.FullScene3d)
		{
			if (!string.Equals(backdrop, "hidden", StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "full-3D catalog at " + path + " must say \"backdrop\": \"hidden\" (got "
					+ (backdrop ?? "<null>") + ").");
			catalog.EnvironmentPrefabKey = Str(Obj(root["environment"], "environment"), "prefabKey")
				?? throw new InvalidOperationException(LogPrefix + "full-3D catalog at " + path + " has no environment.prefabKey.");
			var waterLook = root["waterLook"] != null ? Obj(root["waterLook"], "waterLook") : null;
			if (waterLook != null && waterLook["screenSpaceReflection"] != null)
				ParseSsrWaterOrThrow(catalog, Obj(waterLook["screenSpaceReflection"], "waterLook.screenSpaceReflection"), path);
			if (root["skyLook"] != null)
				ParseSkyLookOrThrow(catalog, Obj(root["skyLook"], "skyLook"), path);
			if (root["clothLook"] != null)
				ParseClothLookOrThrow(catalog, Obj(root["clothLook"], "clothLook"), path);
		}
		else if (backdrop != null || root["environment"] != null)
		{
			throw new InvalidOperationException(LogPrefix + "catalog at " + path
				+ " has backdrop/environment but is not fullScene3d.");
		}
		var refCam = Obj(root["referenceCamera"], "referenceCamera");
		catalog.ReferenceFov = Num(refCam, "fov");
		catalog.ReferenceAspect = Num(refCam, "aspect");
		if (restPoseSeating)
		{
			if (catalog.ReferenceFov <= 1f || catalog.ReferenceFov >= 179f
			    || catalog.ReferenceAspect <= 0.1f || catalog.ReferenceAspect >= 10f)
				throw new InvalidOperationException(LogPrefix + "v2 referenceCamera fov/aspect out of bounds at " + path + ".");
			var pose = Obj(refCam["restPose"], "referenceCamera.restPose");
			if (!string.Equals(Str(pose, "pivotName"), "CityCamera", StringComparison.Ordinal)
			    || !string.Equals(Str(pose, "cameraName"), "MainCamera", StringComparison.Ordinal)
			    || !string.Equals(Str(pose, "sourceScene"), GameSymbols.FactoryCityScene.DonorUnitySceneName,
				    StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "v2 restPose at " + path
					+ " must identify the native cityHuman2 CityCamera/MainCamera source.");
			catalog.RestSourceLevelFile = Str(pose, "sourceLevelFile");
			if (catalog.RestSourceLevelFile == null || !catalog.RestSourceLevelFile.StartsWith("level", StringComparison.Ordinal)
			    || catalog.RestSourceLevelFile.Length <= 5)
				throw new InvalidOperationException(LogPrefix + "v2 restPose at " + path + " has invalid sourceLevelFile.");
			for (var i = 5; i < catalog.RestSourceLevelFile.Length; i++)
				if (catalog.RestSourceLevelFile[i] < '0' || catalog.RestSourceLevelFile[i] > '9')
					throw new InvalidOperationException(LogPrefix + "v2 restPose at " + path + " has invalid sourceLevelFile.");
			catalog.RestSourceLevelSha256 = Str(pose, "sourceLevelSha256");
			if (catalog.RestSourceLevelSha256 == null || catalog.RestSourceLevelSha256.Length != 64)
				throw new InvalidOperationException(LogPrefix + "v2 restPose at " + path + " has invalid sourceLevelSha256.");
			for (var i = 0; i < catalog.RestSourceLevelSha256.Length; i++)
			{
				var c = catalog.RestSourceLevelSha256[i];
				if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')))
					throw new InvalidOperationException(LogPrefix + "v2 restPose at " + path + " has invalid sourceLevelSha256.");
			}
			catalog.RestLocalPosition = Vec(pose["localPosition"], "referenceCamera.restPose.localPosition");
			if (Mathf.Abs(catalog.RestLocalPosition.x) > 1000f || Mathf.Abs(catalog.RestLocalPosition.y) > 1000f
			    || Mathf.Abs(catalog.RestLocalPosition.z) > 1000f)
				throw new InvalidOperationException(LogPrefix + "v2 restPose at " + path + " has out-of-bounds localPosition.");
			catalog.RestLocalRotation = Quat(pose["localRotation"], "referenceCamera.restPose.localRotation");
			if (refCam["framing"] != null)
				ParseFramingOrThrow(catalog, Obj(refCam["framing"], "referenceCamera.framing"), path);
		}
		else if (refCam["restPose"] != null || refCam["framing"] != null)
			throw new InvalidOperationException(LogPrefix + "legacy v1 catalog at " + path + " cannot declare a v2 restPose/framing.");
		catalog.KeyLocalDir = Vec(Obj(root["keyLight"], "keyLight")["cameraLocalDir"], "keyLight.cameraLocalDir");
		var fill = Obj(root["fillLight"], "fillLight");
		catalog.FillLocalDir = Vec(fill["cameraLocalDir"], "fillLight.cameraLocalDir");
		var fc = Vec(fill["linearColor"], "fillLight.linearColor");
		catalog.FillLinear = new Color(fc.x, fc.y, fc.z, 1f);
		var layers = Arr(root["layers"], "layers");
		for (var i = 0; i < layers.Count; i++)
		{
			var row = Obj(layers[i], "layers[" + i + "]");
			var layerId = Str(row, "layerId");
			var key = Str(row, "prefabKey");
			if (string.IsNullOrEmpty(layerId) || string.IsNullOrEmpty(key))
				throw new InvalidOperationException(LogPrefix + "catalog layer row " + i + " lacks layerId/prefabKey.");
			catalog.PrefabKeyByLayer[layerId] = key;
		}
		if (catalog.PrefabKeyByLayer.Count == 0)
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " has no layers.");
		// Array of rows, read by index: property enumeration is not used on the interop Newtonsoft.
		// Full-3D draws no 2D layer, so it has no depths (empty or absent); a depth there is a contradiction.
		if (catalog.FullScene3d)
		{
			if (root["layerDepths"] != null && Arr(root["layerDepths"], "layerDepths").Count != 0)
				throw new InvalidOperationException(LogPrefix + "full-3D catalog at " + path + " lists layerDepths.");
			return catalog;
		}
		var depths = Arr(root["layerDepths"], "layerDepths");
		for (var i = 0; i < depths.Count; i++)
		{
			var row = Obj(depths[i], "layerDepths[" + i + "]");
			var layerId = Str(row, "layerId")
				?? throw new InvalidOperationException(LogPrefix + "layerDepths row " + i + " lacks layerId.");
			catalog.LayerDepths[layerId] = Num(row, "distance");
		}
		return catalog;
	}

	/// <summary>Bounds mirror tools/validate_town_scene3d_contract.py (framing block).</summary>
	private static void ParseFramingOrThrow(SceneCatalog catalog, JObject framing, string path)
	{
		if (!string.Equals(Str(framing, "schema"), FramingSchema, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "referenceCamera.framing at " + path + " is not " + FramingSchema + ".");
		var zoom = Num(framing, "zoom");
		var pan = Num(framing, "panScale");
		if (zoom < 1f || zoom > 1.6f)
			throw new InvalidOperationException(LogPrefix + "framing zoom out of [1, 1.6] at " + path + ".");
		if (pan <= 0f || pan > 1f)
			throw new InvalidOperationException(LogPrefix + "framing panScale out of (0, 1] at " + path + ".");
		var aim = Quat(framing["aimRotation"], "referenceCamera.framing.aimRotation");
		if (aim.w < 0.98f) // about 23 degrees: an aim nudges the view toward the buildings, it is not a new view
			throw new InvalidOperationException(LogPrefix + "framing aimRotation turns more than ~23 degrees at " + path + ".");
		catalog.HasFraming = true;
		catalog.FramingZoom = zoom;
		catalog.FramingPanScale = pan;
		catalog.FramingAim = aim;
	}

	private static void ParseSkyLookOrThrow(SceneCatalog catalog, JObject sky, string path)
	{
		if (!string.Equals(Str(sky, "schema"), SkySchema, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " skyLook is not " + SkySchema + ".");
		var shader = Str(sky, "shader");
		if (shader == null || !shader.EndsWith(SkyPanoramaShaderSuffix, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " skyLook.shader '" + (shader ?? "<null>")
				+ "' is not a */SkyPanorama shader.");
		var piece = Str(sky, "piece");
		if (piece == null || !piece.StartsWith(SkyPiecePrefix, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " skyLook.piece '" + (piece ?? "<null>")
				+ "' is not a Sky_ piece.");
		catalog.SkyShader = shader;
		catalog.SkyPiece = piece;
	}

	private static void ParseClothLookOrThrow(SceneCatalog catalog, JObject cloth, string path)
	{
		if (!string.Equals(Str(cloth, "schema"), ClothSchema, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " clothLook is not " + ClothSchema + ".");
		var pieces = Arr(cloth["pieces"], "clothLook.pieces");
		for (var i = 0; i < pieces.Count; i++)
		{
			var row = Obj(pieces[i], "clothLook.pieces[" + i + "]");
			var name = Str(row, "piece");
			var layer = Str(row, "layerId");
			if (name == null || layer == null || !name.StartsWith(ClothPiecePrefix + layer + "_b", StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "catalog at " + path + " clothLook piece '" + (name ?? "<null>")
					+ "' is not a Mesh_Cloth_<layer>_b<k> piece.");
			var wave = new ClothWave
			{
				LayerId = layer,
				Power = Vec(row["power"], "clothLook " + name + ".power"),
				Direction = Vec(row["direction"], "clothLook " + name + ".direction"),
				Speed = Num(row, "speed"),
			};
			if (!(wave.Speed > 0f) || float.IsInfinity(wave.Speed))
				throw new InvalidOperationException(LogPrefix + "catalog at " + path + " clothLook piece '" + name + "' has speed " + wave.Speed + ".");
			if (catalog.ClothByPiece.ContainsKey(name))
				throw new InvalidOperationException(LogPrefix + "catalog at " + path + " clothLook declares '" + name + "' twice.");
			catalog.ClothByPiece[name] = wave;
		}
		if (catalog.ClothByPiece.Count == 0)
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " clothLook has no pieces.");
	}

	private static void ParseSsrWaterOrThrow(SceneCatalog catalog, JObject ssr, string path)
	{
		if (!string.Equals(Str(ssr, "schema"), SsrSchema, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " waterLook.screenSpaceReflection is not " + SsrSchema + ".");
		var depthText = Str(ssr, "requiresCameraDepthTexture");
		if (depthText == null || !bool.TryParse(depthText, out var requiresDepth) || !requiresDepth)
			throw new InvalidOperationException(LogPrefix + "catalog at " + path
				+ " waterLook.screenSpaceReflection must declare requiresCameraDepthTexture true (got " + (depthText ?? "<null>") + ").");
		catalog.RequiresCameraDepthTexture = true;
		catalog.SsrShader = Str(ssr, "shader")
			?? throw new InvalidOperationException(LogPrefix + "catalog at " + path + " waterLook.screenSpaceReflection has no shader.");
		var pieces = Arr(ssr["pieces"], "waterLook.screenSpaceReflection.pieces");
		for (var i = 0; i < pieces.Count; i++)
		{
			var name = pieces[i]?.ToString();
			if (string.IsNullOrEmpty(name) || !name.StartsWith(FxPiecePrefix, StringComparison.Ordinal))
				throw new InvalidOperationException(LogPrefix + "catalog at " + path + " waterLook.screenSpaceReflection piece '" + name
					+ "' is not an Fx_ piece.");
			catalog.SsrPieces.Add(name);
		}
		if (catalog.SsrPieces.Count == 0)
			throw new InvalidOperationException(LogPrefix + "catalog at " + path + " waterLook.screenSpaceReflection has no pieces.");
	}

	// Proxy-safe JSON reads (IL2CPP Newtonsoft: `as JObject` misses; re-parse via ToString, as elsewhere).
	private static string Str(JToken parent, string property)
	{
		var token = parent?[property];
		var text = token?.ToString();
		return string.IsNullOrWhiteSpace(text) ? null : text;
	}

	private static JObject Obj(JToken token, string what) =>
		token as JObject ?? (token != null ? JObject.Parse(token.ToString()) : null)
		?? throw new InvalidOperationException(LogPrefix + "catalog missing object " + what);

	private static JArray Arr(JToken token, string what) =>
		token as JArray ?? (token != null ? JArray.Parse(token.ToString()) : null)
		?? throw new InvalidOperationException(LogPrefix + "catalog missing array " + what);

	private static float Num(JToken parent, string property) =>
		ParseFloat(Str(parent, property), property);

	private static Vector3 Vec(JToken token, string what)
	{
		var a = Arr(token, what);
		if (a.Count != 3)
			throw new InvalidOperationException(LogPrefix + what + " must have 3 components.");
		return new Vector3(ParseFloat(a[0].ToString(), what), ParseFloat(a[1].ToString(), what), ParseFloat(a[2].ToString(), what));
	}

	private static Quaternion Quat(JToken token, string what)
	{
		var a = Arr(token, what);
		if (a.Count != 4)
			throw new InvalidOperationException(LogPrefix + what + " must have 4 components.");
		var q = new Quaternion(ParseFloat(a[0].ToString(), what), ParseFloat(a[1].ToString(), what),
			ParseFloat(a[2].ToString(), what), ParseFloat(a[3].ToString(), what));
		var lengthSquared = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
		if (Mathf.Abs(lengthSquared - 1f) > 0.001f || q.w < 0f)
			throw new InvalidOperationException(LogPrefix + what + " must be unit length with canonical non-negative W.");
		return q;
	}

	private static float ParseFloat(string text, string what)
	{
		if (string.IsNullOrEmpty(text)
		    || !Homm3JsonNumber.TryParseFloat(text, out var value)
		    || float.IsNaN(value) || float.IsInfinity(value))
			throw new InvalidOperationException(LogPrefix + "catalog value '" + what + "' is not a number: " + (text ?? "<null>"));
		return value;
	}
}
