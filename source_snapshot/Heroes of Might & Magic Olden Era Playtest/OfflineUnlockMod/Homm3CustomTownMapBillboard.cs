using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Map;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

internal static class Homm3CustomTownMapBillboard
{
	private const string BillboardRootPrefix = "homm3_custom_city_billboard_";
	private const float BillboardLiftRatio = 0.5f;
	private const float BillboardGroundClearance = 0.08f;
	private const float BillboardSouthOffset = 0.22f;
	private const float BillboardDepthTowardCamera = 0.04f;
	private const float NativeTownDonorSiblingTolerance = 1.25f;
	// Land-on 3x3 ObjectConfig: placement root is SW; GATE is south-center (index 7).
	// HoMM3 town art is a full-town sprite with the entrance at the image bottom-center.
	// Anchoring the billboard on the GATE cell (SW+1 X) put the center-pivoted quad half
	// south of the entrance and made the gate read as a corner of the town mass.
	// Anchor on the footprint center (SW +1 X, +1 north) so the town body centers on the
	// 3x3 and the art's bottom entrance falls on the south-center GATE.
	private const float LandOnSouthCenterGateTileWorldSize = 1f;
	private const float LandOnFootprintCenterNorthTiles = 1f;
	// Nudge land-on HoMM3 sprites down so the art's bottom-center entrance meets the GATE cell.
	private const float LandOnBillboardLowerY = 0.18f;
	private const float StaleSectionBillboardMarkerCleanupRadius = 0.5f;
	private const int TextureBottomPaddingPixels = 96;
	private const string PropCityProbeFlagName = "homm3_town_billboard_prop_city_probe.flag";
	private const string PostLoadScannerFlagName = "homm3_town_billboard_post_load_scanner.flag";

	private static readonly Dictionary<string, BillboardAsset> Assets = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, Texture2D> TexturesByKey = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, TownBillboardPlacement> PlacementByLiveRootKey = new(StringComparer.Ordinal);
	private static readonly HashSet<string> AppliedLiveRootKeys = new(StringComparer.Ordinal);
	private static Mesh _quadMesh;
	private static bool _registered;
	private static int _loggedMissingImage;
	private static int _loggedApplied;
	private static int _loggedNoCitySid;
	private static int _loggedSeenSid;
	private static int _loggedRootMissing;
	private static int _loggedPlacedSid;
	private static int _loggedPropCityRouteMiss;
	private static int _loggedPropCityMemberSummary;
	private static int _loggedPropCityProbe;
	private static int _loggedRootCandidateProbe;
	private static int _materialDiagRemaining = 8;
	private static int _assetRefreshDiagRemaining = 8;
	private static int _deferredReapplyDiagRemaining = 12;
	private static int _postconditionDiagRemaining = 12;
	private static int _sectionFinalizerDiagRemaining = 12;
	private static int _entranceAnchorDiagRemaining = 12;
	private static int _donorAnchorMissDiagRemaining = 12;
	private static bool _postLoadScannerRegistered;
	private static bool _postLoadScannerAttached;
	private static bool _sectionFinalizerRegistered;

	internal static bool IsRegistered => _registered;

	internal static void TryRegisterReleaseSafeMapObjectSlice(Harmony harmony, ManualLogSource log)
	{
		RegisterReleaseSafeMapObjectSlice(harmony, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeMapObjectSlice(Harmony harmony, ManualLogSource log)
	{
		RegisterReleaseSafeMapObjectSlice(harmony, log, required: true);
	}

	private static void RegisterReleaseSafeMapObjectSlice(Harmony harmony, ManualLogSource log, bool required)
	{
		if (_registered || harmony == null)
		{
			if (required && harmony == null)
				throw new InvalidOperationException("Harmony was not initialized before required custom town billboard registration.");
			return;
		}

		try
		{
			var metaType = ResolveMapMetaType();
			var objectType = GameMember.FindPlacedObjectType(
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId,
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints,
				GetHexType);
			var initPatched = 0;
			foreach (var m in GameMember.FindPlacedObjectInitMethods(objectType, metaType))
			{
				harmony.Patch(
					m,
					postfix: new HarmonyMethod(typeof(Homm3CustomTownMapBillboard), nameof(PostfixReleaseMapObjectInit)));
				initPatched++;
			}

			var sidPatched = 0;
			foreach (var m in FindReleaseMapObjectSidHooks(objectType))
			{
				harmony.Patch(
					m,
					postfix: new HarmonyMethod(typeof(Homm3CustomTownMapBillboard), nameof(PostfixReleaseMapObjectSid)));
				sidPatched++;
			}
			if (initPatched == 0 && sidPatched == 0)
				throw new InvalidOperationException("no release map-object init or SID setter surfaces resolved.");

			_registered = true;
			EnsurePostLoadScanner(log);
			log?.LogInfo("HoMM3 custom town billboard release slice: registered map-object hooks (init=" + initPatched + ", sidSetters=" + sidPatched + ").");
		}
		catch (Exception ex)
		{
			if (required)
			{
				log?.LogFatal("HoMM3 custom town billboard release slice: required hook registration failed: " + ex);
				throw;
			}
			log?.LogWarning("HoMM3 custom town billboard release slice: hook registration failed: " + ex);
		}
	}

	/// <summary>
	/// Fail-closed path existence check only. Decode stays in <see cref="GetOrCreateTexture"/> on first map apply.
	/// </summary>
	internal static int ValidateManifestTexturePathsOrFail(ManualLogSource log)
	{
		var validated = 0;
		foreach (var citySid in Homm3CustomFactionRegistry.EnumerateCitySids())
		{
			if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(citySid, out var relativePath, out var billboardHeight))
				continue;
			if (string.IsNullOrWhiteSpace(relativePath) || billboardHeight <= 0f)
				throw new InvalidOperationException("Invalid HoMM3 city map billboard manifest contract for " + citySid + ".");
			if (!Homm3CustomFactionRegistry.TryGetStartupAssetPath(relativePath, out var path) || !File.Exists(path))
				throw new InvalidOperationException("Failed to validate HoMM3 custom town billboard texture path for " + citySid + ".");
			validated++;
		}
		log?.LogInfo("HoMM3 custom town billboard: validated " + validated + " texture path(s); decode deferred until map apply.");
		return validated;
	}

	internal static int PrewarmManifestTextures(ManualLogSource log)
	{
		return ValidateManifestTexturePathsOrFail(log);
	}

	private static void PostfixReleaseMapObjectInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;
			var meta = (__args != null && __args.Length > 1) ? __args[1] : null;
			meta ??= GetReleaseMapObjectMeta(__instance);
			var mapInstance = (__args != null && __args.Length > 0) ? __args[0] : null;
			int? nodeArg = (__args != null && __args.Length > 2 && __args[2] is int n) ? n : (int?)null;
			if (!TryGetPlacedObjectCityBillboard(__instance, out var citySid, out var relativePath, out var billboardHeight)
			    && !TryGetMetaCityBillboard(meta, out citySid, out relativePath, out billboardHeight)
			    && !TryGetRootNameCityBillboard(__instance, out citySid, out relativePath, out billboardHeight)
			    && !TryGetPropCityBillboard(__instance, meta, mapInstance, nodeArg, out citySid, out relativePath, out billboardHeight))
			{
				LogNoCitySid(__instance, meta);
				return;
			}
			var root = SelectReleaseMapObjectRoot(__instance, citySid, Plugin.LogSource);
			if (!root)
			{
				if (_loggedRootMissing < 20)
				{
					_loggedRootMissing++;
					Plugin.LogSource?.LogInfo("HoMM3 custom town billboard: matched custom city sid='" + citySid + "' but map-object root was not readable instanceType='" + (__instance.GetType().FullName ?? "?") + "'.");
				}
				return;
			}
			var placement = ResolveTownBillboardPlacement(__instance, __args, root, citySid);
			RememberTownBillboardPlacement(root, citySid, placement);
			if (HasAppliedLiveRoot(root, citySid))
			{
				EnsureAppliedBillboardSuppressesDonor(root, citySid);
				var suppressRoot = SelectBillboardVisualRoot(root, citySid, null);
				if (HasActiveBillboard(suppressRoot, citySid))
				{
					ApplyBillboardPrefab(root, citySid, relativePath, billboardHeight, placement, Plugin.LogSource);
					NoteCitySeen(citySid);
					return;
				}
			}
			if (!ApplyBillboardPrefab(root, citySid, relativePath, billboardHeight, placement, Plugin.LogSource))
				return;
			MarkAppliedLiveRoot(root, citySid);
			NoteCitySeen(citySid);
			if (_loggedApplied < 20)
			{
				_loggedApplied++;
				Plugin.LogSource?.LogInfo("HoMM3 custom town billboard: applied live billboard to " + citySid + " map object.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom town billboard: release MapObject.Init postfix failed: " + ex.Message);
		}
	}

	private static void PostfixReleaseMapObjectSid(object __instance, string __0)
	{
		try
		{
			if (__instance == null || string.IsNullOrWhiteSpace(__0))
				return;
			if (!TryResolveCityBillboardSid(__0, out var citySid, out var relativePath, out var billboardHeight))
				return;
			var root = SelectReleaseMapObjectRoot(__instance, citySid, Plugin.LogSource);
			if (!root)
				return;
			var placement = ResolveTownBillboardPlacement(__instance, null, root, citySid);
			RememberTownBillboardPlacement(root, citySid, placement);
			if (HasAppliedLiveRoot(root, citySid))
			{
				EnsureAppliedBillboardSuppressesDonor(root, citySid);
				var suppressRoot = SelectBillboardVisualRoot(root, citySid, null);
				if (HasActiveBillboard(suppressRoot, citySid))
				{
					ApplyBillboardPrefab(root, citySid, relativePath, billboardHeight, placement, Plugin.LogSource);
					NoteCitySeen(citySid);
					return;
				}
			}
			if (!ApplyBillboardPrefab(root, citySid, relativePath, billboardHeight, placement, Plugin.LogSource))
				return;
			MarkAppliedLiveRoot(root, citySid);
			NoteCitySeen(citySid);
			if (_loggedApplied < 20)
			{
				_loggedApplied++;
				Plugin.LogSource?.LogInfo("HoMM3 custom town billboard: applied " + citySid + " from placed-object sid setter.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom town billboard: release sid postfix failed: " + ex.Message);
		}
	}

	private static Type ResolveMapMetaType()
	{
		foreach (var hint in GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints)
		{
			var type = GameMember.FindType(
				GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId + "." + hint,
				hint,
				() => GetHexType(hint));
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type GetHexType(string name)
	{
		if (string.IsNullOrEmpty(name))
			return null;
		var asm = typeof(Hex.Configs.ObjCityConfig).Assembly;
		return asm.GetType(name) ?? asm.GetType("Hex.Map." + name);
	}

	private static MethodInfo[] FindReleaseMapObjectSidHooks(Type objectType)
	{
		if (objectType == null)
			return Array.Empty<MethodInfo>();
		var methods = GameMember.FindMethodsByNames(
			objectType,
			new[] { typeof(string) },
			GameSymbols.CustomTownMapBillboard.PlacedObjectSetSid);
		var list = new List<MethodInfo>();
		foreach (var method in methods)
		{
			if (method == null || method.IsSpecialName || method.Name.StartsWith("get_", StringComparison.Ordinal) || method.Name.StartsWith("set_", StringComparison.Ordinal))
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 1 || parameters[0].ParameterType != typeof(string))
				continue;
			list.Add(method);
		}
		return list.ToArray();
	}

	private static bool TryGetPlacedObjectCityBillboard(object instance, out string citySid, out string relativePath, out float billboardHeight)
	{
		citySid = null;
		relativePath = null;
		billboardHeight = 0f;
		if (!DeobfInteropCompat.TryGetPlacedMapObjectSid(instance, out var sid))
			sid = GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields) as string;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		if (_loggedPlacedSid < 40
		    && (sid.IndexOf("city", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("homm3", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("human", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("dungeon", StringComparison.OrdinalIgnoreCase) >= 0))
		{
			_loggedPlacedSid++;
			Plugin.LogSource?.LogInfo("HoMM3 custom town billboard: observed placed object sid='" + sid + "'.");
		}
		return TryResolveCityBillboardSid(sid, out citySid, out relativePath, out billboardHeight);
	}

	private static bool TryGetMetaCityBillboard(object meta, out string citySid, out string relativePath, out float billboardHeight)
	{
		citySid = null;
		relativePath = null;
		billboardHeight = 0f;
		if (meta == null)
			return false;

		if (meta is MapObjectInfo mapObjectInfo
		    && DeobfInteropCompat.TryGetMapObjectInfoSid(mapObjectInfo, out var infoSid)
		    && TryResolveCityBillboardSid(infoSid, out citySid, out relativePath, out billboardHeight))
			return true;

		var config = DeobfInteropCompat.TryGetMapObjectMetaConfig(meta, out var metaConfig) ? metaConfig : null;
		if (config == null)
			config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		if (config == null)
			return false;

		return TryGetConfigCityBillboard(config, out citySid, out relativePath, out billboardHeight);
	}

	private static bool TryGetRootNameCityBillboard(object placedInstance, out string citySid, out string relativePath, out float billboardHeight)
	{
		citySid = null;
		relativePath = null;
		billboardHeight = 0f;
		var rootName = TryGetPlacedObjectRootName(placedInstance);
		if (string.IsNullOrWhiteSpace(rootName))
			return false;

		// Source-validated June 26, 2026; runtime proof pending. Exact manifest city roots
		// such as homm3_castle_city can reach bvb.Init with rotation while sid/meta stay generic.
		return TryResolveCityBillboardSid(rootName, out citySid, out relativePath, out billboardHeight);
	}

	// Hotfix May 21, 2026: placed city objects can use generic "city-spawner" / "random-city"
	// ids on both bvb and bvd.ObjectConfig. Native bvb.Init resolves their PropCity through
	// ObjectsProperties by ObjectProp.EType.MapObject plus bvb.bvms; the init node arg is only
	// placement data and can identify the wrong donor city on reused/reloaded maps.
	private static bool TryGetPropCityBillboard(object placedInstance, object meta, object mapInstance, int? nodeArg, out string citySid, out string relativePath, out float billboardHeight)
	{
		citySid = null;
		relativePath = null;
		billboardHeight = 0f;

		var placedSid = DeobfInteropCompat.TryGetPlacedMapObjectSid(placedInstance, out var compatSid) ? compatSid
			: GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields) as string;
		var metaSid = GetMetaConfigSid(meta);
		var rootName = TryGetPlacedObjectRootName(placedInstance);
		var isGenericCityObject = IsGenericCityObjectSid(placedSid) || IsGenericCityObjectSid(metaSid) || IsGenericCityObjectSid(rootName);
		// ObjectId→PropCity alone can resolve a faction for scenery that reused an id slot
		// (logs: mountain_snow_small_1 painted as homm3_castle_city). Fail closed unless the
		// live root/SID is already city-shaped.
		if (!IsCityShapedBillboardHost(placedSid, metaSid, rootName))
		{
			LogPropCityRouteMiss("non-city-root", placedInstance, null, nodeArg);
			return false;
		}

		var map = mapInstance ?? GetFirstMemberValue(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectMapFields);
		if (map == null)
		{
			LogPropCityRouteMiss("no-map", placedInstance, null, nodeArg);
			return false;
		}

		var objectsProperties = Homm3MapObjectPropCityResolver.ResolveObjectsProperties(map);
		if (objectsProperties == null)
		{
			LogPropCityRouteMiss("no-objects-properties", placedInstance, map, nodeArg);
			LogPropCityMemberSummary("no-objects-properties", placedInstance, meta, map);
			return false;
		}

		var objectId = DeobfInteropCompat.GetIntMember(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields);
		if (objectId == 0)
			objectId = Homm3MapObjectPropCityResolver.TryGetIntMember(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields) ?? 0;
		var nodeId = nodeArg ?? Homm3MapObjectPropCityResolver.TryGetIntMember(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields);
		if (objectId == 0)
		{
			LogPropCityRouteMiss("no-object-id", placedInstance, objectsProperties, nodeId);
			ScheduleSectionRootFinalizer(placedInstance, "no-object-id", Plugin.LogSource);
			return false;
		}
		LogPropCityProbe(placedInstance, map, objectId, placedSid ?? metaSid ?? rootName, nodeId);

		if (!Homm3MapObjectPropCityResolver.TryGetMapObjectPropCityFaction(objectsProperties, objectId, out var factionSid))
		{
			var missReason = isGenericCityObject ? "no-custom-map-object-prop-city" : "not-generic-city-object-without-custom-propcity";
			LogPropCityRouteMiss(missReason, placedInstance, objectsProperties, nodeId);
			LogPropCityMemberSummary(missReason, placedInstance, meta, objectsProperties);
			ScheduleSectionRootFinalizer(placedInstance, missReason, Plugin.LogSource);
			return false;
		}

		var citySidCandidate = Homm3CustomFactionRegistry.GetCitySidForFaction(factionSid.Trim());
		if (string.IsNullOrWhiteSpace(citySidCandidate))
			return false;
		if (_loggedSeenSid < 40)
		{
			_loggedSeenSid++;
			Plugin.LogSource?.LogInfo("HoMM3 custom town billboard: resolved factionSid='" + factionSid + "' (object=" + objectId + ", node=" + (nodeId.HasValue ? nodeId.Value.ToString() : "?") + ") -> city='" + citySidCandidate + "' via PropCity.");
		}
		return TryResolveCityBillboardSid(citySidCandidate, out citySid, out relativePath, out billboardHeight);
	}

	private static void LogPropCityProbe(object placedInstance, object mapInstance, int objectId, string rawSid, int? nodeId)
	{
		if (_loggedPropCityProbe >= 20 || !Homm3DiagnosticFlags.IsEnabled(PropCityProbeFlagName))
			return;
		_loggedPropCityProbe++;
		try
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom town billboard PropCity probe: "
			                           + Homm3MapObjectPropCityResolver.DescribePlacedObjectPropCityProbe(placedInstance, mapInstance, objectId, rawSid, nodeId));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom town billboard PropCity probe failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void EnsurePostLoadScanner(ManualLogSource log)
	{
		if (_postLoadScannerAttached)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(PostLoadScannerFlagName))
			return;
		try
		{
			if (!_postLoadScannerRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3TownBillboardPostLoadScanner>();
				_postLoadScannerRegistered = true;
			}
			var go = new GameObject("Homm3TownBillboardPostLoadScanner");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3TownBillboardPostLoadScanner>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_postLoadScannerAttached = true;
			log?.LogInfo("HoMM3 custom town billboard diagnostic post-load scanner attached for exact manifest city roots.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard diagnostic post-load scanner attach failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static TownBillboardScanResult ReapplyLiveNamedCityRoots(ManualLogSource log)
	{
		var applied = 0;
		var foundCityRoots = 0;
		var unresolvedCityRoots = 0;
		try
		{
			var cityBillboards = new Dictionary<string, (string RelativePath, float BillboardHeight)>(StringComparer.OrdinalIgnoreCase);
			foreach (var citySid in Homm3CustomFactionRegistry.EnumerateCitySids())
			{
				if (string.IsNullOrWhiteSpace(citySid))
					continue;
				if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(citySid, out var relativePath, out var billboardHeight))
					continue;
				cityBillboards[citySid] = (relativePath, billboardHeight);
			}
			if (cityBillboards.Count == 0)
				return new TownBillboardScanResult(0, 0, 0);

			var roots = UnityEngine.Object.FindObjectsOfType<GameObject>(true);
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (!root)
					continue;
				var canonicalCitySid = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(root.name ?? string.Empty);
				if (!cityBillboards.TryGetValue(canonicalCitySid, out var billboard))
					continue;
				var citySid = canonicalCitySid;
				if (!IsLiveMapCityRoot(root, citySid))
					continue;
				foundCityRoots++;
				var suppressRoot = SelectBillboardVisualRoot(root, citySid, null);
				if (HasActiveBillboard(suppressRoot, citySid))
				{
					EnsureAppliedBillboardSuppressesDonor(root, citySid);
					continue;
				}
				var placement = ResolveTownBillboardPlacement(null, null, root, citySid);
				if (!ApplyBillboardPrefab(root, citySid, billboard.RelativePath, billboard.BillboardHeight, placement, log))
				{
					unresolvedCityRoots++;
					continue;
				}
				MarkAppliedLiveRoot(root, citySid);
				NoteCitySeen(citySid);
				applied++;
				if (_deferredReapplyDiagRemaining > 0)
				{
					_deferredReapplyDiagRemaining--;
					log?.LogInfo("HoMM3 custom town billboard post-load scanner: applied city='" + citySid + "' rootPath='" + DescribeTransformPath(root.transform) + "'.");
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard post-load scanner failed: " + ex.GetType().Name + ": " + ex.Message);
		}
		return new TownBillboardScanResult(applied, foundCityRoots, unresolvedCityRoots);
	}

	internal static TownBillboardScanResult ReapplyLiveNamedCityRootsUnder(GameObject sectionRoot, ManualLogSource log)
	{
		var applied = 0;
		var foundCityRoots = 0;
		var unresolvedCityRoots = 0;
		try
		{
			if (!sectionRoot || !sectionRoot.transform || !sectionRoot.activeInHierarchy)
				return new TownBillboardScanResult(0, 0, 0);
			var sectionName = sectionRoot.name ?? string.Empty;
			if (!sectionName.StartsWith("Section Root:", StringComparison.Ordinal))
				return new TownBillboardScanResult(0, 0, 0);

			var cityBillboards = new Dictionary<string, (string RelativePath, float BillboardHeight)>(StringComparer.OrdinalIgnoreCase);
			foreach (var citySid in Homm3CustomFactionRegistry.EnumerateCitySids())
			{
				if (string.IsNullOrWhiteSpace(citySid))
					continue;
				if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(citySid, out var relativePath, out var billboardHeight))
					continue;
				cityBillboards[citySid] = (relativePath, billboardHeight);
			}
			if (cityBillboards.Count == 0)
				return new TownBillboardScanResult(0, 0, 0);

			for (var i = 0; i < sectionRoot.transform.childCount; i++)
			{
				var child = sectionRoot.transform.GetChild(i);
				var root = child ? child.gameObject : null;
				if (!root)
					continue;
				var canonicalCitySid = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(root.name ?? string.Empty);
				if (!cityBillboards.TryGetValue(canonicalCitySid, out var billboard))
					continue;
				var citySid = canonicalCitySid;
				if (!IsLiveMapCityRoot(root, citySid))
					continue;
				foundCityRoots++;
				var suppressRoot = SelectBillboardVisualRoot(root, citySid, null);
				if (HasActiveBillboard(suppressRoot, citySid))
				{
					EnsureAppliedBillboardSuppressesDonor(root, citySid);
					continue;
				}
				var placement = ResolveTownBillboardPlacement(null, null, root, citySid);
				if (!ApplyBillboardPrefab(root, citySid, billboard.RelativePath, billboard.BillboardHeight, placement, log))
				{
					unresolvedCityRoots++;
					continue;
				}
				MarkAppliedLiveRoot(root, citySid);
				NoteCitySeen(citySid);
				applied++;
				if (_deferredReapplyDiagRemaining > 0)
				{
					_deferredReapplyDiagRemaining--;
					log?.LogInfo("HoMM3 custom town billboard section finalizer: applied city='" + citySid + "' rootPath='" + DescribeTransformPath(root.transform) + "'.");
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard section finalizer failed: " + ex.GetType().Name + ": " + ex.Message);
		}
		return new TownBillboardScanResult(applied, foundCityRoots, unresolvedCityRoots);
	}

	private static void ScheduleSectionRootFinalizer(object placedInstance, string reason, ManualLogSource log)
	{
		try
		{
			var root = GetReleaseMapObjectRoot(placedInstance);
			if (!root || !IsGenericCityObjectSid(root.name) || !root.transform || !root.transform.parent)
				return;
			var sectionRoot = root.transform.parent.gameObject;
			if (!sectionRoot || !sectionRoot.transform || !sectionRoot.activeInHierarchy)
				return;
			var sectionName = sectionRoot.name ?? string.Empty;
			if (!sectionName.StartsWith("Section Root:", StringComparison.Ordinal))
				return;
			if (!_sectionFinalizerRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3TownBillboardSectionFinalizer>();
				_sectionFinalizerRegistered = true;
				log?.LogInfo("HoMM3 custom town billboard section finalizer: registered Il2Cpp type.");
			}
			var existing = sectionRoot.GetComponent<Homm3TownBillboardSectionFinalizer>();
			if (existing != null && existing)
				return;
			var finalizer = sectionRoot.AddComponent<Homm3TownBillboardSectionFinalizer>();
			finalizer.Initialize(reason);
			if (_sectionFinalizerDiagRemaining > 0)
			{
				_sectionFinalizerDiagRemaining--;
				log?.LogInfo("HoMM3 custom town billboard section finalizer: scheduled section='" + sectionName + "' reason='" + (reason ?? "?") + "'.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard section finalizer schedule failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool IsLiveMapCityRoot(GameObject root, string citySid)
	{
		if (!root || !root.activeInHierarchy || string.IsNullOrWhiteSpace(citySid))
			return false;
		// Land-on visit-gate clones keep root names like homm3_landon_castle_city.
		if (!Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(root.name, citySid))
			return false;
		var parentName = root.transform && root.transform.parent ? root.transform.parent.name ?? string.Empty : string.Empty;
		if (!parentName.StartsWith("Section Root:", StringComparison.Ordinal))
			return false;
		var sectionRoot = root.transform.parent.gameObject;
		foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer || IsUnderMarker(renderer.transform))
				continue;
			if (RendererBelongsToCitySid(sectionRoot.transform, renderer.transform, citySid))
				return true;
		}
		return false;
	}

	private static IEnumerable<object> EnumerateIl2CppList(object listObj)
	{
		if (listObj == null)
			yield break;
		var type = listObj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		PropertyInfo countProp = null;
		MethodInfo countGetter = null;
		MethodInfo itemGetter = null;
		for (var t = type; t != null && countProp == null; t = t.BaseType)
		{
			try { countProp = t.GetProperty("Count", flags); }
			catch { countProp = null; }
		}
		if (countProp == null)
		{
			for (var t = type; t != null && countGetter == null; t = t.BaseType)
			{
				try { countGetter = t.GetMethod("get_Count", flags, null, Type.EmptyTypes, null); }
				catch { countGetter = null; }
			}
		}
		for (var t = type; t != null && itemGetter == null; t = t.BaseType)
		{
			try { itemGetter = t.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null); }
			catch { itemGetter = null; }
		}
		if (itemGetter == null)
		{
			var enumerable = listObj as System.Collections.IEnumerable;
			if (enumerable == null)
				yield break;
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}
		int count;
		try
		{
			count = countProp != null
				? Convert.ToInt32(countProp.GetValue(listObj))
				: Convert.ToInt32(countGetter.Invoke(listObj, null));
		}
		catch
		{
			yield break;
		}
		for (var i = 0; i < count; i++)
		{
			object item;
			try { item = itemGetter.Invoke(listObj, new object[] { i }); }
			catch { item = null; }
			if (item != null)
				yield return item;
		}
	}

	private static bool TryGetConfigCityBillboard(object config, out string citySid, out string relativePath, out float billboardHeight)
	{
		citySid = null;
		relativePath = null;
		billboardHeight = 0f;
		if (config == null)
			return false;

		var sid = GetConfigSid(config);
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		LogSeenSid(sid, config);
		return TryResolveCityBillboardSid(sid, out citySid, out relativePath, out billboardHeight);
	}

	private static string GetMetaConfigSid(object meta)
	{
		if (meta == null)
			return null;
		var config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		return GetConfigSid(config);
	}

	private static string GetConfigSid(object config)
	{
		if (config == null)
			return null;
		var id = DeobfInteropCompat.GetConfigElementId(config);
		if (!string.IsNullOrWhiteSpace(id))
			return id;
		var fallback = GetFirstMemberValue(config, GameSymbols.CustomTownMapBillboard.ConfigIdFields) as string;
		// ObjectConfig.tag can leak through generated String_0; never treat category tokens as SIDs.
		if (string.IsNullOrWhiteSpace(fallback))
			return null;
		if (string.Equals(fallback.Trim(), "Artifact", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "Interact", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "Environment", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "Animals", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "FX", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "TEST", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "Resource", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "meta", StringComparison.Ordinal)
		    || string.Equals(fallback.Trim(), "Block", StringComparison.Ordinal))
			return null;
		return fallback;
	}

	private static bool IsGenericCityObjectSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var candidate = sid.Trim();
		return string.Equals(candidate, "city-spawner", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(candidate, "random-city", StringComparison.OrdinalIgnoreCase);
	}

	private static bool IsCityShapedBillboardHost(string placedSid, string metaSid, string rootName)
	{
		foreach (var candidate in new[] { placedSid, metaSid, rootName })
		{
			if (string.IsNullOrWhiteSpace(candidate))
				continue;
			if (IsGenericCityObjectSid(candidate))
				return true;
			if (Homm3CustomFactionRegistry.IsLandOnCityRootName(candidate))
				return true;
			var trimmed = candidate.Trim();
			if (trimmed.EndsWith("_city", StringComparison.OrdinalIgnoreCase))
				return true;
			if (trimmed.StartsWith("city_", StringComparison.OrdinalIgnoreCase)
			    || trimmed.StartsWith("obj_city_", StringComparison.OrdinalIgnoreCase))
				return true;
		}
		return false;
	}

	private static bool TryResolveCityBillboardSid(string sid, out string citySid, out string relativePath, out float billboardHeight)
	{
		citySid = null;
		relativePath = null;
		billboardHeight = 0f;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(sid, out relativePath, out billboardHeight))
			return false;
		// Canonicalize land-on visit-gate clones to the custom city SID the billboard assets use.
		citySid = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(sid.Trim());
		return !string.IsNullOrWhiteSpace(relativePath) && billboardHeight > 0f;
	}

	private static object GetReleaseMapObjectMeta(object instance)
	{
		return GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.MetaFields);
	}

	private static string TryGetPlacedObjectRootName(object placedInstance)
	{
		var root = GetReleaseMapObjectRoot(placedInstance);
		return root ? root.name : null;
	}

	private static GameObject GetReleaseMapObjectRoot(object instance)
	{
		return SelectReleaseMapObjectRoot(instance, null, null);
	}

	private static GameObject SelectReleaseMapObjectRoot(object instance, string citySid, ManualLogSource log)
	{
		var candidates = EnumerateReleaseMapObjectRootCandidates(instance).ToList();
		if (candidates.Count == 0)
			return null;
		RootCandidate best = null;
		for (var i = 0; i < candidates.Count; i++)
		{
			var candidate = candidates[i];
			if (candidate == null || !candidate.Root)
				continue;
			candidate.Score = ScoreRootCandidate(candidate.Root);
			if (best == null || candidate.Score > best.Score)
				best = candidate;
		}
		if (ShouldLogRootCandidateProbe(citySid))
			LogRootCandidateProbe(citySid, candidates, best, log);
		return best?.Root;
	}

	private static IEnumerable<RootCandidate> EnumerateReleaseMapObjectRootCandidates(object instance)
	{
		if (instance == null)
			yield break;
		foreach (var candidate in EnumerateNamedMemberValues(instance, GameSymbols.CustomTownMapBillboard.RootGameObjectFields))
		{
			if (candidate.Value is GameObject go && go)
				yield return new RootCandidate("field:" + candidate.Name, go);
		}
		var getterRoot = InvokeFirstNoArg(instance, typeof(GameObject), GameSymbols.CustomTownMapBillboard.RootGameObjectGetter) as GameObject;
		if (getterRoot)
			yield return new RootCandidate("getter:" + GameSymbols.CustomTownMapBillboard.RootGameObjectGetter.Id, getterRoot);
		foreach (var candidate in EnumerateNamedMemberValues(instance, GameSymbols.CustomTownMapBillboard.RootTransformFields))
		{
			if (candidate.Value is Transform transform && transform)
				yield return new RootCandidate("field:" + candidate.Name, transform.gameObject);
		}
		var getterTransform = InvokeFirstNoArg(instance, typeof(Transform), GameSymbols.CustomTownMapBillboard.RootTransformGetter) as Transform;
		if (getterTransform)
			yield return new RootCandidate("getter:" + GameSymbols.CustomTownMapBillboard.RootTransformGetter.Id, getterTransform.gameObject);
	}

	private static int ScoreRootCandidate(GameObject root)
	{
		if (!root)
			return int.MinValue;
		var score = root.activeInHierarchy ? 2000 : 0;
		var renderers = root.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r || IsUnderMarker(r.transform))
				continue;
			score += 20;
			if (r.enabled && !r.forceRenderingOff)
				score += 300;
			if (r.gameObject.activeInHierarchy)
				score += 150;
			var material = r.sharedMaterial;
			if (!material || !material.shader)
				continue;
			var shaderName = material.shader.name ?? string.Empty;
			if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
				score += 1000;
			if (shaderName.IndexOf("Sprites/Default", StringComparison.OrdinalIgnoreCase) >= 0)
				score -= 1000;
			if (HasTerrainBlendKeyword(material))
				score -= 700;
		}
		return score;
	}

	private static bool ShouldLogRootCandidateProbe(string citySid)
	{
		return _loggedRootCandidateProbe < 12
		       && Homm3DiagnosticFlags.IsEnabled(PropCityProbeFlagName)
		       && (string.IsNullOrWhiteSpace(citySid)
		           || citySid.IndexOf("stronghold", StringComparison.OrdinalIgnoreCase) >= 0
		           || citySid.IndexOf("homm3", StringComparison.OrdinalIgnoreCase) >= 0);
	}

	private static void LogRootCandidateProbe(string citySid, List<RootCandidate> candidates, RootCandidate best, ManualLogSource log)
	{
		if (log == null)
			return;
		_loggedRootCandidateProbe++;
		var parts = new List<string>();
		for (var i = 0; i < candidates.Count && parts.Count < 10; i++)
		{
			var candidate = candidates[i];
			if (candidate == null || !candidate.Root)
				continue;
			parts.Add(candidate.Source + " root='" + (candidate.Root.name ?? "?") + "' path='" + DescribeTransformPath(candidate.Root.transform) + "' score=" + candidate.Score + " renderers=" + CountOwnedRenderers(candidate.Root) + " best=[" + DescribeMaterial(FindBestMapDonorRenderer(candidate.Root)?.sharedMaterial) + "]");
		}
		log.LogInfo(
			"HoMM3 custom town billboard root probe city='"
			+ (citySid ?? "?")
			+ "' best='"
			+ (best?.Root ? best.Root.name : "?")
			+ "' candidates=["
			+ string.Join("; ", parts)
			+ "].");
	}

	private static bool ApplyBillboardPrefab(GameObject prefabRoot, string citySid, string relativePath, float billboardHeight, TownBillboardPlacement placement, ManualLogSource log)
	{
		if (!prefabRoot)
			return false;
		var placementRoot = prefabRoot;
		var suppressRoot = SelectBillboardVisualRoot(prefabRoot, citySid, log);
		if (!placementRoot || !suppressRoot)
			return false;
		var anchorRenderer = FindTownAnchorDonorRenderer(suppressRoot, placementRoot, citySid);
		var anchorLocalPosition = Vector3.zero;
		// Land-on towns: ObjectConfig GATE is south-center (nodes index 7). Placement root is
		// still the SW cell of the 3x3. HoMM3 town art is a full-town sprite (entrance at image
		// bottom-center). Anchoring on the GATE cell made the center-pivoted quad hang south of
		// the entrance and read as a corner gate. Anchor on the 3x3 footprint center instead
		// (SW +1 east, +1 north) so the town mass lines up with the HoMM3 body center and the
		// art entrance falls on the south-center GATE. Donor bounds.center stays skipped.
		var isLandOnCity = Homm3CustomFactionRegistry.IsLandOnCityRootName(placementRoot.name)
		                   || Homm3CustomFactionRegistry.IsLandOnCityRootName(prefabRoot.name);
		if (isLandOnCity)
		{
			if (suppressRoot != placementRoot)
			{
				log?.LogError(
					"HoMM3 custom town billboard: land-on suppress root escaped placement root city='"
					+ citySid
					+ "' placement='"
					+ (placementRoot.name ?? "?")
					+ "' suppress='"
					+ (suppressRoot.name ?? "?")
					+ "'; refusing apply (would mis-anchor GATE and leave dual town visuals).");
				return false;
			}
			anchorLocalPosition = GetLandOnFootprintCenterBillboardAnchorLocalPosition(
				placementRoot.transform,
				suppressRoot.transform);
			log?.LogInfo(
				"HoMM3 custom town billboard land-on footprint-center anchor city='"
				+ citySid
				+ "' root='"
				+ (placementRoot.name ?? "?")
				+ "' local="
				+ anchorLocalPosition.ToString("0.###")
				+ " (SW root +1 tile X / +1 tile north; GATE stays south-center; donor bounds.center skipped).");
		}
		else
		{
			var hasNativeDonorAnchor = anchorRenderer
			                           && TryGetNativeDonorAnchorLocalPosition(placementRoot.transform, suppressRoot.transform, anchorRenderer, out anchorLocalPosition);
			if (!hasNativeDonorAnchor)
			{
				LogNativeDonorAnchorUnavailable(placementRoot, suppressRoot, citySid, log);
				anchorLocalPosition = GetFallbackBillboardAnchorLocalPosition(placementRoot.transform, suppressRoot.transform);
			}
		}
		if (!placement.HasEntranceSide)
			LogNativePlacementOrientationUnavailable(placementRoot, suppressRoot, citySid, placement, log);
		LogNativeDonorAnchorApplied(citySid, anchorRenderer, anchorLocalPosition, placement, log);
		var materialDonorRenderer = anchorRenderer
		                            ?? FindBestMapDonorRenderer(placementRoot)
		                            ?? FindBestMapDonorRenderer(suppressRoot);
		var donorMaterial = materialDonorRenderer ? materialDonorRenderer.sharedMaterial : null;

		if (Homm3MapBuildingMeshBundle.IsEnabled()
		    && Homm3MapBuildingMeshBundle.HasMeshForRelativePath(relativePath))
		{
			// PropCity can resolve faction identity onto transient city-spawner/random-city roots
			// before durable homm3_*_city children exist. Painting the mesh onto a promoted
			// Section Root there left a Conflux capitol billboard (and vice versa) after finalization.
			// Fail soft until the exact custom city root owns the apply — no PNG fallback while the
			// mesh catalog hits for this path.
			if (!IsExactCustomCityRoot(placementRoot, citySid) && !IsExactCustomCityRoot(suppressRoot, citySid))
			{
				log?.LogInfo(
					"HoMM3 city map mesh: soft-skip city='"
					+ citySid
					+ "' root='"
					+ (placementRoot.name ?? "?")
					+ "' suppress='"
					+ (suppressRoot.name ?? "?")
					+ "' — waiting for durable exact city root (refuse PropCity/section-promoted apply).");
				return false;
			}
			return ApplyCityMapBuildingMesh(
				placementRoot,
				suppressRoot,
				citySid,
				relativePath,
				anchorLocalPosition,
				placement,
				materialDonorRenderer,
				donorMaterial,
				isLandOnCity,
				log);
		}

		var asset = GetOrCreateAsset(citySid, relativePath, billboardHeight, donorMaterial, log);
		if (asset == null || !asset.Material)
			return false;

		RemoveStaleBillboardMarkers(suppressRoot, citySid, suppressRoot);
		RemoveStaleMeshMarkers(suppressRoot, citySid);
		var donorRenderers = HideExistingRenderers(suppressRoot, citySid, placementRoot);

		var billboardRootName = BillboardRootPrefix + SanitizeName(citySid);
		var billboardRoot = suppressRoot.transform.Find(billboardRootName);
		if (billboardRoot == null)
		{
			var go = new GameObject(billboardRootName);
			billboardRoot = go.transform;
			billboardRoot.SetParent(suppressRoot.transform, false);
		}

		var mapLayer = materialDonorRenderer ? materialDonorRenderer.gameObject.layer : placementRoot.layer;
		var billboardScale = GetBillboardScale(asset, asset.Material.mainTexture);
		var bottomPaddingWorld = GetBottomPaddingWorld(asset, asset.Material.mainTexture, billboardScale);
		var liftY = (billboardScale.y * BillboardLiftRatio) - bottomPaddingWorld + BillboardGroundClearance;
		if (isLandOnCity)
			liftY -= LandOnBillboardLowerY;
		billboardRoot.localPosition = anchorLocalPosition
		                              + Vector3.up * liftY
		                              + Vector3.forward * BillboardSouthOffset;
		billboardRoot.localRotation = Quaternion.identity;
		billboardRoot.localScale = Vector3.one;
		billboardRoot.gameObject.layer = mapLayer;
		billboardRoot.gameObject.SetActive(true);
		RemoveStaleSectionBillboardMarkers(placementRoot, suppressRoot, billboardRoot, citySid);
		RemoveStaleSectionMeshMarkers(placementRoot, suppressRoot, billboardRoot, citySid);

		var quad = billboardRoot.Find("quad");
		var quadGo = quad == null ? new GameObject("quad") : quad.gameObject;
		if (quad == null)
			quadGo.transform.SetParent(billboardRoot, false);
		quadGo.layer = mapLayer;
		quadGo.SetActive(true);
		quadGo.transform.localRotation = Quaternion.identity;
		quadGo.transform.localPosition = new Vector3(0f, 0f, BillboardDepthTowardCamera);
		quadGo.transform.localScale = billboardScale;

		var mf = quadGo.GetComponent<MeshFilter>() ?? quadGo.AddComponent<MeshFilter>();
		var nd = quadGo.GetComponent<MeshRenderer>() ?? quadGo.AddComponent<MeshRenderer>();
		mf.sharedMesh = GetOrCreateQuadMesh();
		nd.sharedMaterial = asset.Material;
		ClearRendererPropertyBlock(nd);
		if (materialDonorRenderer)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(materialDonorRenderer, billboardRoot.gameObject);
		nd.enabled = true;
		nd.forceRenderingOff = false;
		nd.shadowCastingMode = ShadowCastingMode.On;
		nd.receiveShadows = false;
		nd.allowOcclusionWhenDynamic = false;
		if (!Homm3TownBillboardDonorSuppressor.TryAttach(billboardRoot.gameObject, donorRenderers, citySid, suppressRoot.transform, placementRoot.transform, log))
			return false;
		Homm3BattleBillboardCameraFacing.TryAttachMapObject(billboardRoot, log);
		ValidateBillboardPostconditions(suppressRoot, billboardRoot, quadGo, nd, asset.Material, asset.Material.mainTexture, materialDonorRenderer, citySid, log);
		if (_materialDiagRemaining > 0)
		{
			_materialDiagRemaining--;
			log?.LogInfo("HoMM3 custom town billboard: applied " + citySid + " asset='" + relativePath + "' material donor=[" + DescribeMaterial(donorMaterial) + "] final=[" + DescribeMaterial(asset.Material) + "] scale=" + billboardScale.ToString("0.###") + ".");
		}
		return true;
	}

	private static bool ApplyCityMapBuildingMesh(
		GameObject placementRoot,
		GameObject suppressRoot,
		string citySid,
		string relativePath,
		Vector3 anchorLocalPosition,
		TownBillboardPlacement placement,
		Renderer materialDonorRenderer,
		Material donorMaterial,
		bool isLandOnCity,
		ManualLogSource log)
	{
		if (!Homm3MapBuildingMeshBundle.TryLoadPrefab(relativePath, out var prefab, out var entry, log) || !prefab)
		{
			log?.LogError(
				"HoMM3 city map mesh: prefab load failed for city='"
				+ citySid
				+ "' path='"
				+ relativePath
				+ "'; refuse apply (homm3MapBuildingMeshes on — no PNG fallback for catalog hit).");
			return false;
		}

		RemoveStaleBillboardMarkers(suppressRoot, citySid, suppressRoot);
		RemoveStaleMeshMarkers(suppressRoot, citySid);
		var donorRenderers = HideExistingRenderers(suppressRoot, citySid, placementRoot);

		var meshRootName = Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeName(citySid);
		var existing = suppressRoot.transform.Find(meshRootName);
		if (existing)
			UnityEngine.Object.Destroy(existing.gameObject);

		var instance = UnityEngine.Object.Instantiate(prefab, suppressRoot.transform, false);
		instance.name = meshRootName;
		var mapLayer = materialDonorRenderer ? materialDonorRenderer.gameObject.layer : placementRoot.layer;
		SetLayerRecursive(instance, mapLayer);

		var runtimeScale = Homm3MapBuildingMeshBundle.GetRuntimeScale();
		instance.transform.localPosition = anchorLocalPosition
		                                   + Vector3.forward * BillboardSouthOffset;
		var authoredScale = instance.transform.localScale;
		if (authoredScale.sqrMagnitude < 1e-8f)
			authoredScale = Vector3.one;
		instance.transform.localScale = authoredScale * runtimeScale;
		instance.SetActive(true);

		// PNG billboards use identity localRotation and only use bvmu for entrance mirror sign.
		// OE rotation values include 0 and 10 (footprint/mirror encoding) — never × 90 for yaw.
		// Inherit parent facing; Meshy front is corrected inside OrientToBillboardArtAndSeat (+180).
		Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat(
			instance,
			mapFacingYawDegrees: 0f,
			artYawDegrees: entry != null ? entry.ArtYawDegrees : 0f,
			cacheKey: entry != null ? entry.PrefabKey : null,
			log);

		RemoveStaleSectionBillboardMarkers(placementRoot, suppressRoot, instance.transform, citySid);
		RemoveStaleSectionMeshMarkers(placementRoot, suppressRoot, instance.transform, citySid);

		if (!Homm3MapBuildingMeshBundle.TryRebindRenderersToMapDonor(instance, donorMaterial, log))
		{
			UnityEngine.Object.Destroy(instance);
			return false;
		}

		if (materialDonorRenderer)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(materialDonorRenderer, instance);

		if (!Homm3TownBillboardDonorSuppressor.TryAttach(
			    instance,
			    donorRenderers,
			    citySid,
			    suppressRoot.transform,
			    placementRoot.transform,
			    log))
		{
			UnityEngine.Object.Destroy(instance);
			return false;
		}

		var meshRenderers = instance.GetComponentsInChildren<MeshRenderer>(true);
		if (meshRenderers == null || meshRenderers.Length == 0)
		{
			log?.LogError("HoMM3 city map mesh: no MeshRenderer after instantiate.");
			UnityEngine.Object.Destroy(instance);
			return false;
		}

		foreach (var renderer in meshRenderers)
		{
			if (!renderer)
				continue;
			renderer.enabled = true;
			renderer.forceRenderingOff = false;
		}

		Homm3MapBuildingMeshProjectedFx.TryAttachForCatalogEntry(instance, entry, log);
		Homm3MeshFx.TryAttachForMapBuilding(instance, entry, log);
		Homm3MapBuildingAnim.TryAttachForMapBuilding(instance, entry, materialDonorRenderer, log);

		log?.LogInfo(
			"HoMM3 city map mesh: applied city='"
			+ citySid
			+ "' prefab='"
			+ (entry?.PrefabKey ?? "?")
			+ "' root='"
			+ (placementRoot.name ?? "?")
			+ "' scale="
			+ runtimeScale.ToString("0.###")
			+ " landOn="
			+ isLandOnCity
			+ " pose=billboardArt"
			+ " placementRotNoted="
			+ (placement.HasEntranceSide ? placement.Rotation.ToString() : "n/a")
			+ " mapFacing=parentInherit"
			+ " renderers="
			+ meshRenderers.Length
			+ ".");
		return true;
	}

	private static void SetLayerRecursive(GameObject root, int layer)
	{
		if (!root)
			return;
		root.layer = layer;
		var transforms = root.GetComponentsInChildren<Transform>(true);
		if (transforms == null)
			return;
		for (var i = 0; i < transforms.Length; i++)
		{
			if (transforms[i])
				transforms[i].gameObject.layer = layer;
		}
	}

	private static void RemoveStaleMeshMarkers(GameObject root, string citySid)
	{
		if (!root)
			return;
		var expectedName = Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeName(citySid);
		var transforms = root.GetComponentsInChildren<Transform>(true);
		if (transforms == null)
			return;
		for (var i = 0; i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (!t || t == root.transform || t.name == null)
				continue;
			if (!t.name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
				continue;
			if (t.name == expectedName && t.parent == root.transform)
				continue;
			UnityEngine.Object.Destroy(t.gameObject);
		}
	}

	private static bool IsExactCustomCityRoot(GameObject root, string citySid)
	{
		if (!root || string.IsNullOrWhiteSpace(citySid) || string.IsNullOrWhiteSpace(root.name))
			return false;
		if (IsGenericCityObjectSid(root.name))
			return false;
		if (root.name.StartsWith("Section Root:", StringComparison.OrdinalIgnoreCase))
			return false;
		return Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(root.name, citySid);
	}

	private static void RemoveStaleSectionMeshMarkers(
		GameObject placementRoot,
		GameObject suppressRoot,
		Transform expectedMeshRoot,
		string citySid)
	{
		if (!placementRoot || !suppressRoot || !expectedMeshRoot)
			return;
		var sectionRoot = FindNearestSectionRoot(placementRoot.transform);
		if (!sectionRoot || sectionRoot == suppressRoot.transform)
			return;

		var expectedName = Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeName(citySid);
		var stale = new List<GameObject>();
		for (var i = 0; i < sectionRoot.childCount; i++)
		{
			var child = sectionRoot.GetChild(i);
			if (!child || child.name == null || !child.name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
				continue;
			if (child.name == expectedName && child.parent == suppressRoot.transform)
				continue;
			if (!IsSameHorizontalPlacement(child.position, expectedMeshRoot.position)
			    && !IsStaleDirectSectionMeshMarker(sectionRoot, placementRoot, child, citySid, expectedName))
				continue;
			stale.Add(child.gameObject);
		}

		foreach (var go in stale)
		{
			if (!go)
				continue;
			go.SetActive(false);
			UnityEngine.Object.Destroy(go);
		}
	}

	private static bool IsStaleDirectSectionMeshMarker(
		Transform sectionRoot,
		GameObject placementRoot,
		Transform marker,
		string citySid,
		string expectedName)
	{
		if (!sectionRoot || !placementRoot || !placementRoot.transform || !marker || string.IsNullOrWhiteSpace(citySid))
			return false;
		if (marker.parent != sectionRoot
		    || string.IsNullOrWhiteSpace(marker.name)
		    || !marker.name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
			return false;
		if (placementRoot.transform.parent != sectionRoot
		    || !Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(placementRoot.name, citySid))
			return false;

		if (string.Equals(marker.name, expectedName, StringComparison.Ordinal))
			return CountDirectLiveCityRoots(sectionRoot, citySid) == 1;

		var markerCitySid = marker.name.Substring(Homm3MapBuildingMeshBundle.MeshRootPrefix.Length);
		if (string.IsNullOrWhiteSpace(markerCitySid))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(markerCitySid, out _, out _))
			return false;
		return CountDirectLiveCityRoots(sectionRoot, markerCitySid) == 0
		       && CountDirectLiveCityRoots(sectionRoot, citySid) == 1;
	}

	private static GameObject SelectBillboardVisualRoot(GameObject root, string citySid, ManualLogSource log)
	{
		if (!root)
			return null;
		// Land-on towns keep GATE / SW placement on the clone root. Promoting to Section Root
		// rewrote the south-center GATE billboard anchor into section-local garbage (e.g. local
		// -3.5/-8.72 instead of +1 tile X) and left neighboring section meshes counted as
		// "still-enabled donors" — corner-gate look + dual town visuals. Fail closed: never promote.
		if (Homm3CustomFactionRegistry.IsLandOnCityRootName(root.name))
			return root;
		if (IsGenericCityObjectSid(root.name) && root.transform && root.transform.parent)
		{
			var sectionRoot = root.transform.parent.gameObject;
			if (sectionRoot)
			{
				if (_postconditionDiagRemaining > 0)
				{
					_postconditionDiagRemaining--;
					log?.LogInfo(
						"HoMM3 custom town billboard: promoted generic city root city='"
						+ (citySid ?? "?")
						+ "' from='"
						+ (root.name ?? "?")
						+ "' to section='"
						+ (sectionRoot.name ?? "?")
						+ "'.");
				}
				return sectionRoot;
			}
		}
		var currentCount = CountOwnedRenderers(root);
		var bestRoot = root;
		var bestCount = currentCount;
		var cursor = root.transform ? root.transform.parent : null;
		var depth = 0;
		while (cursor && depth < 4)
		{
			var candidateRoot = cursor.gameObject;
			var candidateCount = CountOwnedRenderers(candidateRoot);
			if (candidateCount > bestCount && candidateCount <= 64)
			{
				bestRoot = candidateRoot;
				bestCount = candidateCount;
			}
			cursor = cursor.parent;
			depth++;
		}
		if (bestRoot == root || bestCount < currentCount + 2)
			return root;
		if (_postconditionDiagRemaining > 0)
		{
			_postconditionDiagRemaining--;
			log?.LogInfo(
				"HoMM3 custom town billboard: promoted visual root city='"
				+ (citySid ?? "?")
				+ "' from='"
				+ (root.name ?? "?")
				+ "' renderers="
				+ currentCount
				+ " to='"
				+ (bestRoot.name ?? "?")
				+ "' renderers="
				+ bestCount
				+ ".");
		}
		return bestRoot;
	}

	private static bool HasActiveBillboard(GameObject root, string citySid)
	{
		if (!root || string.IsNullOrWhiteSpace(citySid))
			return false;
		if (HasActiveCityMapBuildingMesh(root, citySid))
			return true;
		var billboardRoot = root.transform.Find(BillboardRootPrefix + SanitizeName(citySid));
		if (!billboardRoot || !billboardRoot.gameObject.activeSelf)
			return false;
		var quad = billboardRoot.Find("quad");
		var renderer = quad ? quad.GetComponent<MeshRenderer>() : null;
		return renderer && renderer.enabled && !renderer.forceRenderingOff && renderer.sharedMaterial;
	}

	private static bool HasActiveCityMapBuildingMesh(GameObject root, string citySid)
	{
		if (!root || string.IsNullOrWhiteSpace(citySid))
			return false;
		if (!Homm3MapBuildingMeshBundle.IsEnabled())
			return false;
		if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(citySid, out var relativePath, out _))
			return false;
		if (!Homm3MapBuildingMeshBundle.HasMeshForRelativePath(relativePath))
			return false;
		var meshRoot = root.transform.Find(Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeName(citySid));
		if (!meshRoot || !meshRoot.gameObject.activeSelf)
			return false;
		var renderers = meshRoot.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers == null || renderers.Length == 0)
			return false;
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (renderer && renderer.enabled && !renderer.forceRenderingOff && renderer.sharedMaterial)
				return true;
		}
		return false;
	}

	private static TownBillboardPlacement ResolveTownBillboardPlacement(object placedInstance, object[] args, GameObject root, string citySid)
	{
		if (TryGetRotationArgument(args, out var argRotation))
			return BuildTownBillboardPlacement(argRotation, "bvb.Init.rotation");
		if (TryGetPlacedObjectRotation(placedInstance, out var fieldRotation))
			return BuildTownBillboardPlacement(fieldRotation, "bvb.bvmu");
		if (TryGetRememberedTownBillboardPlacement(root, citySid, out var remembered))
			return remembered;
		return new TownBillboardPlacement(false, -1, 0f, "unknown");
	}

	private static TownBillboardPlacement BuildTownBillboardPlacement(int rotation, string source)
	{
		var sign = IsMirroredTownPlacement(rotation) ? 1f : -1f;
		return new TownBillboardPlacement(true, rotation, sign, source);
	}

	private static bool IsMirroredTownPlacement(int rotation)
	{
		return (rotation & 1) != 0;
	}

	private static bool TryGetRotationArgument(object[] args, out int rotation)
	{
		rotation = 0;
		if (args == null || args.Length <= 3 || args[3] == null)
			return false;
		return TryConvertRotationByte(args[3], out rotation);
	}

	private static bool TryGetPlacedObjectRotation(object placedInstance, out int rotation)
	{
		rotation = 0;
		if (placedInstance == null)
			return false;
		foreach (var candidate in EnumerateNamedMemberValues(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectRotationFields))
		{
			if (TryConvertRotationByte(candidate.Value, out rotation))
				return true;
		}
		return false;
	}

	private static bool TryConvertRotationByte(object value, out int rotation)
	{
		rotation = 0;
		if (value == null || value is string)
			return false;
		try
		{
			var converted = Convert.ToInt32(value);
			if (converted < byte.MinValue || converted > byte.MaxValue)
				return false;
			rotation = converted;
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static void RememberTownBillboardPlacement(GameObject root, string citySid, TownBillboardPlacement placement)
	{
		if (!root || string.IsNullOrWhiteSpace(citySid) || !placement.HasEntranceSide)
			return;
		PlacementByLiveRootKey[BuildLiveRootKey(root, citySid)] = placement;
	}

	private static bool TryGetRememberedTownBillboardPlacement(GameObject root, string citySid, out TownBillboardPlacement placement)
	{
		placement = default;
		if (!root || string.IsNullOrWhiteSpace(citySid))
			return false;
		return PlacementByLiveRootKey.TryGetValue(BuildLiveRootKey(root, citySid), out placement);
	}

	private static void LogNativePlacementOrientationUnavailable(GameObject placementRoot, GameObject suppressRoot, string citySid, TownBillboardPlacement placement, ManualLogSource log)
	{
		if (_donorAnchorMissDiagRemaining <= 0)
			return;
		_donorAnchorMissDiagRemaining--;
		log?.LogWarning(
			"HoMM3 custom town billboard: native placed-object orientation unavailable city='"
			+ (citySid ?? "?")
			+ "' placementRoot='"
			+ (placementRoot ? DescribeTransformPath(placementRoot.transform) : "?")
			+ "' suppressRoot='"
			+ (suppressRoot ? DescribeTransformPath(suppressRoot.transform) : "?")
			+ "' entranceSource='"
			+ (placement.Source ?? "?")
			+ "'; using footprint-center placement without entrance-side offset.");
	}

	private static void LogNativeDonorAnchorApplied(string citySid, Renderer donorRenderer, Vector3 anchorLocalPosition, TownBillboardPlacement placement, ManualLogSource log)
	{
		if (_entranceAnchorDiagRemaining <= 0)
			return;
		_entranceAnchorDiagRemaining--;
		log?.LogInfo(
			"HoMM3 custom town billboard: anchored city='"
			+ (citySid ?? "?")
			+ "' to native donor renderer center local="
			+ anchorLocalPosition.ToString("0.###")
			+ " entranceSource='"
			+ (placement.Source ?? "?")
			+ "' rotation="
			+ (placement.HasEntranceSide ? placement.Rotation.ToString() : "?")
			+ " entranceOffsetX=retired donor='"
			+ (donorRenderer ? DescribeTransformPath(donorRenderer.transform) : "?")
			+ "'.");
	}

	private static void LogNativeDonorAnchorUnavailable(GameObject placementRoot, GameObject suppressRoot, string citySid, ManualLogSource log)
	{
		if (_donorAnchorMissDiagRemaining <= 0)
			return;
		_donorAnchorMissDiagRemaining--;
		log?.LogWarning(
			"HoMM3 custom town billboard: native donor renderer anchor unavailable city='"
			+ (citySid ?? "?")
			+ "' placementRoot='"
			+ (placementRoot ? DescribeTransformPath(placementRoot.transform) : "?")
			+ "' suppressRoot='"
			+ (suppressRoot ? DescribeTransformPath(suppressRoot.transform) : "?")
			+ "'; using root-center fallback placement.");
	}

	private static bool TryGetNativeDonorAnchorLocalPosition(Transform placementRoot, Transform suppressRoot, Renderer donorRenderer, out Vector3 anchorLocalPosition)
	{
		anchorLocalPosition = Vector3.zero;
		if (!placementRoot || !suppressRoot || !donorRenderer)
			return false;
		try
		{
			var bounds = donorRenderer.bounds;
			var world = bounds.center;
			world.y = placementRoot.position.y;
			anchorLocalPosition = suppressRoot.InverseTransformPoint(world) - Vector3.forward * BillboardSouthOffset;
			return true;
		}
		catch
		{
			anchorLocalPosition = Vector3.zero;
			return false;
		}
	}

	private static Vector3 GetFallbackBillboardAnchorLocalPosition(Transform placementRoot, Transform suppressRoot)
	{
		if (!placementRoot || !suppressRoot)
			return Vector3.zero;
		try
		{
			if (placementRoot == suppressRoot)
				return Vector3.zero;
			return suppressRoot.InverseTransformPoint(placementRoot.position) - Vector3.forward * BillboardSouthOffset;
		}
		catch
		{
			return Vector3.zero;
		}
	}

	private static Vector3 GetLandOnFootprintCenterBillboardAnchorLocalPosition(Transform placementRoot, Transform suppressRoot)
	{
		var swLocal = GetFallbackBillboardAnchorLocalPosition(placementRoot, suppressRoot);
		if (!placementRoot)
			return swLocal;
		try
		{
			// Map +X / planar north from the placement root (section roots are axis-aligned).
			var east = placementRoot.right;
			east.y = 0f;
			if (east.sqrMagnitude < 1e-6f)
				east = Vector3.right;
			east.Normalize();
			// Olden map north is -forward when sections face the camera along +Z south.
			var north = -placementRoot.forward;
			north.y = 0f;
			if (north.sqrMagnitude < 1e-6f)
				north = Vector3.forward;
			north.Normalize();
			var centerWorld = placementRoot.position
			                  + east * LandOnSouthCenterGateTileWorldSize
			                  + north * LandOnFootprintCenterNorthTiles;
			if (!suppressRoot)
				return swLocal + east * LandOnSouthCenterGateTileWorldSize + north * LandOnFootprintCenterNorthTiles;
			return suppressRoot.InverseTransformPoint(centerWorld) - Vector3.forward * BillboardSouthOffset;
		}
		catch
		{
			return swLocal;
		}
	}

	private static Vector3 GetLandOnSouthCenterGateBillboardAnchorLocalPosition(Transform placementRoot, Transform suppressRoot)
	{
		// Kept for diagnostics; land-on apply uses footprint-center anchoring.
		var swLocal = GetFallbackBillboardAnchorLocalPosition(placementRoot, suppressRoot);
		if (!placementRoot)
			return swLocal;
		try
		{
			var east = placementRoot.right;
			east.y = 0f;
			if (east.sqrMagnitude < 1e-6f)
				east = Vector3.right;
			east.Normalize();
			var gateWorld = placementRoot.position + east * LandOnSouthCenterGateTileWorldSize;
			if (!suppressRoot)
				return swLocal + east * LandOnSouthCenterGateTileWorldSize;
			return suppressRoot.InverseTransformPoint(gateWorld) - Vector3.forward * BillboardSouthOffset;
		}
		catch
		{
			return swLocal;
		}
	}

	private static bool HasAppliedLiveRoot(GameObject root, string sid)
	{
		return root && !string.IsNullOrWhiteSpace(sid) && AppliedLiveRootKeys.Contains(BuildLiveRootKey(root, sid));
	}

	private static void EnsureAppliedBillboardSuppressesDonor(GameObject root, string citySid)
	{
		if (!root || string.IsNullOrWhiteSpace(citySid))
			return;
		var placementRoot = root;
		var suppressRoot = SelectBillboardVisualRoot(root, citySid, null);
		if (!placementRoot || !suppressRoot || !HasActiveBillboard(suppressRoot, citySid))
			return;
		var donorRenderers = HideExistingRenderers(suppressRoot, citySid, placementRoot);
		var billboardRoot = suppressRoot.transform.Find(BillboardRootPrefix + SanitizeName(citySid));
		if (billboardRoot)
		{
			Homm3TownBillboardDonorSuppressor.TryAttach(billboardRoot.gameObject, donorRenderers, citySid, suppressRoot.transform, placementRoot.transform, Plugin.LogSource);
		}
	}

	private static void MarkAppliedLiveRoot(GameObject root, string sid)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return;
		AppliedLiveRootKeys.Add(BuildLiveRootKey(root, sid));
	}

	internal static void ResetScenePlacementCache()
	{
		PlacementByLiveRootKey.Clear();
	}

	private static string BuildLiveRootKey(GameObject root, string sid)
	{
		return root.GetInstanceID().ToString() + "|" + sid;
	}

	private static BillboardAsset GetOrCreateAsset(string citySid, string relativePath, float billboardHeight, Material donorMaterial, ManualLogSource log)
	{
		var key = citySid + "|" + relativePath;
		if (Assets.TryGetValue(key, out var existing))
		{
			if (IsBillboardAssetUsable(existing))
				return existing;
			Assets.Remove(key);
			if (existing == null || !existing.Texture)
				TexturesByKey.Remove(key);
			if (_assetRefreshDiagRemaining > 0)
			{
				_assetRefreshDiagRemaining--;
				log?.LogInfo("HoMM3 custom town billboard: rebuilt cached " + citySid + " billboard asset after map reload invalidated a Unity object or material shader.");
			}
		}

		var texture = GetOrCreateTexture(citySid, relativePath, log);
		if (!texture)
			return null;
		var material = CreateBillboardMaterial(citySid, texture, donorMaterial, log);
		if (!material)
			return null;
		var asset = new BillboardAsset(texture, material, billboardHeight);
		Assets[key] = asset;
		return asset;
	}

	private static bool IsBillboardAssetUsable(BillboardAsset asset)
	{
		if (asset == null || !asset.Texture || !asset.Material)
			return false;
		if (!IsHexLitMaterial(asset.Material))
			return false;
		var texture = asset.Material.mainTexture;
		return texture;
	}

	private static Texture2D GetOrCreateTexture(string citySid, string relativePath, ManualLogSource log)
	{
		var key = citySid + "|" + relativePath;
		if (TexturesByKey.TryGetValue(key, out var existing) && existing)
			return existing;
		var texture = LoadTexture(citySid, relativePath, log);
		if (!texture)
			return null;
		TexturesByKey[key] = texture;
		return texture;
	}

	private static Texture2D LoadTexture(string citySid, string relativePath, ManualLogSource log)
	{
		// Phase 2 pilot: homm3_map_billboards AssetBundle before PNG decode; PNG stays the per-key
		// fallback. Bundle textures are compressed/not CPU-readable, so the required bottom padding
		// goes through a GPU blit instead of GetPixels32; a pad failure refuses the unpadded texture
		// (placement math depends on the pad) and falls back to the PNG path.
		if (Homm3MapBillboardBundle.IsEnabled())
		{
			if (Homm3MapBillboardBundle.TryLoadTexture(relativePath, out var bundleTexture) && bundleTexture)
			{
				LogBillboardBundleResolution(citySid, relativePath, hit: true, log);
				var paddedFromBundle = CreateBottomPaddedTextureFromGpu(bundleTexture, TextureBottomPaddingPixels, citySid, log);
				if (paddedFromBundle)
				{
					paddedFromBundle.filterMode = FilterMode.Point;
					paddedFromBundle.wrapMode = TextureWrapMode.Clamp;
					return paddedFromBundle;
				}
				log?.LogWarning(
					"HoMM3 custom town billboard: bundle texture pad failed for "
					+ citySid
					+ " ("
					+ relativePath
					+ "); falling back to PNG so bottom padding stays exact.");
			}
			else
			{
				LogBillboardBundleResolution(citySid, relativePath, hit: false, log);
			}
		}

		if (!Homm3CustomFactionRegistry.TryGetStartupAssetPath(relativePath, out var pluginPath))
		{
			if (_loggedMissingImage < 20)
			{
				_loggedMissingImage++;
				log?.LogWarning("HoMM3 custom town billboard: missing image for " + citySid + ": " + relativePath + ".");
			}
			return null;
		}

		var source = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		if (!TryLoadTextureImage(source, File.ReadAllBytes(pluginPath)))
		{
			UnityEngine.Object.Destroy(source);
			return null;
		}
		source.name = "HOMM3_" + SanitizeName(citySid) + "_map_billboard_source";
		source.filterMode = FilterMode.Point;
		source.wrapMode = TextureWrapMode.Clamp;
		var padded = CreateBottomPaddedTexture(source, TextureBottomPaddingPixels, citySid, log) ?? source;
		padded.filterMode = FilterMode.Point;
		padded.wrapMode = TextureWrapMode.Clamp;
		return padded;
	}

	private static readonly HashSet<string> LoggedBillboardBundleResolution = new(StringComparer.Ordinal);

	private static void LogBillboardBundleResolution(string citySid, string relativePath, bool hit, ManualLogSource log)
	{
		var key = (citySid ?? "?") + "|" + (relativePath ?? "?");
		if (!LoggedBillboardBundleResolution.Add(key))
			return;
		log?.LogInfo(
			"HoMM3 custom town billboard: "
			+ (hit ? "bundle-hit" : "bundle-miss")
			+ " city='"
			+ (citySid ?? "?")
			+ "' asset='"
			+ (relativePath ?? "?")
			+ "' (homm3_map_billboards"
			+ (hit ? "" : "; falling back to PNG")
			+ ").");
	}

	/// <summary>
	/// Bottom-pads a non-CPU-readable (compressed bundle) texture so placement matches the PNG path.
	/// Decompress with a same-size <see cref="Graphics.Blit"/> + <see cref="Texture2D.ReadPixels"/>,
	/// then reuse <see cref="CreateBottomPaddedTexture"/> (source rows above
	/// <paramref name="bottomPadding"/> transparent rows).
	/// Do not Blit with scale/offset into a taller RT: that remaps UVs across the full destination
	/// (stretch/crop) and never leaves a transparent gutter. Lift math still subtracts
	/// <c>bottomPaddingWorld</c>, so a false pad pushes town art south/down.
	/// </summary>
	private static Texture2D CreateBottomPaddedTextureFromGpu(Texture2D source, int bottomPadding, string citySid, ManualLogSource log)
	{
		if (!source || bottomPadding <= 0)
			return null;
		RenderTexture renderTarget = null;
		var previousActive = RenderTexture.active;
		Texture2D readable = null;
		try
		{
			var width = source.width;
			var height = source.height;
			if (width <= 0 || height <= 0)
				return null;

			// Same-size blit only decompresses DXT → RGBA for ReadPixels. Padding is owned by
			// CreateBottomPaddedTexture so PNG and bundle share one pixel layout.
			renderTarget = RenderTexture.GetTemporary(
				width,
				height,
				0,
				RenderTextureFormat.ARGB32,
				RenderTextureReadWrite.sRGB);
			Graphics.Blit(source, renderTarget);
			RenderTexture.active = renderTarget;
			readable = new Texture2D(width, height, TextureFormat.RGBA32, false)
			{
				name = "HOMM3_" + SanitizeName(citySid) + "_map_billboard_bundle_decode"
			};
			readable.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
			readable.Apply(false, false);
			RenderTexture.active = previousActive;

			var padded = CreateBottomPaddedTexture(readable, bottomPadding, citySid, log);
			if (!padded)
			{
				log?.LogWarning(
					"HoMM3 custom town billboard: bundle texture CPU bottom padding failed for "
					+ citySid
					+ " after GPU decode.");
				UnityEngine.Object.Destroy(readable);
				readable = null;
				return null;
			}
			// CreateBottomPaddedTexture destroys the readable source on success.
			readable = null;

			if (!HasTransparentBottomPad(padded, bottomPadding))
			{
				log?.LogWarning(
					"HoMM3 custom town billboard: bundle padded texture failed transparent-bottom check for "
					+ citySid
					+ " (padPx="
					+ bottomPadding
					+ "); refusing so placement does not apply a false south/down lift.");
				UnityEngine.Object.Destroy(padded);
				return null;
			}

			log?.LogInfo(
				"HoMM3 custom town billboard: padded bundle texture "
				+ citySid
				+ " source="
				+ width
				+ "x"
				+ height
				+ " padded="
				+ padded.width
				+ "x"
				+ padded.height
				+ ".");
			return padded;
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard: bundle texture bottom padding failed for " + citySid + ": " + ex.Message);
			if (readable)
				UnityEngine.Object.Destroy(readable);
			return null;
		}
		finally
		{
			RenderTexture.active = previousActive;
			if (renderTarget != null)
				RenderTexture.ReleaseTemporary(renderTarget);
		}
	}

	/// <summary>
	/// Spot-checks the bottom gutter: mid-pad pixel must be transparent. Catches the Blit(scale,offset)
	/// false-pad failure mode where opaque art fills the region placement treats as empty.
	/// </summary>
	private static bool HasTransparentBottomPad(Texture2D padded, int bottomPadding)
	{
		if (!padded || bottomPadding <= 0 || padded.height < bottomPadding || padded.width <= 0)
			return false;
		var sample = padded.GetPixel(padded.width / 2, bottomPadding / 2);
		return sample.a <= 0.01f;
	}

	private static Texture2D CreateBottomPaddedTexture(Texture2D source, int bottomPadding, string citySid, ManualLogSource log)
	{
		if (!source || bottomPadding <= 0)
			return null;
		try
		{
			var sourcePixels = source.GetPixels32();
			var width = source.width;
			var height = source.height;
			if (sourcePixels == null || sourcePixels.Length != width * height)
				return null;
			var paddedHeight = height + bottomPadding;
			var padded = new Texture2D(width, paddedHeight, TextureFormat.RGBA32, false)
			{
				name = "HOMM3_" + SanitizeName(citySid) + "_map_billboard_padded"
			};
			var clear = new Color32(0, 0, 0, 0);
			var pixels = new Color32[width * paddedHeight];
			for (var i = 0; i < pixels.Length; i++)
				pixels[i] = clear;
			for (var y = 0; y < height; y++)
				Array.Copy(sourcePixels, y * width, pixels, (y + bottomPadding) * width, width);
			padded.SetPixels32(pixels);
			padded.Apply(false, false);
			log?.LogInfo("HoMM3 custom town billboard: padded " + citySid + " texture source=" + width + "x" + height + " padded=" + width + "x" + paddedHeight + ".");
			UnityEngine.Object.Destroy(source);
			return padded;
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard: bottom padding failed for " + citySid + ": " + ex.Message);
			return null;
		}
	}

	private static Material CreateBillboardMaterial(string citySid, Texture texture, Material donorMaterial, ManualLogSource log)
	{
		if (!texture)
			return null;

		var materialName = "HOMM3_custom_town_billboard_" + SanitizeName(citySid);
		var donorForMaterial = ResolveTownBillboardDonorMaterial(donorMaterial, log);
		if (donorForMaterial)
		{
			var sanitized = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(
				donorForMaterial,
				texture,
				materialName + "_hexlit",
				keepRevealed: true);
			if (sanitized)
				return sanitized;
		}

		var shader = Shader.Find("Hex/Lit");
		if (!shader)
			return null;
		var material = new Material(shader) { name = materialName + "_hexlit_generated" };
		if (material.HasProperty("_MainTex"))
			material.SetTexture("_MainTex", texture);
		material.mainTexture = texture;
		if (material.HasProperty("_EmissionTex"))
			material.SetTexture("_EmissionTex", null);
		if (material.HasProperty("_BaseMap"))
			material.SetTexture("_BaseMap", texture);
		if (material.HasProperty("_AlphaClip"))
			material.SetFloat("_AlphaClip", 1f);
		if (material.HasProperty("_AlphaCutoff"))
			material.SetFloat("_AlphaCutoff", 0.08f);
		if (material.HasProperty("_Cutoff"))
			material.SetFloat("_Cutoff", 0.08f);
		if (material.HasProperty("_Color"))
			material.SetColor("_Color", Color.white);
		if (material.HasProperty("_EmissionColor"))
			material.SetColor("_EmissionColor", Color.black);
		try { material.EnableKeyword("HEX_ALPHA_CLIP_ENABLED"); } catch { }
		try { material.EnableKeyword("_ALPHATEST_ON"); } catch { }
		try { material.DisableKeyword("_EMISSION"); } catch { }
		EsquirePikemanVisuals.FinalizeHexLitMapBillboardMaterial(material, null, keepRevealed: true);
		return material;
	}

	private static Material ResolveTownBillboardDonorMaterial(Material donorMaterial, ManualLogSource log)
	{
		if (!donorMaterial || !IsHexLitMaterial(donorMaterial))
		{
			if (EsquirePikemanVisuals.TryFindLoadedUnitStyleHexLitMapDonor(log, out var loadedOnly))
				return loadedOnly;
			if (donorMaterial && _materialDiagRemaining > 0)
			{
				_materialDiagRemaining--;
				log?.LogInfo("HoMM3 custom town billboard: rejected non-Hex/Lit city donor=[" + DescribeMaterial(donorMaterial) + "].");
			}
			return null;
		}

		if (!HasTerrainBlendKeyword(donorMaterial))
			return donorMaterial;
		if (!EsquirePikemanVisuals.TryFindLoadedUnitStyleHexLitMapDonor(log, out var unitDonor))
			return donorMaterial;
		if (_materialDiagRemaining > 0)
		{
			_materialDiagRemaining--;
			log?.LogInfo(
				"HoMM3 custom town billboard: replaced terrain-blend city donor=["
				+ DescribeMaterial(donorMaterial)
				+ "] with unit-style donor=["
				+ DescribeMaterial(unitDonor)
				+ "].");
		}
		return unitDonor;
	}

	private static bool IsHexLitMaterial(Material material)
	{
		return material
		       && material.shader
		       && !string.IsNullOrWhiteSpace(material.shader.name)
		       && material.shader.name.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool HasTerrainBlendKeyword(Material material)
	{
		if (!material)
			return false;
		var kws = material.shaderKeywords;
		if (kws == null)
			return false;
		for (var i = 0; i < kws.Length; i++)
		{
			var kw = kws[i];
			if (string.Equals(kw, "HEX_BLEND_INTO_TERRAIN_POSITION", StringComparison.Ordinal)
			    || string.Equals(kw, "HEX_BLEND_INTO_TERRAIN_COLOR", StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static List<Renderer> HideExistingRenderers(GameObject root, string citySid, GameObject placementRoot = null)
	{
		var hidden = new List<Renderer>();
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderMarker(r.transform))
				continue;
			if (!ShouldHideTownDonorRenderer(root.transform, placementRoot ? placementRoot.transform : null, r.transform, citySid))
				continue;
			r.enabled = false;
			r.forceRenderingOff = true;
			hidden.Add(r);
		}
		return hidden;
	}

	private static bool ShouldHideTownDonorRenderer(Transform suppressRoot, Transform placementRoot, Transform rendererTransform, string citySid)
	{
		if (!suppressRoot || !rendererTransform)
			return false;
		if (placementRoot && placementRoot != suppressRoot && rendererTransform.IsChildOf(placementRoot))
			return true;
		if (RendererBelongsToCitySid(suppressRoot, rendererTransform, citySid))
			return true;
		if (placementRoot && placementRoot.parent == suppressRoot && IsNativeTownDonorRenderer(suppressRoot, placementRoot, rendererTransform))
			return true;
		return false;
	}

	private static bool IsNativeTownDonorRenderer(Transform suppressRoot, Transform placementRoot, Transform rendererTransform)
	{
		for (var t = rendererTransform; t != null && t != suppressRoot.parent; t = t.parent)
		{
			if (t == suppressRoot || t == placementRoot)
				continue;
			if (t.parent != suppressRoot || !IsNearPlacementRoot(t, placementRoot))
				continue;
			var name = t.name ?? string.Empty;
			if (name.EndsWith("_city(Clone)", StringComparison.OrdinalIgnoreCase)
			    || name.EndsWith("_town(Clone)", StringComparison.OrdinalIgnoreCase)
			    || name.IndexOf("city(Clone)", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	internal static bool IsNearPlacementRoot(Transform candidateRoot, Transform placementRoot)
	{
		if (!candidateRoot || !placementRoot)
			return false;
		var delta = candidateRoot.localPosition - placementRoot.localPosition;
		delta.y = 0f;
		return delta.sqrMagnitude <= NativeTownDonorSiblingTolerance * NativeTownDonorSiblingTolerance;
	}

	private static bool RendererBelongsToCitySid(Transform suppressRoot, Transform rendererTransform, string citySid)
	{
		if (!suppressRoot || !rendererTransform || string.IsNullOrWhiteSpace(citySid))
			return false;
		for (var t = rendererTransform; t != null && t != suppressRoot.parent; t = t.parent)
		{
			var name = t.name ?? string.Empty;
			if (Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(name, citySid))
				return true;
			if (name.IndexOf("_homm3_" + citySid + "_billboard", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	private static int CountOwnedRenderers(GameObject root)
	{
		if (!root)
			return 0;
		var count = 0;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderMarker(r.transform))
				continue;
			count++;
		}
		return count;
	}

	private static Renderer FindBestMapDonorRenderer(GameObject root)
	{
		Renderer best = null;
		var bestScore = int.MinValue;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderMarker(r.transform))
				continue;
			var m = r.sharedMaterial;
			if (!m || !m.shader)
				continue;
			var score = 0;
			if ((m.shader.name ?? string.Empty).IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
				score += 1000;
			if (r.enabled)
				score += 500;
			if (m.renderQueue >= 2000 && m.renderQueue <= 2500)
				score += 250;
			if (HasTerrainBlendKeyword(m))
				score -= 1000;
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = r;
		}
		return best;
	}

	private static Renderer FindTownAnchorDonorRenderer(GameObject suppressRoot, GameObject placementRoot, string citySid)
	{
		if (!suppressRoot || !placementRoot)
			return null;
		Renderer best = null;
		var bestScore = int.MinValue;
		foreach (var r in suppressRoot.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderMarker(r.transform))
				continue;
			if (!ShouldHideTownDonorRenderer(suppressRoot.transform, placementRoot.transform, r.transform, citySid))
				continue;
			var isCitySidRenderer = RendererBelongsToCitySid(suppressRoot.transform, r.transform, citySid);
			var isNativeSiblingRenderer = placementRoot.transform.parent == suppressRoot.transform
			                              && IsNativeTownDonorRenderer(suppressRoot.transform, placementRoot.transform, r.transform);
			if (!isCitySidRenderer && !isNativeSiblingRenderer)
				continue;
			var m = r.sharedMaterial;
			if (!m || !m.shader)
				continue;
			var score = 0;
			if (isCitySidRenderer)
				score += 3000;
			if (isNativeSiblingRenderer)
				score += 2500;
			if (r.transform.IsChildOf(placementRoot.transform) && Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(placementRoot.name, citySid))
				score += 1000;
			if ((m.shader.name ?? string.Empty).IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
				score += 1000;
			if (r.enabled)
				score += 500;
			if (r.gameObject.activeInHierarchy)
				score += 250;
			if (m.renderQueue >= 2000 && m.renderQueue <= 2500)
				score += 150;
			if (HasTerrainBlendKeyword(m))
				score -= 1000;
			var distancePenalty = GetRendererAnchorDistancePenalty(placementRoot.transform, r);
			score -= distancePenalty;
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = r;
		}
		return best;
	}

	private static int GetRendererAnchorDistancePenalty(Transform placementRoot, Renderer renderer)
	{
		if (!placementRoot || !renderer)
			return 0;
		try
		{
			var delta = renderer.bounds.center - placementRoot.position;
			delta.y = 0f;
			return Mathf.RoundToInt(Mathf.Min(1000f, delta.magnitude * 25f));
		}
		catch
		{
			return 0;
		}
	}

	private static void RemoveStaleBillboardMarkers(GameObject root, string citySid, GameObject expectedParent)
	{
		if (!root)
			return;
		var expectedName = BillboardRootPrefix + SanitizeName(citySid);
		var stale = new List<GameObject>();
		foreach (var t in root.GetComponentsInChildren<Transform>(true))
		{
			if (!t || t == root.transform || t.name == null || !t.name.StartsWith(BillboardRootPrefix, StringComparison.Ordinal))
				continue;
			if (t.name == expectedName && expectedParent && t.parent == expectedParent.transform)
				continue;
			stale.Add(t.gameObject);
		}
		foreach (var go in stale)
		{
			if (!go)
				continue;
			go.SetActive(false);
			UnityEngine.Object.Destroy(go);
		}
	}

	private static void RemoveStaleSectionBillboardMarkers(GameObject placementRoot, GameObject suppressRoot, Transform expectedBillboardRoot, string citySid)
	{
		if (!placementRoot || !suppressRoot || !expectedBillboardRoot)
			return;
		var sectionRoot = FindNearestSectionRoot(placementRoot.transform);
		if (!sectionRoot || sectionRoot == suppressRoot.transform)
			return;

		var expectedName = BillboardRootPrefix + SanitizeName(citySid);
		var stale = new List<GameObject>();
		for (var i = 0; i < sectionRoot.childCount; i++)
		{
			var child = sectionRoot.GetChild(i);
			if (!child || child.name == null || !child.name.StartsWith(BillboardRootPrefix, StringComparison.Ordinal))
				continue;
			if (child.name == expectedName && child.parent == suppressRoot.transform)
				continue;
			if (!IsSameHorizontalPlacement(child.position, expectedBillboardRoot.position)
			    && !IsStaleDirectSectionBillboardMarker(sectionRoot, placementRoot, child, citySid, expectedName))
				continue;
			stale.Add(child.gameObject);
		}

		foreach (var go in stale)
		{
			if (!go)
				continue;
			go.SetActive(false);
			UnityEngine.Object.Destroy(go);
		}
	}

	private static bool IsStaleDirectSectionBillboardMarker(Transform sectionRoot, GameObject placementRoot, Transform marker, string citySid, string expectedName)
	{
		if (!sectionRoot || !placementRoot || !placementRoot.transform || !marker || string.IsNullOrWhiteSpace(citySid))
			return false;
		if (marker.parent != sectionRoot || string.IsNullOrWhiteSpace(marker.name) || !marker.name.StartsWith(BillboardRootPrefix, StringComparison.Ordinal))
			return false;
		if (placementRoot.transform.parent != sectionRoot || !Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(placementRoot.name, citySid))
			return false;

		// June 16, 2026: entrance alignment can move the valid city-root marker outside the
		// old proximity cleanup radius. Remove the former section-root marker only when the
		// same section has one unambiguous live root for this exact city SID.
		if (string.Equals(marker.name, expectedName, StringComparison.Ordinal))
			return CountDirectLiveCityRoots(sectionRoot, citySid) == 1;

		// June 17, 2026: streamed/reused sections can also keep a direct section-root marker
		// from a different custom city after that city root has left the section. Remove that
		// marker only when its exact city SID has no live direct city root here.
		var markerCitySid = marker.name.Substring(BillboardRootPrefix.Length);
		if (string.IsNullOrWhiteSpace(markerCitySid))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(markerCitySid, out _, out _))
			return false;
		return CountDirectLiveCityRoots(sectionRoot, markerCitySid) == 0
		       && CountDirectLiveCityRoots(sectionRoot, citySid) == 1;
	}

	private static int CountDirectLiveCityRoots(Transform sectionRoot, string citySid)
	{
		if (!sectionRoot || string.IsNullOrWhiteSpace(citySid))
			return 0;
		var matchingCityRoots = 0;
		for (var i = 0; i < sectionRoot.childCount; i++)
		{
			var child = sectionRoot.GetChild(i);
			if (!child || !Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(child.name, citySid))
				continue;
			if (!HasNonMarkerRenderer(child))
				continue;
			matchingCityRoots++;
			if (matchingCityRoots > 1)
				return matchingCityRoots;
		}
		return matchingCityRoots;
	}

	private static bool HasNonMarkerRenderer(Transform root)
	{
		if (!root)
			return false;
		foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer || IsUnderMarker(renderer.transform))
				continue;
			return true;
		}
		return false;
	}

	private static Transform FindNearestSectionRoot(Transform transform)
	{
		for (var t = transform; t != null; t = t.parent)
		{
			if (t.name != null && t.name.StartsWith("Section Root:", StringComparison.Ordinal))
				return t;
		}
		return null;
	}

	private static bool IsSameHorizontalPlacement(Vector3 a, Vector3 b)
	{
		var dx = a.x - b.x;
		var dz = a.z - b.z;
		return (dx * dx) + (dz * dz)
		       <= StaleSectionBillboardMarkerCleanupRadius * StaleSectionBillboardMarkerCleanupRadius;
	}

	private static bool IsUnderMarker(Transform transform)
	{
		for (var t = transform; t != null; t = t.parent)
		{
			if (t.name == null)
				continue;
			if (t.name.StartsWith(BillboardRootPrefix, StringComparison.Ordinal))
				return true;
			if (t.name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void LogNoCitySid(object instance, object meta)
	{
		if (_loggedNoCitySid >= 24)
			return;
		var root = GetReleaseMapObjectRoot(instance);
		var rootName = root ? root.name : string.Empty;
		_loggedNoCitySid++;
		Plugin.LogSource?.LogInfo(
			"HoMM3 custom town billboard: map object without readable custom city sid root='"
			+ rootName
			+ "' instanceType='"
			+ (instance?.GetType().FullName ?? "?")
			+ "' metaType='"
			+ (meta?.GetType().FullName ?? "?")
			+ "'.");
	}

	private static void LogPropCityRouteMiss(string reason, object placedInstance, object routeObject, int? nodeId)
	{
		if (_loggedPropCityRouteMiss >= 18)
			return;
		var root = GetReleaseMapObjectRoot(placedInstance);
		var rootName = root ? root.name : string.Empty;
		var objectId = Homm3MapObjectPropCityResolver.TryGetIntMember(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields);
		var resolvedNodeId = nodeId ?? Homm3MapObjectPropCityResolver.TryGetIntMember(placedInstance, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields);
		_loggedPropCityRouteMiss++;
		Plugin.LogSource?.LogInfo(
			"HoMM3 custom town billboard: PropCity route miss reason='"
			+ reason
			+ "' root='"
			+ rootName
			+ "' object="
			+ (objectId.HasValue ? objectId.Value.ToString() : "?")
			+ " node="
			+ (resolvedNodeId.HasValue ? resolvedNodeId.Value.ToString() : "?")
			+ " placedType='"
			+ (placedInstance?.GetType().FullName ?? "?")
			+ "' routeType='"
			+ (routeObject?.GetType().FullName ?? "?")
			+ "'.");
	}

	private static void LogPropCityMemberSummary(string reason, object placedInstance, object meta, object routeObject)
	{
		if (_loggedPropCityMemberSummary >= 8)
			return;
		_loggedPropCityMemberSummary++;
		Plugin.LogSource?.LogInfo(
			"HoMM3 custom town billboard diag: PropCity member summary reason='"
			+ (reason ?? "?")
			+ "' placed=["
			+ DescribeReadableMembersForDiag(placedInstance)
			+ "] meta=["
			+ DescribeReadableMembersForDiag(meta)
			+ "] route=["
			+ DescribeReadableMembersForDiag(routeObject)
			+ "].");
	}

	private static string DescribeReadableMembersForDiag(object obj)
	{
		if (obj == null)
			return "(null)";
		try
		{
			var parts = new List<string>();
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var type = obj.GetType(); type != null && type != typeof(object) && parts.Count < 32; type = type.BaseType)
			{
				FieldInfo[] fields;
				try { fields = type.GetFields(flags); }
				catch { fields = Array.Empty<FieldInfo>(); }
				foreach (var field in fields)
				{
					if (parts.Count >= 32)
						break;
					if (!IsPropCityDiagnosticType(field.FieldType))
						continue;
					parts.Add(field.Name + ":" + field.FieldType.Name + "=" + FormatMemberValueForDiag(ReadFieldForDiag(field, obj)));
				}

			}
			return (obj.GetType().FullName ?? obj.GetType().Name) + " " + (parts.Count == 0 ? "(no simple members)" : string.Join(",", parts));
		}
		catch (Exception ex)
		{
			return (obj.GetType().FullName ?? obj.GetType().Name) + " (summary failed:" + ex.GetType().Name + ")";
		}
	}

	private static void ValidateBillboardPostconditions(
		GameObject prefabRoot,
		Transform billboardRoot,
		GameObject quadGo,
		MeshRenderer renderer,
		Material material,
		Texture texture,
		Renderer donorRenderer,
		string citySid,
		ManualLogSource log)
	{
		if (_postconditionDiagRemaining <= 0)
			return;
		var failures = new List<string>();
		if (!prefabRoot)
			failures.Add("root-missing");
		if (billboardRoot == null || !billboardRoot.gameObject)
			failures.Add("billboard-root-missing");
		else if (!billboardRoot.gameObject.activeSelf)
			failures.Add("billboard-root-inactive");
		if (!quadGo)
			failures.Add("quad-missing");
		else if (!quadGo.activeSelf)
			failures.Add("quad-inactive");
		if (!renderer)
			failures.Add("renderer-missing");
		else
		{
			if (!renderer.enabled)
				failures.Add("renderer-disabled");
			if (renderer.forceRenderingOff)
				failures.Add("renderer-force-off");
			if (donorRenderer && renderer.gameObject.layer != donorRenderer.gameObject.layer)
				failures.Add("layer-mismatch");
		}
		if (!material)
			failures.Add("material-missing");
		else if (!IsHexLitMaterial(material))
			failures.Add("material-not-hex-lit=" + (material.shader ? material.shader.name : "?"));
		if (!texture)
			failures.Add("texture-missing");

		var donorRenderersStillEnabled = 0;
		if (prefabRoot)
		{
			foreach (var candidate in prefabRoot.GetComponentsInChildren<Renderer>(true))
			{
				if (!candidate || !candidate.enabled)
					continue;
				if (billboardRoot != null && candidate.transform && candidate.transform.IsChildOf(billboardRoot))
					continue;
				// Only count this city's donor meshes — not unrelated section neighbors.
				if (!ShouldHideTownDonorRenderer(prefabRoot.transform, prefabRoot.transform, candidate.transform, citySid))
					continue;
				donorRenderersStillEnabled++;
			}
		}
		if (donorRenderersStillEnabled > 0)
			failures.Add("donor-renderers-enabled=" + donorRenderersStillEnabled);
		if (failures.Count == 0)
			return;

		_postconditionDiagRemaining--;
		log?.LogWarning(
			"HoMM3 custom town billboard: postcondition warning city='"
			+ (citySid ?? "?")
			+ "' reasons="
			+ string.Join(",", failures)
			+ " rootLayer="
			+ (prefabRoot ? prefabRoot.layer.ToString() : "?")
			+ " donorLayer="
			+ (donorRenderer ? donorRenderer.gameObject.layer.ToString() : "?")
			+ " quadLayer="
			+ (renderer ? renderer.gameObject.layer.ToString() : "?")
			+ " donor=["
			+ DescribeRendererFlags(donorRenderer)
			+ "] quad=["
			+ DescribeRendererFlags(renderer)
			+ "].");
	}

	private static bool IsPropCityDiagnosticType(Type type)
	{
		if (type == null)
			return false;
		if (type == typeof(string) || type == typeof(int) || type == typeof(uint) || type == typeof(short) || type == typeof(byte) || type == typeof(bool))
			return true;
		var name = type.FullName ?? type.Name;
		return name.IndexOf("Dictionary", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("List", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("Map", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("Prop", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("Object", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("Config", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static object ReadFieldForDiag(FieldInfo field, object obj)
	{
		try { return field.GetValue(obj); }
		catch (Exception ex) { return ex.GetType().Name; }
	}

	private static string FormatMemberValueForDiag(object value)
	{
		if (value == null)
			return "(null)";
		if (value is string s)
			return "'" + TrimForDiag(s, 64) + "'";
		if (value is bool b)
			return b ? "true" : "false";
		if (value is int or uint or short or byte)
			return value.ToString();
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string TrimForDiag(string value, int max)
	{
		if (string.IsNullOrEmpty(value) || value.Length <= max)
			return value ?? string.Empty;
		return value.Substring(0, max) + "...";
	}

	private static void LogSeenSid(string sid, object meta)
	{
		if (_loggedSeenSid >= 40)
			return;
		if (!Homm3CustomFactionRegistry.IsCustomCitySid(sid)
		    && sid.IndexOf("city", StringComparison.OrdinalIgnoreCase) < 0
		    && sid.IndexOf("homm3", StringComparison.OrdinalIgnoreCase) < 0
		    && sid.IndexOf("human", StringComparison.OrdinalIgnoreCase) < 0
		    && sid.IndexOf("dungeon", StringComparison.OrdinalIgnoreCase) < 0)
			return;
		_loggedSeenSid++;
		Plugin.LogSource?.LogInfo(
			"HoMM3 custom town billboard: observed map object sid='"
			+ sid
			+ "' customCity="
			+ Homm3CustomFactionRegistry.IsCustomCitySid(sid)
			+ " metaType='"
			+ (meta?.GetType().FullName ?? "?")
			+ "'.");
	}

	private static void NoteCitySeen(string citySid)
	{
		Homm3StrongholdDwellingMapBillboard.NoteCustomCitySeen(citySid);
	}

	private static bool TryLoadTextureImage(Texture2D texture, byte[] bytes)
	{
		if (!texture || bytes == null || bytes.Length == 0)
			return false;
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		return ImageConversion.LoadImage(texture, il2cppBytes);
	}

	private static Vector3 GetBillboardScale(BillboardAsset asset, Texture texture)
	{
		var visibleHeight = Math.Max(1, asset.VisibleHeight);
		var visibleWidth = Math.Max(1, asset.VisibleWidth);
		if (texture && texture.height > 0)
		{
			var width = asset.Height * visibleWidth / visibleHeight;
			var height = asset.Height * texture.height / visibleHeight;
			return new Vector3(width, height, 1f);
		}
		return new Vector3(asset.Height, asset.Height, 1f);
	}

	private static float GetBottomPaddingWorld(BillboardAsset asset, Texture texture, Vector3 billboardScale)
	{
		if (!texture || texture.height <= 0 || asset.BottomPaddingPixels <= 0)
			return 0f;
		return billboardScale.y * asset.BottomPaddingPixels / texture.height;
	}

	private static Mesh GetOrCreateQuadMesh()
	{
		if (_quadMesh)
			return _quadMesh;
		_quadMesh = new Mesh { name = "HOMM3_custom_town_billboard_quad" };
		_quadMesh.vertices = new[]
		{
			new Vector3(-0.5f, -0.5f, 0f),
			new Vector3(0.5f, -0.5f, 0f),
			new Vector3(-0.5f, 0.5f, 0f),
			new Vector3(0.5f, 0.5f, 0f)
		};
		_quadMesh.uv = new[] { new Vector2(0f, 0f), new Vector2(1f, 0f), new Vector2(0f, 1f), new Vector2(1f, 1f) };
		_quadMesh.uv2 = _quadMesh.uv;
		_quadMesh.colors = new[] { Color.white, Color.white, Color.white, Color.white };
		_quadMesh.tangents = new[] { new Vector4(1f, 0f, 0f, 1f), new Vector4(1f, 0f, 0f, 1f), new Vector4(1f, 0f, 0f, 1f), new Vector4(1f, 0f, 0f, 1f) };
		_quadMesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
		_quadMesh.RecalculateNormals();
		_quadMesh.RecalculateBounds();
		return _quadMesh;
	}

	private static void ClearRendererPropertyBlock(Renderer renderer)
	{
		try { renderer.SetPropertyBlock(null); }
		catch
		{
			var empty = new MaterialPropertyBlock();
			renderer.SetPropertyBlock(empty);
		}
	}

	private static string DescribeMaterial(Material m)
	{
		if (!m)
			return "(null)";
		return "name='" + (m.name ?? "?") + "' shader=" + (m.shader ? m.shader.name : "(null)") + " queue=" + m.renderQueue;
	}

	private static string DescribeRendererFlags(Renderer r)
	{
		if (!r)
			return "(null)";
		return "type="
		       + r.GetType().Name
		       + " name='"
		       + (r.name ?? "?")
		       + "' enabled="
		       + r.enabled
		       + " forceOff="
		       + r.forceRenderingOff
		       + " active="
		       + r.gameObject.activeInHierarchy
		       + " layer="
		       + r.gameObject.layer
		       + " renderLayerMask="
		       + r.renderingLayerMask;
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			try
			{
				var f = t.GetField(name, flags);
				if (f != null)
				{
					var value = f.GetValue(obj);
					if (value != null)
						return value;
				}
			}
			catch { }
			try
			{
				if (IsGeneratedInteropPropertyName(name))
					continue;
				var p = t.GetProperty(name, flags);
				if (p != null && p.GetIndexParameters().Length == 0)
				{
					var value = p.GetValue(obj);
					if (value != null)
						return value;
				}
			}
			catch { }
		}
		return null;
	}

	private static bool IsGeneratedInteropPropertyName(string name)
	{
		return !string.IsNullOrWhiteSpace(name)
		       && name.StartsWith("prop_", StringComparison.Ordinal);
	}

	private static object GetFirstMemberValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static IEnumerable<NamedMemberValue> EnumerateNamedMemberValues(object obj, string[] names)
	{
		if (obj == null || names == null)
			yield break;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				yield return new NamedMemberValue(names[i], value);
		}
	}

	private static object GetInheritedFieldValue(object obj, string name)
	{
		if (obj == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var f = t.GetField(name, flags);
			if (f == null)
				continue;
			try { return f.GetValue(obj); } catch { }
		}
		return null;
	}

	private static object InvokeFirstNoArg(object obj, Type returnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null)
			return null;
		var methods = GameMember.FindMethods(obj.GetType(), returnType, Type.EmptyTypes, symbol);
		for (var i = 0; i < methods.Length; i++)
		{
			try { return methods[i].Invoke(obj, null); } catch { }
		}
		return null;
	}

	private static object InvokeFirstNoArgByName(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = obj.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var t = type; t != null; t = t.BaseType)
			{
				MethodInfo method;
				try { method = t.GetMethod(name, flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null || method.IsSpecialName && !method.Name.StartsWith("get_", StringComparison.Ordinal))
					continue;
				try
				{
					var value = method.Invoke(obj, null);
					if (value != null)
						return value;
				}
				catch { }
			}
		}
		return null;
	}

	private static string SanitizeName(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "unknown";
		return value.Trim().Replace(' ', '_').Replace('/', '_').Replace('\\', '_').Replace(':', '_');
	}

	private static string DescribeTransformPath(Transform transform)
	{
		if (!transform)
			return "?";
		var names = new List<string>();
		for (var t = transform; t != null && names.Count < 8; t = t.parent)
			names.Add(t.name ?? "?");
		names.Reverse();
		return string.Join("/", names);
	}

	private sealed class RootCandidate
	{
		internal RootCandidate(string source, GameObject root)
		{
			Source = source;
			Root = root;
		}

		internal string Source { get; }
		internal GameObject Root { get; }
		internal int Score { get; set; }
	}

	private readonly struct NamedMemberValue
	{
		internal NamedMemberValue(string name, object value)
		{
			Name = name;
			Value = value;
		}

		internal string Name { get; }
		internal object Value { get; }
	}

	private readonly struct TownBillboardPlacement
	{
		internal TownBillboardPlacement(bool hasEntranceSide, int rotation, float entranceOffsetSign, string source)
		{
			HasEntranceSide = hasEntranceSide;
			Rotation = rotation;
			EntranceOffsetSign = entranceOffsetSign;
			Source = source;
		}

		internal bool HasEntranceSide { get; }
		internal int Rotation { get; }
		internal float EntranceOffsetSign { get; }
		internal string Source { get; }
	}

	private sealed class BillboardAsset
	{
		internal BillboardAsset(Texture2D texture, Material material, float height)
		{
			Texture = texture;
			Material = material;
			Height = height;
			VisibleWidth = texture ? texture.width : 1;
			VisibleHeight = texture ? Math.Max(1, texture.height - TextureBottomPaddingPixels) : 1;
			BottomPaddingPixels = texture ? TextureBottomPaddingPixels : 0;
		}

		internal Texture2D Texture { get; }
		internal Material Material { get; }
		internal float Height { get; }
		internal int VisibleWidth { get; }
		internal int VisibleHeight { get; }
		internal int BottomPaddingPixels { get; }
	}

	internal readonly struct TownBillboardScanResult
	{
		internal TownBillboardScanResult(int applied, int foundCityRoots, int unresolvedCityRoots)
		{
			Applied = applied;
			FoundCityRoots = foundCityRoots;
			UnresolvedCityRoots = unresolvedCityRoots;
		}

		internal int Applied { get; }
		internal int FoundCityRoots { get; }
		internal int UnresolvedCityRoots { get; }
	}

}

public sealed class Homm3TownBillboardPostLoadScanner : MonoBehaviour
{
	private const int FirstScanDelayFrames = 15;
	private const int ScanIntervalFrames = 120;
	private const int MaxScans = 4;

	private int _scanCount;
	private int _nextScanFrame;
	private string _lastScene;

	public Homm3TownBillboardPostLoadScanner(IntPtr ptr) : base(ptr) { }

	private void LateUpdate()
	{
		var scene = SceneManager.GetActiveScene();
		var sceneName = scene.name ?? string.Empty;
		if (!string.Equals(sceneName, _lastScene, StringComparison.Ordinal))
		{
			_lastScene = sceneName;
			_scanCount = 0;
			_nextScanFrame = Time.frameCount + FirstScanDelayFrames;
			Homm3CustomTownMapBillboard.ResetScenePlacementCache();
		}
		if (!string.Equals(sceneName, "worldLight", StringComparison.Ordinal))
			return;
		if (_scanCount >= MaxScans || Time.frameCount < _nextScanFrame)
			return;
		_scanCount++;
		_nextScanFrame = Time.frameCount + ScanIntervalFrames;
		var result = Homm3CustomTownMapBillboard.ReapplyLiveNamedCityRoots(Plugin.LogSource);
		if (result.Applied > 0)
			Plugin.LogSource?.LogInfo("HoMM3 custom town billboard post-load scanner: scan=" + _scanCount + " applied=" + result.Applied + ".");
	}
}

public sealed class Homm3TownBillboardSectionFinalizer : MonoBehaviour
{
	private const int FirstScanDelayFrames = 8;
	private const int ScanIntervalFrames = 20;
	private const int MaxScans = 12;

	private int _scanCount;
	private int _nextScanFrame;
	private string _reason;

	public Homm3TownBillboardSectionFinalizer(IntPtr ptr) : base(ptr) { }

	internal void Initialize(string reason)
	{
		_reason = reason ?? "?";
		_scanCount = 0;
		_nextScanFrame = Time.frameCount + FirstScanDelayFrames;
	}

	private void LateUpdate()
	{
		if (_nextScanFrame <= 0)
			Initialize(_reason);
		if (_scanCount >= MaxScans || Time.frameCount < _nextScanFrame)
			return;
		if (!gameObject || !gameObject.activeInHierarchy || !(gameObject.name ?? string.Empty).StartsWith("Section Root:", StringComparison.Ordinal))
		{
			Destroy(this);
			return;
		}

		_scanCount++;
		_nextScanFrame = Time.frameCount + ScanIntervalFrames;
		var result = Homm3CustomTownMapBillboard.ReapplyLiveNamedCityRootsUnder(gameObject, Plugin.LogSource);
		if (result.Applied > 0)
			Plugin.LogSource?.LogInfo("HoMM3 custom town billboard section finalizer: scan=" + _scanCount + " applied=" + result.Applied + " reason='" + (_reason ?? "?") + "'.");
		if (result.Applied > 0 || (result.FoundCityRoots > 0 && result.UnresolvedCityRoots == 0) || _scanCount >= MaxScans)
			Destroy(this);
	}
}

public sealed class Homm3TownBillboardDonorSuppressor : MonoBehaviour
{
	private static bool _typeRegistered;
	private static int _attachDiagRemaining = 12;

	private List<Renderer> _donorRenderers;
	private string _citySid;
	private Transform _suppressRoot;
	private Transform _placementRoot;

	public Homm3TownBillboardDonorSuppressor(IntPtr ptr) : base(ptr) { }

	internal static bool TryAttach(GameObject billboardRoot, List<Renderer> donorRenderers, string citySid, Transform suppressRoot, Transform placementRoot, ManualLogSource log)
	{
		if (!billboardRoot || !billboardRoot.transform)
			return false;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3TownBillboardDonorSuppressor>();
				_typeRegistered = true;
				log?.LogInfo("HoMM3 custom town billboard suppressor: registered Il2Cpp type.");
			}

			var existing = billboardRoot.GetComponent<Homm3TownBillboardDonorSuppressor>();
			var suppressor = existing != null && existing ? existing : billboardRoot.AddComponent<Homm3TownBillboardDonorSuppressor>();
			suppressor._donorRenderers = donorRenderers ?? new List<Renderer>();
			suppressor._citySid = citySid;
			suppressor._suppressRoot = suppressRoot ? suppressRoot : (billboardRoot.transform.parent ? billboardRoot.transform.parent : billboardRoot.transform);
			suppressor._placementRoot = placementRoot ? placementRoot : null;
			var disabled = suppressor.SuppressDonorRenderers();
			if (_attachDiagRemaining > 0)
			{
				_attachDiagRemaining--;
				log?.LogInfo(
					"HoMM3 custom town billboard suppressor: attached city='"
					+ (citySid ?? "?")
					+ "' donorRenderers="
					+ suppressor._donorRenderers.Count
					+ " initialDisabled="
					+ disabled
					+ ".");
			}
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom town billboard suppressor attach failed: " + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}

	private void Start()
	{
		SuppressDonorRenderers();
	}

	private void LateUpdate()
	{
		// Native map init can re-enable donor meshes after Start; keep them forced off so the
		// HoMM3 billboard is the only town visual (no silent dual mesh+billboard towns).
		SuppressDonorRenderers();
	}

	private int SuppressDonorRenderers()
	{
		if (_donorRenderers == null || !transform)
			return 0;

		var disabled = 0;
		for (var i = 0; i < _donorRenderers.Count; i++)
		{
			var renderer = _donorRenderers[i];
			if (!renderer || !renderer.transform || renderer.transform.IsChildOf(transform))
				continue;
			var changed = false;
			if (renderer.enabled)
			{
				renderer.enabled = false;
				changed = true;
			}
			if (!renderer.forceRenderingOff)
			{
				renderer.forceRenderingOff = true;
				changed = true;
			}
			if (changed)
				disabled++;
		}
		disabled += SuppressLateCitySidRenderers();
		return disabled;
	}

	private int SuppressLateCitySidRenderers()
	{
		if (!_suppressRoot || string.IsNullOrWhiteSpace(_citySid))
			return 0;
		var disabled = 0;
		var renderers = _suppressRoot.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (!renderer || !renderer.transform)
				continue;
			if (RendererIsBillboardMarker(renderer.transform))
				continue;
			if (!ShouldHideTownDonorRenderer(renderer.transform))
				continue;
			var changed = false;
			if (renderer.enabled)
			{
				renderer.enabled = false;
				changed = true;
			}
			if (!renderer.forceRenderingOff)
			{
				renderer.forceRenderingOff = true;
				changed = true;
			}
			if (changed)
				disabled++;
		}
		return disabled;
	}

	private bool ShouldHideTownDonorRenderer(Transform rendererTransform)
	{
		if (!_suppressRoot || !rendererTransform)
			return false;
		if (_placementRoot && _placementRoot != _suppressRoot && rendererTransform.IsChildOf(_placementRoot))
			return true;
		if (RendererBelongsToCitySid(rendererTransform))
			return true;
		if (_placementRoot && _placementRoot.parent == _suppressRoot && IsNativeTownDonorRenderer(rendererTransform))
			return true;
		return false;
	}

	private bool RendererBelongsToCitySid(Transform rendererTransform)
	{
		for (var t = rendererTransform; t != null && t != _suppressRoot.parent; t = t.parent)
		{
			var name = t.name ?? string.Empty;
			if (Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(name, _citySid))
				return true;
			if (name.IndexOf("_homm3_" + _citySid + "_billboard", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	private bool IsNativeTownDonorRenderer(Transform rendererTransform)
	{
		for (var t = rendererTransform; t != null && t != _suppressRoot.parent; t = t.parent)
		{
			if (t == _suppressRoot || t == _placementRoot)
				continue;
			if (t.parent != _suppressRoot || !Homm3CustomTownMapBillboard.IsNearPlacementRoot(t, _placementRoot))
				continue;
			var name = t.name ?? string.Empty;
			if (name.EndsWith("_city(Clone)", StringComparison.OrdinalIgnoreCase)
			    || name.EndsWith("_town(Clone)", StringComparison.OrdinalIgnoreCase)
			    || name.IndexOf("city(Clone)", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	private static bool RendererIsBillboardMarker(Transform rendererTransform)
	{
		for (var t = rendererTransform; t != null; t = t.parent)
		{
			var name = t.name ?? string.Empty;
			if (name.StartsWith("homm3_custom_city_billboard_", StringComparison.Ordinal))
				return true;
			if (name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
				return true;
			if (name == "homm3_artifact_billboard"
			    || name == "homm3_stronghold_dwelling_billboard"
			    || name == "homm3_stronghold_city_homm3_billboard")
				return true;
		}
		return false;
	}
}
