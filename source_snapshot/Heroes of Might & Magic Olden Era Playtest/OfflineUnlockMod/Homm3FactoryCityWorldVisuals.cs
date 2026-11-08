using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using BepInEx;
using HarmonyLib;
using Hex.Session.City;
using Il2CppInterop.Runtime;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Replaces active Castle-parity BhBuilding visuals with HotA town layers for owned cityFactory
/// factions (Factory proven; peers share the compositor and need their own presentation proof).
/// The native manager still owns activation, native Building binding, colliders,
/// hover, and click dispatch; this module only replaces presentation.
/// </summary>
internal static class Homm3FactoryCityWorldVisuals
{
	private const string LogPrefix = "HoMM3 factory city world art: ";
	private const string ArtChildName = "OfflineUnlockFactoryWorldArt";
	private const string TownMeshChildPrefix = Homm3TownSceneMeshBundle.MeshChildPrefix;
	private const string PlateRootName = "OfflineUnlockFactoryWorldPlate";
	private const string BackdropRootName = "OfflineUnlockFactoryWorldBackdrop";
	private const string DecorChildPrefix = "OfflineUnlockFactoryWorldDecor.";
	private const string PresentationShaderName = "Sprites/Default";
	private const string TransparentShaderName = PresentationShaderName;
	private const string LayerMapFileName = "building_layer_map.json";
	private const string PositionsFileName = "positions.json";
	private const string UpscaledBackgroundFileSuffix =
		"_background_upscaled_3840x2160.png";
	private const string MockBackgroundFileSuffix =
		"_background_mock_1920x1080.png";
	private const float BackdropDistance = 80f;
	private const float PlateDistanceBehindBackdrop = 0.5f;
	// Keep HotA quads almost coplanar with the backdrop so perspective cannot
	// drift HotA reference rects relative to the mock plate.
	private const float LayerDistanceFromBackdrop = 0.02f;
	private const string LayoutRevision = "anchorBuildingToArt-repositionBuildingsWithCamera-factory4k-v10";
	private const int CastleSingleVariantLevel = 1;
	private static readonly MaterialPropertyBlock ArtTintBlock = new MaterialPropertyBlock();
	private static Material _cachedCityDonorMaterial;

	private static readonly Regex BuildingLevelSuffix = new Regex(
		@"_Level_(?<level>\d+)$",
		RegexOptions.CultureInvariant | RegexOptions.Compiled | RegexOptions.IgnoreCase);

	private static readonly Dictionary<string, string> BuildingSidBySceneSlot =
		new Dictionary<string, string>(StringComparer.Ordinal)
		{
			["Main"] = "Build_Main",
			["Tier_1"] = "Build_Tier_1",
			["Tier_2"] = "Build_Tier_2",
			["Tier_3"] = "Build_Tier_3",
			["Tier_4"] = "Build_Tier_4",
			["Tier_5"] = "Build_Tier_5",
			["Tier_6"] = "Build_Tier_6",
			["Tier_7"] = "Build_Tier_7",
			["Artifact_Market"] = "Build_Artifact_Market",
			["Golden_Calf"] = "Build_Golden_Calf",
			["Tavern"] = "Build_Tavern",
			["Magic_Guild"] = "Build_Magic_Guild",
			["Treasury"] = "Build_Treasury",
			["Bank"] = "Build_Bank",
			["Market"] = "Build_Market",
			["Walls"] = "Build_Wall",
			["Resource_Depot"] = "Build_Resource_Depot",
			["Resource_Depot_2"] = "Build_Resource_Depot_level_2"
		};

	private static Dictionary<string, Dictionary<int, string>> _levelsBySid;
	private static Dictionary<string, LayerPlacement> _placementsById;
	private static string _loadedFractionSid;
	private static float _canvasWidth;
	private static float _canvasHeight;
	private static float _backgroundWidth;
	private static float _backgroundHeight;
	private static readonly Dictionary<string, Texture2D> TextureCache =
		new Dictionary<string, Texture2D>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, string> TextureStampByPath =
		new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<Texture2D, Material> MaterialByTexture =
		new Dictionary<Texture2D, Material>();
	private static readonly Dictionary<Renderer, bool> OriginalRendererStates =
		new Dictionary<Renderer, bool>();
	private static readonly Dictionary<Behaviour, bool> OriginalTerrainStates =
		new Dictionary<Behaviour, bool>();
	private static readonly Dictionary<BoxCollider, BoxColliderState> OriginalColliderStates =
		new Dictionary<BoxCollider, BoxColliderState>();
	private static Material _sharedUnlit;
	private static bool _loggedManifestPaths;
	private static bool _donorHidden;
	private static string _lastAppliedSignature;
	private static readonly Color HoverTint = new Color(1.35f, 1.35f, 1.12f, 1f);

	internal static bool IsApplied => !string.IsNullOrEmpty(_lastAppliedSignature);

	/// <summary>
	/// Clears the applied-signature gate so the next EnsureOwnedCityPresentationActive
	/// recomposes. Required after native Build_Wall (and peer) construction: town-layer
	/// sync early-returns on <see cref="IsApplied"/> and would otherwise leave donor wall
	/// meshes hidden with no HotA replacement.
	/// </summary>
	internal static void InvalidateAppliedSignature()
	{
		_lastAppliedSignature = null;
	}

	internal static int RegisterHarmony(HarmonyLib.Harmony harmony)
	{
		if (harmony == null)
			throw new InvalidOperationException(LogPrefix + "Harmony missing for hover patches.");
		Homm3FactoryCityWorldAnimDriver.EnsureRegistered();
		var patched = 0;
		patched += PatchBuildingMethod(harmony, nameof(BhBuilding.Select), nameof(PostfixBuildingSelect));
		patched += PatchBuildingMethod(harmony, nameof(BhBuilding.Deselect), nameof(PostfixBuildingDeselect));
		patched += PatchBuildingPointerClick(harmony);
		patched += Homm3TownScene3dPick.RegisterHarmony(harmony);
		return patched;
	}

	private static int PatchBuildingPointerClick(HarmonyLib.Harmony harmony)
	{
		var method = AccessTools.Method(typeof(BhBuilding), nameof(BhBuilding.OnPointerClick));
		var prefix = AccessTools.Method(typeof(Homm3FactoryCityWorldVisuals), nameof(PrefixBuildingPointerClick));
		if (method == null || prefix == null)
			throw new InvalidOperationException(LogPrefix + "missing BhBuilding.OnPointerClick patch surface.");
		harmony.Patch(method, prefix: new HarmonyMethod(prefix));
		return 1;
	}

	/// <summary>
	/// Main (town hall) Visit opens a divergent construction path vs the HUD BuildingsConstruction
	/// select. Open via the HUD navigation path and skip native Visit.
	/// </summary>
	private static bool PrefixBuildingPointerClick(BhBuilding __instance)
	{
		var fraction = ModActions.GetCurrentCityFraction();
		if (!Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction) || __instance == null)
			return true;
		var slot = FindSceneSlot(__instance.transform);
		if (!string.Equals(slot, "Main", StringComparison.Ordinal))
			return true;
		if (!ModActions.TryOpenOwnedCityHallConstructionMenu("owned-city-main-world-click"))
		{
			Plugin.LogSource?.LogError(LogPrefix
				+ "Main world click could not open BuildingsConstruction via HUD navigation; "
				+ "refusing native Visit.");
		}
		return false;
	}

	private static int PatchBuildingMethod(HarmonyLib.Harmony harmony, string methodName, string postfixName)
	{
		var method = AccessTools.Method(typeof(BhBuilding), methodName);
		var postfix = AccessTools.Method(typeof(Homm3FactoryCityWorldVisuals), postfixName);
		if (method == null || postfix == null)
			throw new InvalidOperationException(LogPrefix + "missing BhBuilding." + methodName + " patch surface.");
		harmony.Patch(method, postfix: new HarmonyMethod(postfix));
		return 1;
	}

	private static void PostfixBuildingSelect(BhBuilding __instance)
	{
		SetFactoryArtTint(__instance, HoverTint);
	}

	private static void PostfixBuildingDeselect(BhBuilding __instance)
	{
		SetFactoryArtTint(__instance, Color.white);
	}

	private static void SetFactoryArtTint(BhBuilding building, Color color)
	{
		if (building == null || building.gameObject == null)
			return;
		if (!Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(ModActions.GetCurrentCityFraction()))
			return;
		var art = building.transform.Find(ArtChildName);
		if (art == null)
			return;
		var renderers = art.GetComponentsInChildren<MeshRenderer>(true);
		for (var i = 0; renderers != null && i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (renderer == null)
				continue;
			// Never touch renderer.material — that clones and orphans Homm3FactoryCityWorldAnimDriver's
			// overlay material, freezing animation after the first hover.
			ArtTintBlock.Clear();
			renderer.GetPropertyBlock(ArtTintBlock);
			ArtTintBlock.SetColor("_Color", color);
			renderer.SetPropertyBlock(ArtTintBlock);
		}
	}

	internal static void ApplyOwnedFactoryWorldArt()
	{
		var fraction = ModActions.GetCurrentCityFraction();
		if (!Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction))
			return;
		if (Homm3TownScene3d.IsActiveFor(fraction))
			Homm3TownScene3d.ValidateFactionPayloadOrFail(fraction);
		try
		{
			ApplyOwnedFactoryWorldArtOrThrow(fraction);
		}
		catch (Exception applyException)
		{
			try
			{
				ClearOwnedFactoryWorldArt();
			}
			catch (Exception rollbackException)
			{
				throw new AggregateException(LogPrefix + "presentation apply and rollback both failed.",
					applyException, rollbackException);
			}
			throw;
		}
	}

	private static void ApplyOwnedFactoryWorldArtOrThrow(string fraction)
	{
		EnsureLayerManifestLoadedOrThrow(fraction);
		var scene = SceneManager.GetActiveScene();
		if (!scene.IsValid() || !string.Equals(scene.name,
			    GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + "active scene is not cityFactory.");
		var camera = FindFactoryMainCamera(scene);
		if (camera == null)
			throw new InvalidOperationException(LogPrefix + "MainCamera missing under CityCamera.");

		var activeBySlot = CollectActiveManagerOwnedBuildings(scene);
		if (activeBySlot.Count == 0)
			throw new InvalidOperationException(LogPrefix + "no active manager-owned BhBuilding variants.");

		// Validate the complete native-to-HotA join before changing any renderer or collider.
		// Resolve placements first; load textures only after the applied-signature gate so town-layer
		// sync can re-enter every frame cheaply when late-activating slots grow the join set.
		// Camera-registered 3D scene (Homm3TownScene3d) for fractions that ship a scene catalog.
		var scene3d = Homm3TownScene3d.IsActiveFor(fraction);
		// Full-3D (docs/homm3_conflux_full_3d_town.md): no HotA 2D presentation at all, so a layer without
		// a prefab is never drawn as a quad.
		var full3d = scene3d && Homm3TownScene3d.IsFullScene3d(fraction);
		// User decision 2026-10-13 (GH#28): a built slot with no authored art (no binding, no layer for its
		// level, no placement, or no full-3D prefab) is skipped — hidden and unclickable, logged once per
		// signature — instead of suspending the whole town presentation.
		var resolved = new List<ResolvedBuildingLayer>();
		var skipped = new List<SkippedBuildingSlot>();
		foreach (var pair in activeBySlot)
		{
			var sceneSlot = pair.Key;
			var variants = pair.Value;
			if (!BuildingSidBySceneSlot.TryGetValue(sceneSlot, out var buildingSid))
			{
				skipped.Add(new SkippedBuildingSlot(sceneSlot, variants, "no layer binding"));
				continue;
			}
			var highest = SelectHighestActiveVariantOrThrow(sceneSlot, variants, out var level);
			if (!TryResolveExactLayerId(buildingSid, level, out var layerId))
			{
				skipped.Add(new SkippedBuildingSlot(sceneSlot, variants,
					"no HotA layer for " + buildingSid + " level " + level));
				continue;
			}
			if (!_placementsById.TryGetValue(layerId, out var placement))
			{
				skipped.Add(new SkippedBuildingSlot(sceneSlot, variants,
					"positions.json has no placement for layer '" + layerId + "'"));
				continue;
			}
			if (full3d && !Homm3TownScene3d.HasLayer(fraction, layerId))
			{
				skipped.Add(new SkippedBuildingSlot(sceneSlot, variants,
					"full-3D scene has no prefab for layer '" + layerId + "' (level " + level
					+ "); no 2D fallback in full-3D mode"));
				continue;
			}
			resolved.Add(new ResolvedBuildingLayer(sceneSlot, variants, highest, level, layerId,
				placement, texture: null));
		}

		var signatureParts = new List<string>();
		for (var r = 0; r < resolved.Count; r++)
			signatureParts.Add(resolved[r].SceneSlot + ":" + resolved[r].Level + ":" + resolved[r].LayerId);
		for (var s = 0; s < skipped.Count; s++)
			signatureParts.Add(skipped[s].SceneSlot + ":skipped");
		signatureParts.Sort(StringComparer.Ordinal);
		var signature = fraction + "|" + LayoutRevision + (scene3d ? "|scene3d" : string.Empty) + "|"
			+ string.Join("|", signatureParts);
		if (string.Equals(signature, _lastAppliedSignature, StringComparison.Ordinal)
			&& _donorHidden
			&& HasOwnedPresentationRoots(scene)
			&& (!scene3d || Homm3TownScene3d.FindRoot(scene) != null))
		{
			// Reposition only — camera may have moved; skip texture reload / full donor scans.
			// Plate + backdrop alone is not enough: building art is parented under BhBuilding, not the
			// backdrop, so a camera-only refresh desyncs HotA layers from the mock plate.
			EnsureWorldPlate(scene, camera, hidden: full3d);
			EnsureWorldBackdrop(fraction, scene, camera, hidden: full3d);
			GameObject scene3dRoot = null;
			if (scene3d)
			{
				scene3dRoot = Homm3TownScene3d.EnsureRoot(scene, camera, fraction);
				Homm3TownScene3d.ApplyLighting(scene, camera, fraction);
			}
			for (var r = 0; r < resolved.Count; r++)
			{
				var item = resolved[r];
				if (scene3d && Homm3TownScene3d.HasLayer(fraction, item.LayerId))
				{
					RepositionScene3dLayerOrThrow(item.Highest.gameObject, scene3dRoot, item.LayerId);
					continue;
				}
				if (Homm3TownSceneMeshBundle.IsEnabled()
				    && Homm3TownSceneMeshBundle.HasMeshForLayer(item.LayerId))
				{
					RepositionExistingTownSceneMeshOrThrow(
						item.Highest.gameObject, item.Placement, item.LayerId, camera);
				}
				else
				{
					RepositionExistingBuildingArtOrThrow(
						item.Highest.gameObject, item.Placement, camera);
				}
			}
			return;
		}

		for (var r = 0; r < resolved.Count; r++)
		{
			var item = resolved[r];
			var useMesh = (scene3d && Homm3TownScene3d.HasLayer(fraction, item.LayerId))
				|| (Homm3TownSceneMeshBundle.IsEnabled()
					&& Homm3TownSceneMeshBundle.HasMeshForLayer(item.LayerId));
			resolved[r] = new ResolvedBuildingLayer(item.SceneSlot, item.Variants, item.Highest,
				item.Level, item.LayerId, item.Placement,
				useMesh ? null : LoadLayerTextureOrThrow(fraction, item.Placement.SpriteFile));
		}
		for (var r = 0; r < resolved.Count; r++)
		{
			if (resolved[r].Texture != null)
				MaterialFor(resolved[r].Texture);
		}
		if (!full3d)
			ValidatePresentationAssetsOrThrow(fraction);

		// Full-3D keeps the plate and backdrop roots (reposition and clear key off them) but hides both quads.
		EnsureWorldPlate(scene, camera, hidden: full3d);
		var backdrop = EnsureWorldBackdrop(fraction, scene, camera, hidden: full3d);
		if (!full3d)
			EnsureDecorationLayers(fraction, backdrop, camera);
		Material scene3dDonor = null;
		GameObject scene3dLayerRoot = null;
		var scene3dKeep = new HashSet<string>(StringComparer.Ordinal);
		if (scene3d)
		{
			scene3dDonor = Homm3TownScene3d.CaptureCleanHexLitDonorOrThrow(scene, IsOwnedArtObject);
			scene3dLayerRoot = Homm3TownScene3d.EnsureRoot(scene, camera, fraction);
			if (full3d)
			{
				var environment = Homm3TownScene3d.EnsureEnvironment(scene3dLayerRoot, fraction, scene3dDonor, MaterialFor);
				scene3dKeep.Add(environment.name);
				Homm3TownScene3dPick.EnsureEnvironmentOccludersOrThrow(environment.transform, camera);
			}
		}
		Material cityDonorMaterial = null;
		for (var r = 0; r < resolved.Count; r++)
		{
			if (Homm3TownSceneMeshBundle.IsEnabled()
			    && Homm3TownSceneMeshBundle.HasMeshForLayer(resolved[r].LayerId))
			{
				cityDonorMaterial = CaptureCityDonorMaterialOrThrow(scene);
				break;
			}
		}
		for (var r = 0; r < resolved.Count; r++)
		{
			var item = resolved[r];
			for (var i = 0; i < item.Variants.Count; i++)
			{
				var variant = item.Variants[i];
				if (variant != item.Highest)
				{
					RemoveBuildingArtChild(variant.gameObject);
					RemoveTownSceneMeshChild(variant.gameObject);
				}
			}

			GameObject presentationRoot;
			if (scene3d && Homm3TownScene3d.HasLayer(fraction, item.LayerId))
			{
				RemoveBuildingArtChild(item.Highest.gameObject);
				RemoveTownSceneMeshChild(item.Highest.gameObject);
				presentationRoot = EnsureScene3dLayerOnBuilding(fraction, item.Highest.gameObject,
					scene3dLayerRoot, item.LayerId, scene3dDonor);
				scene3dKeep.Add(presentationRoot.name);
			}
			else if (Homm3TownSceneMeshBundle.IsEnabled()
			    && Homm3TownSceneMeshBundle.HasMeshForLayer(item.LayerId))
			{
				RemoveBuildingArtChild(item.Highest.gameObject);
				presentationRoot = EnsureTownSceneMeshOnBuilding(
					item.Highest.gameObject, item.Placement, item.LayerId, camera, cityDonorMaterial);
			}
			else
			{
				RemoveTownSceneMeshChild(item.Highest.gameObject);
				presentationRoot = EnsureArtQuadOnBuilding(fraction, item.Highest.gameObject, item.Texture,
					item.Placement, item.LayerId, camera);
			}
			for (var i = 0; i < item.Variants.Count; i++)
			{
				var variant = item.Variants[i];
				if (variant != item.Highest)
					DisableNativeBuildingCollidersIfPresent(variant.gameObject);
				else if (scene3d && Homm3TownScene3d.HasLayer(fraction, item.LayerId))
					ApplyScene3dPickOrThrow(variant.gameObject, scene3dLayerRoot, presentationRoot, item.LayerId);
				else
					TryAlignNativeColliderWithArt(variant.gameObject, presentationRoot);
			}
		}
		for (var s = 0; s < skipped.Count; s++)
		{
			var item = skipped[s];
			for (var i = 0; i < item.Variants.Count; i++)
			{
				var variant = item.Variants[i];
				if (variant == null || variant.gameObject == null)
					continue;
				RemoveBuildingArtChild(variant.gameObject);
				RemoveTownSceneMeshChild(variant.gameObject);
				DisableRenderersUnder(variant.transform);
				DisableNativeBuildingCollidersIfPresent(variant.gameObject);
			}
			Plugin.LogSource?.LogWarning(LogPrefix + "skipped native sceneSlot '" + item.SceneSlot + "' for '"
				+ fraction + "': " + item.Reason + "; building left undrawn and unclickable in the town view.");
		}
		if (scene3d)
		{
			Homm3TownScene3d.RemoveLayersExcept(scene3dLayerRoot, scene3dKeep);
			Homm3TownScene3d.ApplyLighting(scene, camera, fraction);
		}
		HideDonorPresentation(scene);

		_lastAppliedSignature = signature;
		Plugin.LogSource?.LogInfo(LogPrefix + "applied " + signatureParts.Count
			+ " native-owned '" + fraction + "' building layer(s); cumulative lower variants hidden with only the highest collider active; "
			+ "clicks remain PhysicsRaycaster -> BhBuilding.");
	}

	private static bool HasOwnedPresentationRoots(Scene scene)
	{
		var roots = scene.GetRootGameObjects();
		var hasPlate = false;
		var hasBackdrop = false;
		for (var i = 0; i < roots.Length; i++)
		{
			if (roots[i] == null)
				continue;
			if (string.Equals(roots[i].name, PlateRootName, StringComparison.Ordinal))
				hasPlate = true;
			if (string.Equals(roots[i].name, BackdropRootName, StringComparison.Ordinal))
				hasBackdrop = true;
		}
		return hasPlate && hasBackdrop;
	}
	internal static void ClearOwnedFactoryWorldArt()
	{
		_lastAppliedSignature = null;
		_donorHidden = false;
		_loadedFractionSid = null;
		_levelsBySid = null;
		_placementsById = null;
		_cachedCityDonorMaterial = null;
		foreach (var pair in OriginalColliderStates)
		{
			var collider = pair.Key;
			if (collider == null)
				continue;
			collider.enabled = pair.Value.Enabled;
			collider.center = pair.Value.Center;
			collider.size = pair.Value.Size;
		}
		OriginalColliderStates.Clear();
		foreach (var pair in OriginalRendererStates)
		{
			if (pair.Key != null)
				pair.Key.enabled = pair.Value;
		}
		OriginalRendererStates.Clear();
		foreach (var pair in OriginalTerrainStates)
		{
			if (pair.Key != null)
				pair.Key.enabled = pair.Value;
		}
		OriginalTerrainStates.Clear();
		Homm3TownScene3d.Clear();
		ClearOwnedFactoryWorldBackdropOnly();
		RemoveUntrackedBuildingArt();
	}

	internal static void ClearOwnedFactoryWorldBackdropOnly()
	{
		for (var s = 0; s < SceneManager.sceneCount; s++)
		{
			var scene = SceneManager.GetSceneAt(s);
			if (!scene.IsValid() || !scene.isLoaded
				|| !string.Equals(scene.name, GameSymbols.FactoryCityScene.FactoryUnitySceneName,
					StringComparison.Ordinal))
				continue;
			var roots = scene.GetRootGameObjects();
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root != null
					&& (string.Equals(root.name, BackdropRootName, StringComparison.Ordinal)
						|| string.Equals(root.name, PlateRootName, StringComparison.Ordinal)))
					UnityEngine.Object.Destroy(root);
			}
		}
	}

	private static Dictionary<string, List<BhBuilding>> CollectActiveManagerOwnedBuildings(Scene scene)
	{
		var manager = FindSingleBuildingsManagerOrThrow(scene);
		var result = new Dictionary<string, List<BhBuilding>>(StringComparer.Ordinal);
		var buildings = manager.transform.root.GetComponentsInChildren<BhBuilding>(true);
		for (var i = 0; buildings != null && i < buildings.Length; i++)
		{
			var building = buildings[i];
			if (building == null || building.gameObject == null || !building.gameObject.activeInHierarchy)
				continue;
			// Newly force-activated variants may bind one frame later; settle retries Apply.
			if (!HasBoundBuildingLogic(building))
				continue;
			var slot = FindSceneSlot(building.transform);
			if (slot == null)
				throw new InvalidOperationException(LogPrefix + "active BhBuilding '" + building.name
					+ "' is not under an expected native sceneSlot.");
			if (!result.TryGetValue(slot, out var variants))
			{
				variants = new List<BhBuilding>();
				result[slot] = variants;
			}
			variants.Add(building);
		}
		return result;
	}

	private static BhBuildingsManager FindSingleBuildingsManagerOrThrow(Scene scene)
	{
		BhBuildingsManager manager = null;
		var managerCount = 0;
		var roots = scene.GetRootGameObjects();
		for (var r = 0; r < roots.Length; r++)
		{
			var managers = roots[r]?.GetComponentsInChildren<BhBuildingsManager>(true);
			for (var i = 0; managers != null && i < managers.Length; i++)
			{
				if (managers[i] == null)
					continue;
				manager = managers[i];
				managerCount++;
			}
		}
		if (managerCount != 1 || manager == null)
			throw new InvalidOperationException(LogPrefix + "cityFactory requires exactly one BhBuildingsManager; found "
				+ managerCount + ".");
		return manager;
	}

	private static string FindSceneSlot(Transform building)
	{
		var cursor = building;
		var depth = 0;
		while (cursor != null && depth < 16)
		{
			var expected = GameSymbols.FactoryCityScene.ExpectedSceneSlotNames;
			for (var i = 0; expected != null && i < expected.Length; i++)
			{
				if (string.Equals(cursor.name, expected[i], StringComparison.Ordinal))
					return expected[i];
			}
			cursor = cursor.parent;
			depth++;
		}
		return null;
	}

	/// <summary>Exposes <see cref="FindSceneSlot"/> for owned-world readiness (Main hall gate).</summary>
	internal static string FindSceneSlotName(Transform building) => FindSceneSlot(building);

	private static BhBuilding SelectHighestActiveVariantOrThrow(
		string sceneSlot, List<BhBuilding> variants, out int highestLevel)
	{
		BhBuilding highest = null;
		highestLevel = 0;
		for (var i = 0; i < variants.Count; i++)
		{
			var candidate = variants[i];
			var level = ResolveBuildingLevelOrThrow(candidate.gameObject);
			if (level < highestLevel)
				continue;
			if (level == highestLevel && highest != null)
				throw new InvalidOperationException(LogPrefix + "native sceneSlot '" + sceneSlot
					+ "' has multiple active variants at level " + level + ".");
			highest = candidate;
			highestLevel = level;
		}
		if (highest == null || highestLevel <= 0)
			throw new InvalidOperationException(LogPrefix + "native sceneSlot '" + sceneSlot
				+ "' has no selectable active variant.");
		return highest;
	}

	/// <summary>
	/// Live native click silently returns when bound Building logic (decomp field ceco / dwc)
	/// is null. The generated interop property is patch-sensitive and centrally pinned.
	/// </summary>
	internal static bool HasBoundBuildingLogic(BhBuilding building)
	{
		if (building == null)
			return false;
		var property = AccessTools.Property(
			typeof(BhBuilding),
			GameSymbols.FactoryCityScene.BuildingBoundLogicPropertyName);
		if (property == null)
			throw new InvalidOperationException(
				LogPrefix + "BhBuilding bound-logic property pin is missing: "
				+ GameSymbols.FactoryCityScene.BuildingBoundLogicPropertyName + ".");
		return property.GetValue(building) != null;
	}

	private static int ResolveBuildingLevelOrThrow(GameObject building)
	{
		var buildingName = building != null ? building.name : null;
		var match = !string.IsNullOrEmpty(buildingName) ? BuildingLevelSuffix.Match(buildingName) : null;
		if (match != null && match.Success
			&& int.TryParse(match.Groups["level"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var level)
			&& level > 0)
			return level;

		// Castle cityHuman2 single-variant slots use unsuffixed names (live-positive: H_build_Tavern,
		// H_build_Market, …). Every owned cityFactory faction inherits that donor graph — not Castle-only.
		// Accept level 1 only when nativeLevels for that SID is exactly {1}.
		// Multi-level slots (Main/Walls/Guild/Tiers) must keep the _Level_N suffix — no blind fallback.
		var slot = building != null ? FindSceneSlot(building.transform) : null;
		if (slot != null
			&& BuildingSidBySceneSlot.TryGetValue(slot, out var buildingSid)
			&& _levelsBySid != null
			&& _levelsBySid.TryGetValue(buildingSid, out var levelsByLevel)
			&& levelsByLevel != null
			&& levelsByLevel.Count == 1
			&& levelsByLevel.ContainsKey(CastleSingleVariantLevel))
			return CastleSingleVariantLevel;

		throw new InvalidOperationException(LogPrefix + "BhBuilding path '"
			+ DescribeUnityPath(building != null ? building.transform : null)
			+ "' does not end in the required _Level_N suffix, and sceneSlot '"
			+ (slot ?? "<none>") + "' is not a single nativeLevels={1} Castle variant.");
	}

	private static string DescribeUnityPath(Transform transform)
	{
		if (transform == null)
			return "<null>";
		var segments = new List<string>();
		var cursor = transform;
		while (cursor != null)
		{
			segments.Add(cursor.name);
			cursor = cursor.parent;
		}
		segments.Reverse();
		return string.Join("/", segments);
	}

	private static void EnsureLayerManifestLoadedOrThrow(string fraction)
	{
		if (string.IsNullOrEmpty(fraction))
			throw new InvalidOperationException(LogPrefix + "owned city fraction is empty.");
		if (_levelsBySid != null && _placementsById != null
			&& string.Equals(_loadedFractionSid, fraction, StringComparison.Ordinal))
			return;
		_levelsBySid = null;
		_placementsById = null;
		_loadedFractionSid = null;
		var layers = Path.Combine("homm3_runtime_assets", "town_scene_refs", fraction, "layers");
		var mapPath = ResolvePluginAssetPath(Path.Combine(layers, LayerMapFileName));
		var positionsPath = ResolvePluginAssetPath(Path.Combine(layers, PositionsFileName));
		if (mapPath == null || !File.Exists(mapPath))
			throw new InvalidOperationException(LogPrefix + "missing " + Path.Combine(layers, LayerMapFileName));
		if (positionsPath == null || !File.Exists(positionsPath))
			throw new InvalidOperationException(LogPrefix + "missing " + Path.Combine(layers, PositionsFileName));
		if (!_loggedManifestPaths)
		{
			_loggedManifestPaths = true;
			Plugin.LogSource?.LogInfo(LogPrefix + "manifest inputs: map='" + mapPath
				+ "' stamp=" + GetFileStamp(mapPath) + "; positions='" + positionsPath
				+ "' stamp=" + GetFileStamp(positionsPath) + ".");
		}

		var map = JObject.Parse(File.ReadAllText(mapPath));
		var levelsRoot = ParseRequiredObjectToken(map["nativeLevels"], LayerMapFileName
			+ " has no explicit nativeLevels object.");
		var levelsBySid = new Dictionary<string, Dictionary<int, string>>(StringComparer.Ordinal);
		var seenSids = new HashSet<string>(StringComparer.Ordinal);
		foreach (var binding in BuildingSidBySceneSlot)
		{
			var sid = binding.Value;
			if (!seenSids.Add(sid))
				continue;
			var levelToken = levelsRoot[sid];
			if (levelToken == null)
				continue;
			var levelObject = ParseRequiredObjectToken(levelToken,
				LayerMapFileName + " nativeLevels." + sid + " is not an object.");
			var levels = new Dictionary<int, string>();
			for (var level = 1; level <= 8; level++)
			{
				var token = levelObject[level.ToString(CultureInfo.InvariantCulture)];
				if (token == null)
					continue;
				if (token.Type != JTokenType.String || string.IsNullOrWhiteSpace(token.ToString()))
					throw new InvalidOperationException(LogPrefix + "invalid level mapping " + sid + "." + level + ".");
				levels[level] = token.ToString();
			}
			if (levels.Count > 0)
				levelsBySid[sid] = levels;
		}

		var positions = JObject.Parse(File.ReadAllText(positionsPath));
		var basis = ParseRequiredObjectToken(positions["coordinateBasis"],
			PositionsFileName + " has no coordinateBasis object.");
		var referenceCanvas = ParseRequiredObjectToken(basis["referenceCanvas"],
			PositionsFileName + " has no referenceCanvas object.");
		// IL2CPP Newtonsoft: JToken.Value<T>(key) TypeInitializes to NRE. Read scalars via ToString.
		_canvasWidth = ReadOptionalFloat(referenceCanvas, "w");
		_canvasHeight = ReadOptionalFloat(referenceCanvas, "h");
		// Route A and the prebaked mockup share the full 1920x1080 reference canvas
		// (left-aligned 1440x1080 plate on black). World art must use that same plate,
		// not the cropped 800x374 source PNG stretched alone — that drifts building anchors.
		_backgroundWidth = _canvasWidth;
		_backgroundHeight = _canvasHeight;
		if (_canvasWidth <= 0f || _canvasHeight <= 0f || _backgroundWidth <= 0f || _backgroundHeight <= 0f)
			throw new InvalidOperationException(LogPrefix + PositionsFileName + " has invalid reference canvas.");
		var rows = ParseRequiredArrayToken(positions["layers"],
			PositionsFileName + " has no layers array.");
		var placements = new Dictionary<string, LayerPlacement>(StringComparer.Ordinal);
		for (var i = 0; i < rows.Count; i++)
		{
			var row = ParseRequiredObjectToken(rows[i],
				"positions layer row " + i + " is not an object.");
			var id = ReadOptionalString(row, "id");
			if (string.IsNullOrWhiteSpace(id) || placements.ContainsKey(id))
				throw new InvalidOperationException(LogPrefix + "invalid or duplicate positions layer id at row " + i + ".");
			var width = ReadOptionalFloat(row, "reference_w");
			var height = ReadOptionalFloat(row, "reference_h");
			if (width <= 0f || height <= 0f)
				throw new InvalidOperationException(LogPrefix + "layer '" + id + "' has no prebaked reference rect.");
			var spriteFile = ReadOptionalString(row, "sprite");
			if (string.IsNullOrWhiteSpace(spriteFile))
				spriteFile = id + ".png";
			if (!spriteFile.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
				throw new InvalidOperationException(LogPrefix + "layer '" + id
					+ "' sprite must be a .png file name, got '" + spriteFile + "'.");
			placements[id] = new LayerPlacement(id, spriteFile,
				ReadOptionalString(row, "structure") ?? string.Empty,
				ReadOptionalFloat(row, "reference_x"), ReadOptionalFloat(row, "reference_y"),
				width, height, ReadOptionalInt(row, "z"), ReadOptionalInt(row, "order"), i);
		}
		_levelsBySid = levelsBySid;
		_placementsById = placements;
		_loadedFractionSid = fraction;
	}

	private static JObject ParseRequiredObjectToken(JToken token, string error)
	{
		if (token == null || token.Type != JTokenType.Object)
			throw new InvalidOperationException(LogPrefix + error);
		return JObject.Parse(token.ToString());
	}

	private static JArray ParseRequiredArrayToken(JToken token, string error)
	{
		if (token == null || token.Type != JTokenType.Array)
			throw new InvalidOperationException(LogPrefix + error);
		return JArray.Parse(token.ToString());
	}

	/// <summary>
	/// Proxy-safe scalar read. Do not call <c>JToken.Value&lt;T&gt;</c> under IL2CPP Newtonsoft
	/// (live-negative TypeInitializationException / NRE on MethodInfoStoreGeneric_Value_*).
	/// </summary>
	private static string ReadOptionalString(JToken parent, string property)
	{
		if (parent == null || string.IsNullOrEmpty(property))
			return null;
		var token = parent[property];
		if (token == null || token.Type == JTokenType.Null)
			return null;
		var text = token.ToString();
		return string.IsNullOrWhiteSpace(text) ? null : text;
	}

	private static float ReadOptionalFloat(JToken parent, string property)
	{
		var text = ReadOptionalString(parent, property);
		if (string.IsNullOrEmpty(text))
			return 0f;
		return Homm3JsonNumber.TryParseFloat(text, out var value)
			? value
			: 0f;
	}

	private static int ReadOptionalInt(JToken parent, string property)
	{
		var text = ReadOptionalString(parent, property);
		if (string.IsNullOrEmpty(text))
			return 0;
		return int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
			? value
			: 0;
	}
	private static bool TryResolveExactLayerId(string sid, int level, out string layerId)
	{
		layerId = null;
		if (_levelsBySid == null || !_levelsBySid.TryGetValue(sid, out var levels) || levels == null)
			return false;
		if (levels.TryGetValue(level, out layerId) && !string.IsNullOrWhiteSpace(layerId))
			return true;
		// nativeLevels is Castle-parity clipped; native BhBuilding level may exceed mapped art.
		var best = 0;
		string bestId = null;
		foreach (var pair in levels)
		{
			if (pair.Key > level || pair.Key < best || string.IsNullOrWhiteSpace(pair.Value))
				continue;
			best = pair.Key;
			bestId = pair.Value;
		}
		if (best <= 0 || bestId == null)
			return false;
		layerId = bestId;
		return true;
	}

	private static Camera FindFactoryMainCamera(Scene scene)
	{
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null || !string.Equals(root.name, "CityCamera", StringComparison.Ordinal))
				continue;
			var main = root.transform.Find("MainCamera");
			if (main != null)
			{
				var camera = main.GetComponent<Camera>();
				if (camera != null)
					return camera;
			}

			return root.GetComponentInChildren<Camera>(true);
		}

		return null;
	}

	private static void HideDonorPresentation(Scene scene)
	{
		if (_donorHidden)
			return;
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null || IsOwnedArtObject(root))
				continue;
			DisableRenderersUnder(root.transform);
			// Narrow Terrain disable — do not scan every Component under the city graph.
			var behaviours = root.GetComponentsInChildren<Behaviour>(true);
			for (var c = 0; behaviours != null && c < behaviours.Length; c++)
			{
				var behaviour = behaviours[c];
				if (behaviour == null || behaviour.gameObject == null || IsOwnedArtObject(behaviour.gameObject))
					continue;
				var il2CppType = behaviour.GetIl2CppType();
				if (il2CppType == null || !string.Equals(il2CppType.FullName, "UnityEngine.Terrain", StringComparison.Ordinal))
					continue;
				if (!OriginalTerrainStates.ContainsKey(behaviour))
					OriginalTerrainStates[behaviour] = behaviour.enabled;
				behaviour.enabled = false;
			}
		}
		_donorHidden = true;
	}

	private static void DisableRenderersUnder(Transform root)
	{
		var renderers = root?.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; renderers != null && i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (renderer == null || renderer.gameObject == null || IsOwnedArtObject(renderer.gameObject))
				continue;
			if (!OriginalRendererStates.ContainsKey(renderer))
				OriginalRendererStates[renderer] = renderer.enabled;
			renderer.enabled = false;
		}
	}
	private static bool IsOwnedArtObject(GameObject go)
	{
		if (go == null)
			return false;
		var cursor = go.transform;
		while (cursor != null)
		{
			if (string.Equals(cursor.name, ArtChildName, StringComparison.Ordinal)
				|| (cursor.name != null && cursor.name.StartsWith(TownMeshChildPrefix, StringComparison.Ordinal))
				|| string.Equals(cursor.name, PlateRootName, StringComparison.Ordinal)
				|| string.Equals(cursor.name, BackdropRootName, StringComparison.Ordinal)
				|| Homm3TownScene3d.IsOwnedName(cursor.name)
				|| cursor.name.StartsWith(DecorChildPrefix, StringComparison.Ordinal))
				return true;
			cursor = cursor.parent;
		}

		return false;
	}

	private static GameObject EnsureArtQuadOnBuilding(
		string fraction, GameObject building, Texture2D texture, LayerPlacement placement, string layerId,
		Camera camera)
	{
		var child = building.transform.Find(ArtChildName);
		var art = child != null ? child.gameObject : CreateQuad(ArtChildName);
		if (child == null)
			SceneManager.MoveGameObjectToScene(art, building.scene);

		PlaceBuildingArtQuad(building.transform, art.transform, placement, camera);

		var stray = art.GetComponent<UnityEngine.Collider>();
		if (stray != null)
			UnityEngine.Object.Destroy(stray);
		var renderer = art.GetComponent<MeshRenderer>();
		renderer.enabled = true;
		var material = MaterialFor(texture);
		renderer.sharedMaterial = material;
		renderer.sortingOrder = 100 + placement.SortIndex;
		Homm3FactoryCityWorldAnimDriver.TryAttach(art, renderer, fraction, layerId, material);
		return art;
	}

	/// <summary>
	/// Camera-track path for already-composed towns: move existing HotA quads without PNG reload.
	/// Fail closed if the signature gate claimed art is present but the child is missing.
	/// </summary>
	private static void RepositionExistingBuildingArtOrThrow(
		GameObject building, LayerPlacement placement, Camera camera)
	{
		if (building == null)
			throw new InvalidOperationException(LogPrefix + "cannot reposition art on a null BhBuilding.");
		var child = building.transform.Find(ArtChildName);
		if (child == null)
			throw new InvalidOperationException(LogPrefix + "BhBuilding '" + building.name
				+ "' is missing " + ArtChildName + " during camera reposition; refusing silent drift.");
		PlaceBuildingArtQuad(building.transform, child, placement, camera);
		TryAlignNativeColliderWithArt(building, child.gameObject);
	}

	private static void PlaceBuildingArtQuad(
		Transform building, Transform art, LayerPlacement placement, Camera camera)
	{
		if (building == null || art == null || placement == null || camera == null)
			throw new InvalidOperationException(LogPrefix + "cannot place building art with a null argument.");
		// Always place while unparented so building rotation cannot shear the sprite, then reparent.
		art.SetParent(null, worldPositionStays: true);
		ApplyQuadMesh(art.gameObject, mirrorX: true);
		PositionReferenceQuad(
			art,
			placement.ReferenceX,
			placement.ReferenceY,
			placement.ReferenceWidth,
			placement.ReferenceHeight,
			QuadDistance(placement),
			camera,
			mirrorX: true);
		// Native Construct SpawnEffect uses BhBuilding.transform.position (Castle donor). Move the
		// building to the HotA art center so rock/debris FX and construction fade plane match art.
		AnchorBuildingTransformToArt(building, art);
		art.SetParent(building, worldPositionStays: true);
	}

	/// <summary>
	/// Camera distance of a HotA quad. In a scene-3D fraction every 2D layer sits at its own painted depth
	/// (catalog layerDepths) so it sorts against the meshes as the painting does; otherwise near the backdrop.
	/// </summary>
	private static float QuadDistance(LayerPlacement placement)
	{
		var fraction = _loadedFractionSid;
		if (!string.IsNullOrEmpty(fraction) && Homm3TownScene3d.IsActiveFor(fraction))
			return Homm3TownScene3d.LayerQuadDistanceOrThrow(fraction, placement.Id) - placement.SortIndex * 0.001f;
		return BackdropDistance - LayerDistanceFromBackdrop - placement.SortIndex * 0.001f;
	}

	private static GameObject EnsureScene3dLayerOnBuilding(
		string fraction, GameObject building, GameObject root, string layerId, Material donor)
	{
		if (building == null || root == null)
			throw new InvalidOperationException(LogPrefix + "cannot apply scene-3D layer with a null argument.");
		var instance = Homm3TownScene3d.EnsureLayer(root, fraction, layerId, donor,
			MaterialFor, TownMeshChildPrefix + layerId);
		AnchorBuildingToScene3dBody(building.transform, instance);
		return instance;
	}

	/// <summary>Camera moved: the root followed it; re-anchor the building and its collider to the body.</summary>
	private static void RepositionScene3dLayerOrThrow(GameObject building, GameObject root, string layerId)
	{
		if (building == null || root == null)
			throw new InvalidOperationException(LogPrefix + "cannot reposition scene-3D layer with a null argument.");
		var instance = root.transform.Find(TownMeshChildPrefix + layerId);
		if (instance == null)
			throw new InvalidOperationException(LogPrefix + "scene-3D root is missing layer '" + layerId
				+ "' during camera reposition; refusing silent drift.");
		AnchorBuildingToScene3dBody(building.transform, instance.gameObject);
		Homm3TownScene3dPick.ReposeOrThrow(building.transform, root.transform, Homm3TownScene3d.BodyOf(instance.gameObject));
	}

	/// <summary>
	/// Scene-3D pick (Homm3TownScene3dPick): the drawn body meshes become the hit geometry. The native BoxColliders
	/// are disabled (snapshotted, restored on clear); a variant that ships none stays non-interactive, as in vanilla,
	/// but its mesh still occludes the buildings behind it.
	/// </summary>
	private static void ApplyScene3dPickOrThrow(GameObject building, GameObject root, GameObject instance, string layerId)
	{
		var interactive = CollectNativeBuildingBoxColliders(building).Count > 0;
		DisableNativeBuildingCollidersIfPresent(building);
		var body = Homm3TownScene3d.BodyOf(instance);
		var count = Homm3TownScene3dPick.BuildOrThrow(building.transform, root.transform, body, interactive);
		Plugin.LogSource?.LogInfo(LogPrefix + "scene-3D pick '" + layerId + "' on '" + building.name + "': "
			+ count + " MeshCollider(s), " + (interactive ? "interactive" : "occluder only (no native BoxCollider)") + ".");
	}

	/// <summary>SpawnEffect / construction FX follow BhBuilding.position: put it at the mesh body's centre.</summary>
	private static void AnchorBuildingToScene3dBody(Transform building, GameObject instance)
	{
		var body = Homm3TownScene3d.BodyOf(instance);
		var renderers = body != null ? body.GetComponentsInChildren<Renderer>(true) : null;
		if (renderers == null || renderers.Length == 0)
			throw new InvalidOperationException(LogPrefix + "scene-3D layer '" + instance.name + "' has no body renderer.");
		var bounds = renderers[0].bounds;
		for (var i = 1; i < renderers.Length; i++)
			bounds.Encapsulate(renderers[i].bounds);
		building.position = bounds.center;
	}

	private static void AnchorBuildingTransformToArt(Transform building, Transform art)
	{
		if (building == null || art == null)
			throw new InvalidOperationException(LogPrefix + "cannot anchor BhBuilding without art.");
		// Position only: SpawnEffect uses transform.position (+ world-up * buildingBaseOffset).
		// Keep donor rotation so temporary particle parenting is not camera-sheared.
		building.position = art.position;
	}

	private static GameObject CreateQuad(string name)
	{
		var go = new GameObject(name);
		go.AddComponent<MeshFilter>().sharedMesh = SharedUnitQuadMesh(mirrorX: false);
		go.AddComponent<MeshRenderer>();
		return go;
	}

	private static void ApplyQuadMesh(GameObject go, bool mirrorX)
	{
		var filter = go.GetComponent<MeshFilter>() ?? go.AddComponent<MeshFilter>();
		filter.sharedMesh = SharedUnitQuadMesh(mirrorX);
	}

	private static void PositionReferenceQuad(
		Transform quad, float x, float y, float width, float height, float distance, Camera camera,
		bool mirrorX = false)
	{
		var frustumHeight = camera.orthographic
			? camera.orthographicSize * 2f
			: 2f * distance * Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
		var frustumWidth = frustumHeight * camera.aspect;
		var centerX = (x + width * 0.5f) / _canvasWidth - 0.5f;
		var centerY = 0.5f - (y + height * 0.5f) / _canvasHeight;
		var cam = camera.transform;
		quad.position = cam.position + cam.forward * distance
			+ cam.right * (centerX * frustumWidth) + cam.up * (centerY * frustumHeight);
		// Camera-parallel plane: avoids keystone/"askew screen" from spherical billboards.
		// Negated forward so the quad faces the camera (positive Z toward viewer).
		quad.rotation = Quaternion.LookRotation(-cam.forward, cam.up);
		var parentScale = quad.parent != null ? quad.parent.lossyScale : Vector3.one;
		var scaleX = SafeScale(width / _canvasWidth * frustumWidth, parentScale.x);
		var scaleY = SafeScale(height / _canvasHeight * frustumHeight, parentScale.y);
		var scaleZ = SafeScale(1f, parentScale.z);
		// Mirror via UV mesh (ApplyQuadMesh), not negative localScale — negative X breaks
		// child overlay depth and can skew anchors after reparent under IL2CPP.
		if (mirrorX)
			ApplyQuadMesh(quad.gameObject, mirrorX: true);
		quad.localScale = new Vector3(scaleX, scaleY, scaleZ);
	}

	private static float SafeScale(float worldSize, float parentScale)
	{
		var scale = Mathf.Abs(parentScale);
		return worldSize / (scale < 0.0001f ? 1f : scale);
	}

	private static Mesh _unitQuad;
	private static Mesh _unitQuadMirrored;

	private static Mesh SharedUnitQuadMesh(bool mirrorX)
	{
		if (!mirrorX)
		{
			if (_unitQuad != null)
				return _unitQuad;
			_unitQuad = BuildUnitQuadMesh("OfflineUnlockFactoryUnitQuad", mirrorU: false);
			return _unitQuad;
		}

		if (_unitQuadMirrored != null)
			return _unitQuadMirrored;
		_unitQuadMirrored = BuildUnitQuadMesh("OfflineUnlockFactoryUnitQuadMirrored", mirrorU: true);
		return _unitQuadMirrored;
	}

	private static Mesh BuildUnitQuadMesh(string name, bool mirrorU)
	{
		var mesh = new Mesh
		{
			name = name,
			vertices = new[]
			{
				new Vector3(-0.5f, -0.5f, 0f),
				new Vector3(0.5f, -0.5f, 0f),
				new Vector3(-0.5f, 0.5f, 0f),
				new Vector3(0.5f, 0.5f, 0f)
			},
			uv = mirrorU
				? new[]
				{
					new Vector2(1f, 0f),
					new Vector2(0f, 0f),
					new Vector2(1f, 1f),
					new Vector2(0f, 1f)
				}
				: new[]
				{
					new Vector2(0f, 0f),
					new Vector2(1f, 0f),
					new Vector2(0f, 1f),
					new Vector2(1f, 1f)
				},
			triangles = new[] { 0, 2, 1, 2, 3, 1 }
		};
		mesh.RecalculateBounds();
		mesh.RecalculateNormals();
		return mesh;
	}

	private static void DisableNativeBuildingCollidersIfPresent(GameObject building)
	{
		var colliders = CollectNativeBuildingBoxColliders(building);
		for (var i = 0; i < colliders.Count; i++)
		{
			var collider = colliders[i];
			SnapshotCollider(collider);
			collider.enabled = false;
		}
	}

	/// <summary>
	/// Aligns a native BoxCollider to HotA art when one exists. cityHuman2 Walls (live-positive
	/// walls_level_1) and some cumulative lower variants ship with no BoxCollider — shared by every
	/// owned cityFactory faction. Paint art anyway and never invent a parallel click owner.
	/// </summary>
	private static void TryAlignNativeColliderWithArt(GameObject building, GameObject art)
	{
		var colliders = CollectNativeBuildingBoxColliders(building);
		if (colliders.Count == 0)
			return;
		if (art == null)
			throw new InvalidOperationException(LogPrefix + "Factory art is null.");
		var hasMeshRenderer = art.GetComponentInChildren<MeshRenderer>(true) != null;
		if (!hasMeshRenderer)
			throw new InvalidOperationException(LogPrefix + "Factory art has no MeshRenderer.");
		for (var i = 0; i < colliders.Count; i++)
		{
			var collider = colliders[i];
			SnapshotCollider(collider);
			if (i > 0)
			{
				collider.enabled = false;
				continue;
			}
			Bounds localBounds;
			if (art.name != null && art.name.StartsWith(TownMeshChildPrefix, StringComparison.Ordinal))
				localBounds = CalculateMeshBoundsInColliderSpace(art.transform, collider.transform);
			else
				localBounds = CalculateArtBoundsInColliderSpace(art.transform, collider.transform);
			var size = localBounds.size;
			size.z = Mathf.Max(size.z, SafeScale(0.35f, collider.transform.lossyScale.z));
			collider.enabled = true;
			collider.center = localBounds.center;
			collider.size = size;
		}
	}

	private static Bounds CalculateMeshBoundsInColliderSpace(Transform art, Transform collider)
	{
		var renderers = art.GetComponentsInChildren<Renderer>(true);
		if (renderers == null || renderers.Length == 0)
			throw new InvalidOperationException(LogPrefix + "town mesh has no Renderer bounds.");
		var world = renderers[0].bounds;
		for (var i = 1; i < renderers.Length; i++)
		{
			if (renderers[i])
				world.Encapsulate(renderers[i].bounds);
		}
		var corners = new[]
		{
			new Vector3(world.min.x, world.min.y, world.min.z),
			new Vector3(world.max.x, world.min.y, world.min.z),
			new Vector3(world.min.x, world.max.y, world.min.z),
			new Vector3(world.max.x, world.max.y, world.min.z),
			new Vector3(world.min.x, world.min.y, world.max.z),
			new Vector3(world.max.x, world.min.y, world.max.z),
			new Vector3(world.min.x, world.max.y, world.max.z),
			new Vector3(world.max.x, world.max.y, world.max.z)
		};
		var local = collider.InverseTransformPoint(corners[0]);
		var bounds = new Bounds(local, Vector3.zero);
		for (var i = 1; i < corners.Length; i++)
			bounds.Encapsulate(collider.InverseTransformPoint(corners[i]));
		return bounds;
	}

	private static Bounds CalculateArtBoundsInColliderSpace(Transform art, Transform collider)
	{
		var corners = new[]
		{
			new Vector3(-0.5f, -0.5f, 0f),
			new Vector3(0.5f, -0.5f, 0f),
			new Vector3(-0.5f, 0.5f, 0f),
			new Vector3(0.5f, 0.5f, 0f)
		};
		var local = collider.InverseTransformPoint(art.TransformPoint(corners[0]));
		var bounds = new Bounds(local, Vector3.zero);
		for (var i = 1; i < corners.Length; i++)
			bounds.Encapsulate(collider.InverseTransformPoint(art.TransformPoint(corners[i])));
		return bounds;
	}

	private static void SnapshotCollider(BoxCollider collider)
	{
		if (!OriginalColliderStates.ContainsKey(collider))
			OriginalColliderStates[collider] = new BoxColliderState(
				collider.enabled, collider.center, collider.size);
	}

	private static List<BoxCollider> CollectNativeBuildingBoxColliders(GameObject building)
	{
		var result = new List<BoxCollider>();
		var colliders = building.GetComponentsInChildren<BoxCollider>(true);
		for (var i = 0; colliders != null && i < colliders.Length; i++)
		{
			var collider = colliders[i];
			if (collider == null || collider.gameObject == null || IsOwnedArtObject(collider.gameObject))
				continue;
			if (collider.gameObject == building)
				result.Insert(0, collider);
			else
				result.Add(collider);
		}
		return result;
	}

	private static string ResolveBackdropMockRelativePath(string fraction)
	{
		// Prefer the 4K outpainted plate when present; otherwise keep the 1920 mock.
		var upscaledName = fraction + UpscaledBackgroundFileSuffix;
		var mockName = fraction + MockBackgroundFileSuffix;
		var upscaledRelative = Path.Combine(
			"homm3_runtime_assets",
			"town_scene_refs",
			fraction,
			"mockups",
			upscaledName);
		var upscaledPath = ResolvePluginAssetPath(upscaledRelative);
		if (upscaledPath != null && File.Exists(upscaledPath))
			return upscaledRelative;
		return Path.Combine(
			"homm3_runtime_assets",
			"town_scene_refs",
			fraction,
			"mockups",
			mockName);
	}

	private static void ValidatePresentationAssetsOrThrow(string fraction)
	{
		var relative = ResolveBackdropMockRelativePath(fraction);
		var path = ResolvePluginAssetPath(relative);
		var backdrop = path != null && File.Exists(path) ? LoadTextureAtPath(path) : null;
		if (backdrop == null)
			throw new InvalidOperationException(LogPrefix + "missing or invalid " + relative);
		MaterialFor(backdrop);
		// Decorations load on demand in EnsureDecorationLayers — do not preload every anim/static
		// decoration texture during town open (live-negative long load).
	}

	private static GameObject EnsureWorldPlate(Scene scene, Camera camera, bool hidden)
	{
		GameObject plate = null;
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			if (roots[i] != null && string.Equals(roots[i].name, PlateRootName, StringComparison.Ordinal))
			{
				plate = roots[i];
				break;
			}
		}
		if (plate == null)
		{
			plate = CreateQuad(PlateRootName);
			SceneManager.MoveGameObjectToScene(plate, scene);
		}
		var renderer = plate.GetComponent<MeshRenderer>();
		renderer.enabled = !hidden;
		renderer.sharedMaterial = MaterialFor(Texture2D.blackTexture);
		renderer.sortingOrder = -100;
		PositionReferenceQuad(plate.transform, 0f, 0f, _canvasWidth, _canvasHeight,
			BackdropDistance + PlateDistanceBehindBackdrop, camera);
		return plate;
	}
	private static GameObject EnsureWorldBackdrop(string fraction, Scene scene, Camera camera, bool hidden)
	{
		GameObject backdrop = null;
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			if (roots[i] != null && string.Equals(roots[i].name, BackdropRootName, StringComparison.Ordinal))
			{
				backdrop = roots[i];
				break;
			}
		}
		if (backdrop == null)
		{
			backdrop = CreateQuad(BackdropRootName);
			SceneManager.MoveGameObjectToScene(backdrop, scene);
		}
		ApplyQuadMesh(backdrop, mirrorX: true);
		var renderer = backdrop.GetComponent<MeshRenderer>();
		if (hidden)
		{
			// Full-3D: the environment prefab replaces the painting; no backdrop texture is loaded or drawn.
			renderer.enabled = false;
		}
		else
		{
			var relative = ResolveBackdropMockRelativePath(fraction);
			var path = ResolvePluginAssetPath(relative);
			if (path == null || !File.Exists(path))
				throw new InvalidOperationException(LogPrefix + "missing " + relative);
			var texture = LoadTextureAtPath(path)
				?? throw new InvalidOperationException(LogPrefix + "failed to decode owned-city backdrop mock for '"
					+ fraction + "'.");
			renderer.enabled = true;
			renderer.sharedMaterial = MaterialFor(texture);
		}
		renderer.sortingOrder = 0;
		// Same camera-facing UV mirror as buildings — HotA mock art reads backwards on a
		// LookRotation(-cam.forward) quad without it.
		PositionReferenceQuad(backdrop.transform, 0f, 0f, _backgroundWidth, _backgroundHeight,
			BackdropDistance, camera, mirrorX: true);
		return backdrop;
	}

	private static void EnsureDecorationLayers(string fraction, GameObject backdrop, Camera camera)
	{
		foreach (var pair in _placementsById)
		{
			var placement = pair.Value;
			if (!placement.Structure.StartsWith("decoration", StringComparison.OrdinalIgnoreCase))
				continue;
			var name = DecorChildPrefix + placement.Id;
			var child = backdrop.transform.Find(name);
			var art = child != null ? child.gameObject : CreateQuad(name);
			art.transform.SetParent(null, worldPositionStays: true);
			ApplyQuadMesh(art, mirrorX: true);
			var renderer = art.GetComponent<MeshRenderer>();
			renderer.enabled = true;
			renderer.sharedMaterial = MaterialFor(LoadLayerTextureOrThrow(fraction, placement.SpriteFile));
			renderer.sortingOrder = 100 + placement.SortIndex;
			PositionReferenceQuad(art.transform, placement.ReferenceX, placement.ReferenceY,
				placement.ReferenceWidth, placement.ReferenceHeight,
				QuadDistance(placement), camera,
				mirrorX: true);
			art.transform.SetParent(backdrop.transform, worldPositionStays: true);
			Homm3FactoryCityWorldAnimDriver.TryAttach(art, renderer, fraction, placement.Id,
				renderer.sharedMaterial);
		}
	}

	private static void RemoveBuildingArtChild(GameObject building)
	{
		var child = building?.transform.Find(ArtChildName);
		if (child != null)
			UnityEngine.Object.Destroy(child.gameObject);
	}

	private static void RemoveTownSceneMeshChild(GameObject building)
	{
		if (building == null)
			return;
		var t = building.transform;
		for (var i = t.childCount - 1; i >= 0; i--)
		{
			var child = t.GetChild(i);
			if (child != null && child.name != null
			    && child.name.StartsWith(TownMeshChildPrefix, StringComparison.Ordinal))
				UnityEngine.Object.Destroy(child.gameObject);
		}
	}

	private static Material CaptureCityDonorMaterialOrThrow(Scene scene)
	{
		if (_cachedCityDonorMaterial != null && _cachedCityDonorMaterial.shader != null)
			return _cachedCityDonorMaterial;
		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null || IsOwnedArtObject(root))
				continue;
			var renderers = root.GetComponentsInChildren<Renderer>(true);
			for (var r = 0; renderers != null && r < renderers.Length; r++)
			{
				var renderer = renderers[r];
				if (renderer == null || IsOwnedArtObject(renderer.gameObject))
					continue;
				var mats = renderer.sharedMaterials;
				for (var m = 0; mats != null && m < mats.Length; m++)
				{
					var mat = mats[m];
					if (mat == null || mat.shader == null)
						continue;
					var shaderName = mat.shader.name ?? string.Empty;
					if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0
					    && shaderName.IndexOf("Hex\\Lit", StringComparison.OrdinalIgnoreCase) < 0)
						continue;
					_cachedCityDonorMaterial = mat;
					return mat;
				}
			}
		}
		throw new InvalidOperationException(
			LogPrefix + "no Hex/Lit city donor material found before HideDonorPresentation; "
			+ "refuse town-scene mesh apply (would shade black or silently use Sprites/Default).");
	}

	private static GameObject EnsureTownSceneMeshOnBuilding(
		GameObject building,
		LayerPlacement placement,
		string layerId,
		Camera camera,
		Material cityDonorMaterial)
	{
		if (building == null || placement == null || camera == null)
			throw new InvalidOperationException(LogPrefix + "cannot apply town mesh with a null argument.");
		if (!Homm3TownSceneMeshBundle.TryLoadPrefab(layerId, out var prefab, out var entry, Plugin.LogSource)
		    || !prefab)
		{
			throw new InvalidOperationException(
				LogPrefix + "town-scene mesh prefab load failed for layer '"
				+ layerId
				+ "' (homm3TownSceneMeshes on — no HotA quad fallback for catalog hit).");
		}

		RemoveTownSceneMeshChild(building);
		var meshName = TownMeshChildPrefix + layerId;
		var instance = UnityEngine.Object.Instantiate(prefab, building.transform, false);
		instance.name = meshName;

		Homm3TownSceneMeshBundle.SeatAtTownStage(
			instance,
			placement.ReferenceX,
			placement.ReferenceY,
			placement.ReferenceWidth,
			placement.ReferenceHeight,
			_canvasWidth,
			_canvasHeight,
			BackdropDistance,
			entry.StageDepthFromBackdrop,
			camera,
			Homm3TownSceneMeshBundle.DefaultFrontYawDegrees,
			Plugin.LogSource);

		if (!Homm3TownSceneMeshBundle.TryRebindRenderersToCityDonor(instance, cityDonorMaterial, Plugin.LogSource))
		{
			UnityEngine.Object.Destroy(instance);
			throw new InvalidOperationException(
				LogPrefix + "town-scene mesh material rebind failed for layer '" + layerId + "'.");
		}

		// Keep SpawnEffect / construction FX centered on the presentation.
		AnchorBuildingTransformToArt(building.transform, instance.transform);
		instance.transform.SetParent(building.transform, worldPositionStays: true);
		Plugin.LogSource?.LogInfo(
			LogPrefix + "applied town-scene mesh layer='" + layerId + "' prefab='" + entry.PrefabKey + "'.");
		return instance;
	}

	private static void RepositionExistingTownSceneMeshOrThrow(
		GameObject building, LayerPlacement placement, string layerId, Camera camera)
	{
		if (building == null)
			throw new InvalidOperationException(LogPrefix + "cannot reposition town mesh on a null BhBuilding.");
		Transform child = null;
		var expected = TownMeshChildPrefix + layerId;
		for (var i = 0; i < building.transform.childCount; i++)
		{
			var c = building.transform.GetChild(i);
			if (c != null && string.Equals(c.name, expected, StringComparison.Ordinal))
			{
				child = c;
				break;
			}
		}
		if (child == null)
			throw new InvalidOperationException(LogPrefix + "BhBuilding '" + building.name
				+ "' is missing " + expected + " during camera reposition; refusing silent drift.");
		if (!Homm3TownSceneMeshBundle.TryGetEntryForLayer(layerId, out var entry))
			throw new InvalidOperationException(LogPrefix + "catalog missing for layer '" + layerId + "'.");
		Homm3TownSceneMeshBundle.SeatAtTownStage(
			child.gameObject,
			placement.ReferenceX,
			placement.ReferenceY,
			placement.ReferenceWidth,
			placement.ReferenceHeight,
			_canvasWidth,
			_canvasHeight,
			BackdropDistance,
			entry.StageDepthFromBackdrop,
			camera,
			Homm3TownSceneMeshBundle.DefaultFrontYawDegrees,
			Plugin.LogSource);
		AnchorBuildingTransformToArt(building.transform, child);
		child.SetParent(building.transform, worldPositionStays: true);
		TryAlignNativeColliderWithArt(building, child.gameObject);
	}

	private static void RemoveUntrackedBuildingArt()
	{
		for (var s = 0; s < SceneManager.sceneCount; s++)
		{
			var scene = SceneManager.GetSceneAt(s);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			var roots = scene.GetRootGameObjects();
			for (var r = 0; r < roots.Length; r++)
			{
				var buildings = roots[r]?.GetComponentsInChildren<BhBuilding>(true);
				for (var i = 0; buildings != null && i < buildings.Length; i++)
				{
					var building = buildings[i]?.gameObject;
					RemoveBuildingArtChild(building);
					RemoveTownSceneMeshChild(building);
				}
			}
		}
	}

	private static Material MaterialFor(Texture2D texture)
	{
		if (MaterialByTexture.TryGetValue(texture, out var material) && material != null)
			return material;
		if (_sharedUnlit == null)
		{
			// City-interior Factory art is flat HotA sprites. Golden Era has no Unlit/Transparent;
			// bare Hex/Lit materials shade black without a donor light setup. Sprites/Default is the
			// proven unlit textured path for this install.
			var shader = Shader.Find(PresentationShaderName);
			if (shader == null)
				throw new InvalidOperationException(LogPrefix + "required shader '"
					+ PresentationShaderName + "' is unavailable.");
			_sharedUnlit = new Material(shader) { name = "OfflineUnlockFactoryCityWorldPresentation" };
		}
		material = new Material(_sharedUnlit)
		{
			name = "OfflineUnlockFactoryCityWorldPresentation." + texture.name,
			mainTexture = texture
		};
		if (material.HasProperty("_MainTex"))
			material.SetTexture("_MainTex", texture);
		if (material.HasProperty("_Color"))
			material.color = Color.white;
		MaterialByTexture[texture] = material;
		return material;
	}
	private static Texture2D LoadLayerTextureOrThrow(string fraction, string spriteFile)
	{
		if (string.IsNullOrWhiteSpace(spriteFile))
			throw new InvalidOperationException(LogPrefix + "layer sprite file is empty.");
		// positions.json may remap id → sprite (Stronghold fort wall_1 → treasury.png;
		// Tower layers → *.dir.png). Never invent id.png when an explicit sprite is declared.
		var relative = Path.Combine(
			"homm3_runtime_assets",
			"town_scene_refs",
			fraction,
			"layers",
			spriteFile);
		var path = ResolvePluginAssetPath(relative);
		if (path == null || !File.Exists(path))
			throw new InvalidOperationException(LogPrefix + "missing layer texture " + relative);
		var texture = LoadTextureAtPath(path);
		if (texture == null)
			throw new InvalidOperationException(LogPrefix + "failed to decode layer texture " + relative);
		return texture;
	}

	private static Texture2D LoadTextureAtPath(string path)
	{
		var stamp = GetFileStamp(path);
		if (TextureCache.TryGetValue(path, out var cached)
			&& cached != null
			&& TextureStampByPath.TryGetValue(path, out var cachedStamp)
			&& string.Equals(cachedStamp, stamp, StringComparison.Ordinal))
			return cached;

		var bytes = File.ReadAllBytes(path);
		var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		texture.name = Path.GetFileNameWithoutExtension(path);
		if (!ImageConversion.LoadImage(texture, bytes, false))
		{
			UnityEngine.Object.Destroy(texture);
			return null;
		}

		texture.wrapMode = TextureWrapMode.Clamp;
		texture.filterMode = FilterMode.Bilinear;
		TextureCache[path] = texture;
		TextureStampByPath[path] = stamp;
		return texture;
	}

	private static string GetFileStamp(string path)
	{
		try
		{
			var info = new FileInfo(path);
			return info.Exists
				? info.Length.ToString(CultureInfo.InvariantCulture) + ":" + info.LastWriteTimeUtc.Ticks.ToString(CultureInfo.InvariantCulture)
				: "missing";
		}
		catch
		{
			return "error";
		}
	}

	private static string ResolvePluginAssetPath(string relativePath)
	{
		if (string.IsNullOrWhiteSpace(relativePath))
			return null;
		var underPlugin = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relativePath));
		if (File.Exists(underPlugin))
			return underPlugin;
		var underPluginRoot = Path.GetFullPath(Path.Combine(Paths.PluginPath, relativePath));
		if (File.Exists(underPluginRoot))
			return underPluginRoot;
		return null;
	}

	private sealed class ResolvedBuildingLayer
	{
		internal ResolvedBuildingLayer(string sceneSlot, List<BhBuilding> variants, BhBuilding highest,
			int level, string layerId, LayerPlacement placement, Texture2D texture)
		{
			SceneSlot = sceneSlot;
			Variants = variants;
			Highest = highest;
			Level = level;
			LayerId = layerId;
			Placement = placement;
			Texture = texture;
		}
		internal string SceneSlot { get; }
		internal List<BhBuilding> Variants { get; }
		internal BhBuilding Highest { get; }
		internal int Level { get; }
		internal string LayerId { get; }
		internal LayerPlacement Placement { get; }
		internal Texture2D Texture { get; }
	}

	private sealed class SkippedBuildingSlot
	{
		internal SkippedBuildingSlot(string sceneSlot, List<BhBuilding> variants, string reason)
		{
			SceneSlot = sceneSlot;
			Variants = variants;
			Reason = reason;
		}
		internal string SceneSlot { get; }
		internal List<BhBuilding> Variants { get; }
		internal string Reason { get; }
	}

	private sealed class LayerPlacement
	{
		internal LayerPlacement(string id, string spriteFile, string structure, float referenceX,
			float referenceY, float referenceWidth, float referenceHeight, int z, int order,
			int sortIndex)
		{
			Id = id;
			SpriteFile = spriteFile;
			Structure = structure;
			ReferenceX = referenceX;
			ReferenceY = referenceY;
			ReferenceWidth = referenceWidth;
			ReferenceHeight = referenceHeight;
			Z = z;
			Order = order;
			SortIndex = sortIndex;
		}
		internal string Id { get; }
		internal string SpriteFile { get; }
		internal string Structure { get; }
		internal float ReferenceX { get; }
		internal float ReferenceY { get; }
		internal float ReferenceWidth { get; }
		internal float ReferenceHeight { get; }
		internal int Z { get; }
		internal int Order { get; }
		internal int SortIndex { get; }
	}

	private readonly struct BoxColliderState
	{
		internal BoxColliderState(bool enabled, Vector3 center, Vector3 size)
		{
			Enabled = enabled;
			Center = center;
			Size = size;
		}
		internal bool Enabled { get; }
		internal Vector3 Center { get; }
		internal Vector3 Size { get; }
	}
}
