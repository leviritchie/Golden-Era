using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdDwellingMapBillboard
{
	private const string VisualRootName = "homm3_stronghold_dwelling_billboard";
	private const float BillboardHeight = 2.25f;
	private const float GroundClearance = 0.06f;
	private const float BillboardSouthOffset = 0.22f;
	private const string PropCityProbeFlagName = "homm3_dwelling_prop_city_probe.flag";

	private static readonly Dictionary<string, Texture2D> TexturesBySid = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Material> MaterialsBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMetaApplied = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedLiveApplied = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissingImage = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedAmbiguousDonorAlias = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedDonorAliasRefused = new(StringComparer.Ordinal);
	private static readonly HashSet<string> AppliedLiveRootKeys = new(StringComparer.Ordinal);
	private static readonly HashSet<string> SeenCitySids = new(StringComparer.Ordinal);
	private static readonly List<PendingDungeonBarracksEntry> PendingDungeonBarracks = new();
	private static readonly Dictionary<int, PendingRandomHireMapObjectEntry> PendingRandomHireMapObjectsById = new();
	private static readonly Dictionary<int, string> ResolvedRandomHireDwellingById = new();
	private static readonly Dictionary<int, string> CustomFactionSidByOwnerSide = new();
	private static readonly Dictionary<int, List<PendingOwnerSideHireEntry>> PendingOwnerSideHireBySide = new();
	private static readonly HashSet<int> LoggedCityOwnerSides = new();
	private static readonly HashSet<int> LoggedHireIdentityStamps = new();
	private static object CurrentMapInstance;
	private static string CurrentMapSceneKey;
	private static Mesh _quadMesh;
	private static bool _registered;
	private static readonly HashSet<string> LoggedDonorAliases = new(StringComparer.Ordinal);
	private static readonly HashSet<int> LoggedRandomHireAmbiguous = new();
	private static int _diagRemaining = 14;
	private static int _loggedDirectDwellingSeen;
	private static int _loggedRootMissing;
	private static int _loggedApplyFailed;
	private static int _loggedQueuedAlias;
	private static int _loggedRandomHireResolved;
	private static int _loggedRandomHireEntered;
	private static int _loggedRandomHireMissingId;
	private static int _loggedRandomHireNoMatch;
	private static int _loggedHireEntered;
	private static int _loggedHireNoMatch;
	private static int _loggedHireShapeSkip;
	private static int _loggedPropCityProbe;
	private static int _loggedMapObjectSamples;
	private static int _loggedMissingSidBreakdown;

	internal static bool IsRegistered => _registered;

	private sealed class PendingDungeonBarracksEntry
	{
		internal GameObject Root;
		internal object Meta;
		internal string RawSid;
		internal string CustomDwellingSid;
		internal string RequiredCitySid;
	}

	private sealed class PendingRandomHireMapObjectEntry
	{
		internal GameObject Root;
		internal object Meta;
		internal string RawSid;
	}

	private sealed class PendingOwnerSideHireEntry
	{
		internal int MapObjectId;
		internal int OwnerSide;
		internal string RawSid;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		try
		{
			var metaType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId, GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints);
			if (metaType == null)
			{
				log?.LogWarning("HoMM3 custom dwelling billboard: MapObjectMeta type not found.");
				return;
			}
			var metaPatched = 0;
			foreach (var m in FindMapObjectMetaResourceHooks(metaType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3StrongholdDwellingMapBillboard), nameof(PostfixMapObjectMetaInitResources)));
				metaPatched++;
			}

			var objectType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId, GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints);
			if (objectType == null)
			{
				log?.LogWarning("HoMM3 custom dwelling billboard: MapObject type not found.");
				return;
			}
			var objectPatched = 0;
			foreach (var m in FindMapObjectInitHooks(objectType, metaType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3StrongholdDwellingMapBillboard), nameof(PostfixMapObjectInit)));
				objectPatched++;
			}

			_registered = metaPatched > 0 || objectPatched > 0;
			log?.LogInfo("HoMM3 custom dwelling billboard: registered map-object hooks (meta=" + metaPatched + ", live=" + objectPatched + ").");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom dwelling billboard: hook registration failed: " + ex);
		}
	}

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
		if (_registered)
			return;
		if (harmony == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized.");
			return;
		}

		try
		{
			var metaType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId, GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints);
			if (metaType == null)
				throw new InvalidOperationException("release Hex.Map map-object metadata type did not resolve.");
			var metaPatched = 0;
			// Release bvd.Init(ObjectConfig) is too early for safe reflective ObjectConfig.id reads.
			// The live bvb.Init(...) hook is sufficient for visible dwellings and avoids native AVs.

			var objectType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId, GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints);
			if (objectType == null)
				throw new InvalidOperationException("release live placed map-object type did not resolve.");
			var objectPatched = 0;
			foreach (var m in FindReleaseMapObjectInitHooks(objectType, metaType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3StrongholdDwellingMapBillboard), nameof(PostfixReleaseMapObjectInit)));
				objectPatched++;
			}

			var randomHirePatched = 0;
			var randomHireType = GetFirstHexType(GameSymbols.CustomDwellingRandomHire.RandomHireWorldObjectTypeId, GameSymbols.CustomDwellingRandomHire.RandomHireWorldObjectTypeHints);
			foreach (var m in FindRandomHireWorldObjectInitHooks(randomHireType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3StrongholdDwellingMapBillboard), nameof(PostfixRandomHireWorldObjectInit)));
				randomHirePatched++;
			}
			if (required && randomHirePatched == 0)
				throw new InvalidOperationException("no release random-hire world-object Init surfaces resolved.");

			var hirePatched = 0;
			var hireType = GetFirstHexType(GameSymbols.CustomDwellingHire.HireWorldObjectTypeId, GameSymbols.CustomDwellingHire.HireWorldObjectTypeHints);
			if (hireType == null && GameBuild.Kind == GameBuildKind.Current)
				hireType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CustomDwellingHireWorldObject);
			foreach (var m in FindHireWorldObjectInitHooks(hireType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3StrongholdDwellingMapBillboard), nameof(PostfixHireWorldObject)));
				hirePatched++;
			}
			if (required && hirePatched == 0)
				log?.LogInfo("HoMM3 custom dwelling billboard release slice: no verified hire world-object Init surfaces resolved; hire payload aliasing is skipped (map-object/random-hire/city hooks remain).");

			var cityPatched = 0;
			var cityType = GetFirstHexType(GameSymbols.CustomDwellingCity.CityWorldObjectTypeId, GameSymbols.CustomDwellingCity.CityWorldObjectTypeHints);
			foreach (var m in FindCityWorldObjectInitHooks(cityType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3StrongholdDwellingMapBillboard), nameof(PostfixCityWorldObject)));
				cityPatched++;
			}
			if (required && cityPatched == 0)
				throw new InvalidOperationException("no release city world-object Init surfaces resolved.");

			_registered = true;
			log?.LogInfo("HoMM3 custom dwelling billboard release slice: registered map-object hooks (meta=" + metaPatched + ", live=" + objectPatched + ", randomHire=" + randomHirePatched + ", hire=" + hirePatched + ", city=" + cityPatched + ").");
		}
		catch (Exception ex)
		{
			if (required)
			{
				log?.LogFatal("HoMM3 custom dwelling billboard release slice: required hook registration failed: " + ex);
				throw;
			}
			log?.LogWarning("HoMM3 custom dwelling billboard release slice: hook registration failed: " + ex);
		}
	}

	/// <summary>
	/// Fail-closed path existence check only. Decode stays in <see cref="GetOrCreateTexture"/> on first map apply.
	/// </summary>
	internal static int ValidateManifestTexturePathsOrFail(ManualLogSource log)
	{
		var validated = 0;
		foreach (var dwellingSid in Homm3CustomFactionRegistry.EnumerateDirectDwellingSids())
		{
			var path = ResolveImagePath(dwellingSid);
			if (path == null || !File.Exists(path))
				throw new InvalidOperationException("Failed to validate HoMM3 dwelling billboard texture path for " + dwellingSid + ".");
			validated++;
		}
		log?.LogInfo("HoMM3 custom dwelling billboard: validated " + validated + " texture path(s); decode deferred until map apply.");
		return validated;
	}

	internal static int PrewarmManifestTextures(ManualLogSource log)
	{
		return ValidateManifestTexturePathsOrFail(log);
	}

	internal static void NoteStrongholdCitySeen()
	{
		NoteCustomCitySeen("homm3_stronghold_city");
	}

	internal static void NoteCustomCitySeen(string citySid)
	{
		if (string.IsNullOrWhiteSpace(citySid))
			return;
		// Land-on visit-gate clones must register under the canonical city SID so
		// donor-alias dwelling gates (SeenCitySids.Contains(alias.CitySid)) succeed.
		var canonical = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(citySid.Trim());
		if (!SeenCitySids.Add(canonical))
			return;
		FlushPendingDungeonBarracks(canonical);
	}

	private static MethodInfo[] FindMapObjectMetaResourceHooks(Type metaType)
	{
		if (metaType == null)
			return Array.Empty<MethodInfo>();
		var list = new List<MethodInfo>();
		foreach (var m in metaType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (!m.IsSpecialName && m.ReturnType == typeof(void) && m.GetParameters().Length == 0)
				list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindMapObjectInitHooks(Type objectType, Type metaType)
	{
		if (objectType == null)
			return Array.Empty<MethodInfo>();
		var list = new List<MethodInfo>();
		foreach (var m in objectType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			var ps = m.GetParameters();
			if (m.ReturnType == typeof(void) && ps.Length == 5 && (metaType == null || ps[1].ParameterType == metaType))
				list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindReleaseMapObjectMetaResourceHooks(Type metaType)
	{
		if (metaType == null)
			return Array.Empty<MethodInfo>();
		var list = new List<MethodInfo>();
		foreach (var m in metaType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (!string.Equals(m.Name, "Init", StringComparison.Ordinal))
				continue;
			if (m.IsSpecialName || m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length == 1 && ps[0].ParameterType.FullName == "Hex.Map.ObjectConfig")
				list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindReleaseMapObjectInitHooks(Type objectType, Type metaType)
	{
		return GameMember.FindPlacedObjectInitMethods(objectType, metaType);
	}

	private static MethodInfo[] FindRandomHireWorldObjectInitHooks(Type randomHireType)
	{
		return FindWorldObjectInitHooks(randomHireType);
	}

	private static MethodInfo[] FindHireWorldObjectInitHooks(Type hireType)
	{
		var named = FindWorldObjectInitHooks(hireType);
		if (named.Length > 0)
			return named;
		if (hireType == null)
			return Array.Empty<MethodInfo>();
		var list = new List<MethodInfo>();
		foreach (var m in hireType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.IsSpecialName || m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 1 || !IsHirePayloadType(ps[0].ParameterType))
				continue;
			list.Add(m);
		}
		if (list.Count > 0)
			return list.ToArray();
		if (!TypeHasHirePayloadSurface(hireType))
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: skipping stale hire world-object type "
			                             + hireType.Name
			                             + " because it has no ObjHire/ObjHireConfig fields, properties, or one-arg init payloads.");
			return Array.Empty<MethodInfo>();
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindCityWorldObjectInitHooks(Type cityType)
	{
		var named = FindWorldObjectInitHooks(cityType);
		if (named.Length > 0)
			return named;
		if (cityType == null)
			return Array.Empty<MethodInfo>();
		var list = new List<MethodInfo>();
		foreach (var m in GameMember.FindMethods(
		         cityType,
		         typeof(void),
		         Type.EmptyTypes,
		         GameSymbols.CustomDwellingCity.CityWorldObjectInit))
		{
			if (m.IsSpecialName || m.GetParameters().Length != 0)
				continue;
			list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindWorldObjectInitHooks(Type worldObjectType)
	{
		if (worldObjectType == null)
			return Array.Empty<MethodInfo>();
		var list = new List<MethodInfo>();
		foreach (var m in worldObjectType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.IsSpecialName || m.ReturnType != typeof(void))
				continue;
			if (m.GetParameters().Length != 0)
				continue;
			if (!string.Equals(m.Name, "Init", StringComparison.Ordinal))
				continue;
			list.Add(m);
		}
		return list.ToArray();
	}

	private static bool TypeHasHirePayloadSurface(Type type)
	{
		if (type == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var t = type; t != null && t != typeof(object); t = t.BaseType)
		{
			foreach (var f in t.GetFields(flags))
			{
				if (IsHirePayloadType(f.FieldType))
					return true;
			}
			foreach (var p in t.GetProperties(flags))
			{
				if (p.GetIndexParameters().Length == 0 && IsHirePayloadType(p.PropertyType))
					return true;
			}
		}
		return false;
	}

	private static bool IsHirePayloadType(Type type)
	{
		var name = type?.FullName ?? type?.Name;
		return !string.IsNullOrEmpty(name)
		       && (name.EndsWith(".ObjHire", StringComparison.Ordinal)
		           || name.EndsWith(".ObjHireConfig", StringComparison.Ordinal)
		           || string.Equals(type.Name, "ObjHire", StringComparison.Ordinal)
		           || string.Equals(type.Name, "ObjHireConfig", StringComparison.Ordinal));
	}

	private static bool HasHirePayloadShape(object hireData, object hireConfig)
	{
		if (GetFirstMemberValue(hireData, GameSymbols.CustomDwellingHire.HireDataConfigSidFields) is string rawSid
		    && !string.IsNullOrWhiteSpace(rawSid))
			return true;
		if (GetFirstMemberValue(hireData, GameSymbols.CustomDwellingHire.HireDataGuardUnitsFields) != null)
			return true;
		if (GetFirstMemberValue(hireConfig, GameSymbols.CustomDwellingHire.HireConfigUnitsDataFields) != null)
			return true;
		if (GetFirstMemberValue(hireConfig, GameSymbols.CustomDwellingHire.HireConfigUnitsFields) != null)
			return true;
		return GetFirstMemberValue(hireConfig, GameSymbols.CustomDwellingHire.HireConfigFactionFields) is string faction
		       && !string.IsNullOrWhiteSpace(faction);
	}

	private static void PostfixHireWorldObject(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;
			var hireData = (__args != null && __args.Length > 0) ? __args[0] : null;
			hireData ??= GetFirstMemberValue(__instance, GameSymbols.CustomDwellingHire.WorldObjectHireDataFields);
			var hireConfig = GetFirstMemberValue(__instance, GameSymbols.CustomDwellingHire.WorldObjectHireConfigFields);
			if (!HasHirePayloadShape(hireData, hireConfig))
			{
				if (_loggedHireShapeSkip < 20)
				{
					_loggedHireShapeSkip++;
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: hire postfix skipped non-hire payload instance="
					                           + DescribeObject(__instance)
					                           + " data=" + DescribeObject(hireData)
					                           + " config=" + DescribeObject(hireConfig) + ".");
				}
				return;
			}
			var mapObjectId = GetMapObjectId(hireData);
			if (mapObjectId < 0)
				return;

			var rawSid = GetFirstMemberValue(hireData, GameSymbols.CustomDwellingHire.HireDataConfigSidFields) as string;
			if (_loggedHireEntered < 30)
			{
				_loggedHireEntered++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: hire postfix entered mapObjectId=" + mapObjectId
				                           + " instance=" + DescribeObject(__instance)
				                           + " data=" + DescribeObject(hireData)
				                           + " config=" + DescribeObject(hireConfig) + ".");
			}
			if (!TryResolveHireDwellingSid(mapObjectId, hireData, hireConfig, out var dwellingSid))
				return;

			ResolvedRandomHireDwellingById[mapObjectId] = dwellingSid;
			ApplyResolvedHireIdentity(hireData, rawSid, dwellingSid, mapObjectId);
			ApplyResolvedRandomHireDwelling(mapObjectId, rawSid, dwellingSid, "hire-payload");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: release hire world-object postfix failed: " + ex.Message);
		}
	}

	private static void PostfixCityWorldObject(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;
			var cityData = (__args != null && __args.Length > 0) ? __args[0] : null;
			cityData ??= GetFirstMemberValue(__instance, GameSymbols.CustomDwellingCity.WorldObjectCityDataFields);
			var cityConfig = GetFirstMemberValue(__instance, GameSymbols.CustomDwellingCity.WorldObjectCityConfigFields);
			RememberCustomCityOwnerSide(cityData, cityConfig);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: release city world-object postfix failed: " + ex.Message);
		}
	}

	private static void PostfixReleaseMapObjectMetaInitResources(object __instance)
	{
		try
		{
			TryReplaceMetaPrefabReflective(__instance);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: release MapObjectMeta postfix failed: " + ex.Message);
		}
	}

	private static void PostfixMapObjectMetaInitResources(object __instance)
	{
		try
		{
			if (!TryGetStrongholdDwellingSid(__instance, out var sid))
				return;
			if (!TryGetFirstPrefabArray(__instance, out var prefs, out var prefab) || !prefab || HasVisual(prefab))
				return;
			var clone = UnityEngine.Object.Instantiate(prefab);
			if (!clone)
				return;
			if (!ApplyBillboard(clone, sid, Plugin.LogSource))
			{
				UnityEngine.Object.Destroy(clone);
				return;
			}
			SetFirstPrefab(prefs, clone);
			TrySetMemberValue(__instance, "IsCombinedGeometryOk", false);
			TrySetMemberValue(__instance, "<IsCombinedGeometryOk>k__BackingField", false);
			TrySetMemberValue(__instance, "buxc", false);
			TrySetMemberValue(__instance, "<buxc>k__BackingField", false);
			if (LoggedMetaApplied.Add(sid))
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: replaced MapObjectMeta prefab for " + sid + ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: MapObjectMeta postfix failed: " + ex.Message);
		}
	}

	private static void PostfixReleaseMapObjectInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;
			ResetMapStateIfChanged(__args != null && __args.Length > 0 ? __args[0] : null);
			var meta = (__args != null && __args.Length > 1) ? __args[1] : null;
			meta ??= GetReleaseMapObjectMeta(__instance);
			var placedSid = DeobfInteropCompat.TryGetPlacedMapObjectSid(__instance, out var compatSid)
				? compatSid
				: GetPlacedObjectSidReflective(__instance);
			var rawSid = placedSid ?? GetConfigSidReflective(meta);
			LogMapObjectSample(__instance, __args != null && __args.Length > 0 ? __args[0] : null, rawSid, meta);
			if (Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(rawSid, out _, out _))
			{
				NoteCustomCitySeen(rawSid);
				return;
			}
			var root = GetReleaseMapObjectRoot(__instance);
			var mapObjectId = GetReleaseMapObjectId(__instance, __args);
			var nodeId = TryGetIntArg(__args, 2);
			if (IsUnknownSid(rawSid) && root && TryResolveCustomDwellingSid(root.name, out var rootDwellingSid, out _))
				rawSid = rootDwellingSid;
			if (mapObjectId >= 0 && root)
			{
				var entry = new PendingRandomHireMapObjectEntry { Root = root, Meta = meta, RawSid = rawSid };
				PendingRandomHireMapObjectsById[mapObjectId] = entry;
				if (ResolvedRandomHireDwellingById.TryGetValue(mapObjectId, out var resolvedRandomHireSid))
				{
					ApplyResolvedRandomHireDwelling(mapObjectId, rawSid, resolvedRandomHireSid, "map-object-init");
					return;
				}
			}
			if (TryResolvePropCityDonorDwellingSid(__instance, __args != null && __args.Length > 0 ? __args[0] : null, rawSid, mapObjectId, out var propCitySid))
			{
				if (!root)
				{
					if (_loggedRootMissing < 20)
					{
						_loggedRootMissing++;
						Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: resolved PropCity donor sid='" + rawSid + "' -> '" + propCitySid + "' but map-object root was not readable.");
					}
					return;
				}
				if (HasAppliedLiveRoot(root, propCitySid))
				{
					EnsureAppliedBillboardSuppressesDonor(root, propCitySid);
					return;
				}
				if (!ApplyBillboard(root, propCitySid, Plugin.LogSource))
				{
					if (_loggedApplyFailed < 20)
					{
						_loggedApplyFailed++;
						Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: failed to apply PropCity donor billboard for sid='" + propCitySid + "' root='" + (root ? root.name : "?") + "'.");
					}
					return;
				}
				MarkAppliedLiveRoot(root, propCitySid);
				ResolvedRandomHireDwellingById[mapObjectId] = propCitySid;
				if (LoggedLiveApplied.Add(propCitySid))
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: applied live billboard to " + propCitySid + " via PropCity donor alias.");
				return;
			}
			if (root && IsRandomHireRootName(root.name)
			    && TryResolvePropRandomHireNativeBiomeDwellingSid(__instance, __args != null && __args.Length > 0 ? __args[0] : null, mapObjectId, nodeId, out var propRandomHireSid))
			{
				if (HasAppliedLiveRoot(root, propRandomHireSid))
				{
					EnsureAppliedBillboardSuppressesDonor(root, propRandomHireSid);
					return;
				}
				if (!ApplyBillboard(root, propRandomHireSid, Plugin.LogSource))
				{
					if (_loggedApplyFailed < 20)
					{
						_loggedApplyFailed++;
						Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: failed to apply PropRandomHire native-biome billboard for sid='" + propRandomHireSid + "' root='" + (root ? root.name : "?") + "'.");
					}
					return;
				}
				MarkAppliedLiveRoot(root, propRandomHireSid);
				ResolvedRandomHireDwellingById[mapObjectId] = propRandomHireSid;
				if (LoggedLiveApplied.Add(propRandomHireSid))
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: applied live billboard to " + propRandomHireSid + " via PropRandomHire native biome.");
				return;
			}
			LogPropRandomHireProbe(__instance, __args != null && __args.Length > 0 ? __args[0] : null, mapObjectId, rawSid, nodeId);
			var hasCustomDwelling = TryResolveCustomDwellingSid(rawSid, out var sid, out var waitsForCitySid);
			if (!hasCustomDwelling && waitsForCitySid == null)
				return;
			if (hasCustomDwelling && _loggedDirectDwellingSeen < 40)
			{
				_loggedDirectDwellingSeen++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: resolved map object sid='" + rawSid + "' -> '" + sid + "'.");
			}
			if (!root)
			{
				if (_loggedRootMissing < 20)
				{
					_loggedRootMissing++;
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: matched sid='" + (sid ?? rawSid ?? "?") + "' but map-object root was not readable.");
				}
				return;
			}
			if (waitsForCitySid != null)
			{
				if (_loggedQueuedAlias < 20)
				{
					_loggedQueuedAlias++;
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: queued donor barracks sid='" + rawSid + "' until matching custom city is seen.");
				}
				QueuePendingBarracksAliases(root, meta, rawSid, sid, waitsForCitySid);
				return;
			}
			if (HasAppliedLiveRoot(root, sid))
			{
				EnsureAppliedBillboardSuppressesDonor(root, sid);
				return;
			}
			if (!ApplyBillboard(root, sid, Plugin.LogSource))
			{
				if (_loggedApplyFailed < 20)
				{
					_loggedApplyFailed++;
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: failed to apply billboard for sid='" + sid + "' root='" + (root ? root.name : "?") + "'.");
				}
				return;
			}
			MarkAppliedLiveRoot(root, sid);
			if (LoggedLiveApplied.Add(sid))
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: applied live billboard to " + sid + ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: release MapObject.Init postfix failed: " + ex.Message);
		}
	}

	private static void PostfixRandomHireWorldObjectInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;
			var randomHireData = (__args != null && __args.Length > 0) ? __args[0] : null;
			randomHireData ??= GetFirstMemberValue(__instance, GameSymbols.CustomDwellingRandomHire.WorldObjectRandomHireDataFields);
			var dataObject = GetFirstMemberValue(__instance, GameSymbols.CustomDwellingRandomHire.WorldObjectDataFields);
			dataObject ??= randomHireData;
			if (_loggedRandomHireEntered < 40)
			{
				_loggedRandomHireEntered++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: random-hire postfix entered instance=" + DescribeObject(__instance)
				                           + " arg0=" + DescribeObject(__args != null && __args.Length > 0 ? __args[0] : null)
				                           + " data=" + DescribeObject(randomHireData)
				                           + " dataObject=" + DescribeObject(dataObject)
				                           + " configField=" + DescribeObject(GetFirstMemberValue(__instance, GameSymbols.CustomDwellingRandomHire.WorldObjectRandomHireConfigFields)) + ".");
			}
			var mapObjectId = GetMapObjectId(dataObject);
			if (mapObjectId < 0)
			{
				if (_loggedRandomHireMissingId < 40)
				{
					_loggedRandomHireMissingId++;
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: random-hire postfix has no map object id; instanceMembers="
					                           + DescribeAvailableMembers(__instance, 18)
					                           + " dataMembers=" + DescribeAvailableMembers(randomHireData, 18)
					                           + " dataObjectMembers=" + DescribeAvailableMembers(dataObject, 18) + ".");
				}
				return;
			}

			var randomHireConfig = GetFirstMemberValue(__instance, GameSymbols.CustomDwellingRandomHire.WorldObjectRandomHireConfigFields);
			if (!TryResolveRandomHireDwellingSid(mapObjectId, randomHireData, randomHireConfig, out var dwellingSid))
				return;

			ResolvedRandomHireDwellingById[mapObjectId] = dwellingSid;
			ApplyResolvedRandomHireDwelling(mapObjectId, null, dwellingSid, "random-hire-init");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: release random-hire Init postfix failed: " + ex.Message);
		}
	}

	private static void PostfixMapObjectInit(object __instance)
	{
		try
		{
			if (__instance == null)
				return;
			var meta = GetReleaseMapObjectMeta(__instance);
			var rawSid = GetPlacedObjectSidReflective(__instance) ?? GetConfigSidReflective(meta);
			if (Homm3CustomFactionRegistry.TryGetCityMapBillboardAsset(rawSid, out _, out _))
			{
				NoteCustomCitySeen(rawSid);
				return;
			}
			if (!TryGetStrongholdDwellingSid(meta, out var sid))
				return;
			var root = GetReleaseMapObjectRoot(__instance);
			if (!root)
				return;
			if (HasAppliedLiveRoot(root, sid))
			{
				EnsureAppliedBillboardSuppressesDonor(root, sid);
				return;
			}
			if (!ApplyBillboard(root, sid, Plugin.LogSource))
				return;
			MarkAppliedLiveRoot(root, sid);
			if (LoggedLiveApplied.Add(sid))
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: applied live billboard to " + sid + ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: MapObject.Init postfix failed: " + ex.Message);
		}
	}

	private static bool TryReplaceMetaPrefabReflective(object meta)
	{
		if (!TryGetStrongholdDwellingSidReflective(meta, out var sid))
			return false;
		if (!TryGetFirstPrefabArrayReflective(meta, out var prefs, out var prefab) || !prefab || HasVisual(prefab))
			return false;
		var clone = UnityEngine.Object.Instantiate(prefab);
		if (!clone)
			return false;
		if (!ApplyBillboard(clone, sid, Plugin.LogSource))
		{
			UnityEngine.Object.Destroy(clone);
			return false;
		}
		SetFirstPrefab(prefs, clone);
		TrySetMemberValue(meta, "IsCombinedGeometryOk", false);
		TrySetMemberValue(meta, "<IsCombinedGeometryOk>k__BackingField", false);
		TrySetMemberValue(meta, "buxc", false);
		TrySetMemberValue(meta, "<buxc>k__BackingField", false);
		TrySetMemberValue(meta, "bvlq", false);
		TrySetMemberValue(meta, "_bvlq_k__BackingField", false);
		TrySetMemberValue(meta, "bvlp", false);
		TrySetMemberValue(meta, "<bvlp>k__BackingField", false);
		TrySetMemberValue(meta, "bvnd", false);
		TrySetMemberValue(meta, "<bvnd>k__BackingField", false);
		if (LoggedMetaApplied.Add(sid))
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: replaced MapObjectMeta prefab for " + sid + ".");
		return true;
	}

	private static bool ApplyDwellingMapBuildingMesh(
		GameObject root,
		string sid,
		string relativePath,
		ManualLogSource log)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return false;

		sid = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(sid) ?? sid;

		// Transient random-hire / spawner roots receive aliased SIDs before the durable barracks_*
		// child exists — painting here left wrong meshes on neighboring roots. Soft-skip until the
		// exact dwelling root owns the apply.
		if (IsTransientDwellingMeshRoot(root))
		{
			log?.LogInfo(
				"HoMM3 dwelling map mesh: soft-skip sid='"
				+ sid
				+ "' root='"
				+ (root.name ?? "?")
				+ "' — waiting for durable exact dwelling root.");
			return false;
		}

		if (TryGetExactCustomDwellingRootSid(root, out var rootSid)
		    && !string.Equals(rootSid, sid, StringComparison.OrdinalIgnoreCase))
		{
			log?.LogError(
				"HoMM3 dwelling map mesh: refuse sid/root mismatch sid='"
				+ sid
				+ "' root='"
				+ (root.name ?? "?")
				+ "' rootSid='"
				+ rootSid
				+ "' (hook resolved the wrong dwelling for this instance).");
			return false;
		}

		DestroyOrphanDwellingMeshes(root, sid);

		var meshRootName = Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeDwellingMeshName(sid);
		var existingMesh = root.transform.Find(meshRootName);
		if (existingMesh && existingMesh.gameObject.activeSelf)
		{
			var existingRenderers = existingMesh.GetComponentsInChildren<MeshRenderer>(true);
			if (existingRenderers != null)
			{
				for (var i = 0; i < existingRenderers.Length; i++)
				{
					var r = existingRenderers[i];
					if (r && r.enabled && !r.forceRenderingOff && r.sharedMaterial)
					{
						HideExistingRenderers(root);
						existingMesh.gameObject.SetActive(true);
						if (Homm3MapBuildingMeshBundle.TryGetEntry(relativePath, out var existingEntry))
						{
							Homm3MapBuildingMeshProjectedFx.TryAttachForCatalogEntry(
								existingMesh.gameObject,
								existingEntry,
								log);
							Homm3MeshFx.TryAttachForMapBuilding(
								existingMesh.gameObject,
								existingEntry,
								log);
							Homm3MapBuildingAnim.TryAttachForMapBuilding(
								existingMesh.gameObject,
								existingEntry,
								FindBestMapDonorRenderer(root),
								log);
						}
						return true;
					}
				}
			}
		}

		if (!Homm3MapBuildingMeshBundle.TryLoadPrefab(relativePath, out var prefab, out var entry, log) || !prefab)
		{
			log?.LogError(
				"HoMM3 dwelling map mesh: prefab load failed for sid='"
				+ sid
				+ "' path='"
				+ relativePath
				+ "'; refuse apply (catalog hit — no PNG fallback).");
			return false;
		}

		HideExistingRenderers(root);
		var staleBillboard = root.transform.Find(VisualRootName);
		if (staleBillboard)
			UnityEngine.Object.Destroy(staleBillboard.gameObject);
		if (existingMesh)
			UnityEngine.Object.Destroy(existingMesh.gameObject);

		var donor = FindBestMapDonorRenderer(root);
		var instance = UnityEngine.Object.Instantiate(prefab, root.transform, false);
		instance.name = meshRootName;
		instance.layer = root.layer;
		var authoredScale = instance.transform.localScale;
		if (authoredScale.sqrMagnitude < 1e-8f)
			authoredScale = Vector3.one;
		instance.transform.localScale = authoredScale * Homm3MapBuildingMeshBundle.GetRuntimeScale();
		instance.transform.localPosition = Vector3.forward * BillboardSouthOffset;
		instance.SetActive(true);
		// Inherit parent facing (PNG identity local). Do not multiply bvmu by 90 — same OE encoding
		// trap that flipped towns (rotation 0 vs 10).
		Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat(
			instance,
			mapFacingYawDegrees: 0f,
			artYawDegrees: entry != null ? entry.ArtYawDegrees : 0f,
			cacheKey: entry != null ? entry.PrefabKey : null,
			log);
		SetDwellingMeshLayerRecursive(instance, root.layer);

		var donorMaterial = donor ? donor.sharedMaterial : null;
		if (!Homm3MapBuildingMeshBundle.TryRebindRenderersToMapDonor(instance, donorMaterial, log))
		{
			UnityEngine.Object.Destroy(instance);
			return false;
		}
		if (donor)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donor, instance);

		Homm3MapBuildingMeshProjectedFx.TryAttachForCatalogEntry(instance, entry, log);
		Homm3MeshFx.TryAttachForMapBuilding(instance, entry, log);
		Homm3MapBuildingAnim.TryAttachForMapBuilding(instance, entry, donor, log);

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			log?.LogInfo(
				"HoMM3 custom dwelling mesh: applied sid='"
				+ sid
				+ "' prefab='"
				+ (entry?.PrefabKey ?? "?")
				+ "' root='"
				+ (root.name ?? "?")
				+ "'.");
		}
		return true;
	}

	private static bool IsTransientDwellingMeshRoot(GameObject root)
	{
		if (!root || string.IsNullOrWhiteSpace(root.name))
			return true;
		var name = root.name;
		if (IsRandomHireRootName(name))
			return true;
		if (name.StartsWith("Section Root:", StringComparison.OrdinalIgnoreCase))
			return true;
		if (string.Equals(name, "city-spawner", StringComparison.OrdinalIgnoreCase)
		    || string.Equals(name, "random-city", StringComparison.OrdinalIgnoreCase))
		{
			return true;
		}
		return false;
	}

	private static bool TryGetExactCustomDwellingRootSid(GameObject root, out string dwellingSid)
	{
		dwellingSid = null;
		if (!root || string.IsNullOrWhiteSpace(root.name) || IsTransientDwellingMeshRoot(root))
			return false;
		var text = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(root.name) ?? root.name;
		if (!Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(text, out _))
			return false;
		dwellingSid = text;
		return true;
	}

	private static void DestroyOrphanDwellingMeshes(GameObject root, string keepSid)
	{
		if (!root)
			return;
		var keepName = Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeDwellingMeshName(keepSid);
		var doomed = new List<GameObject>();
		for (var i = 0; i < root.transform.childCount; i++)
		{
			var child = root.transform.GetChild(i);
			if (!child || string.IsNullOrWhiteSpace(child.name))
				continue;
			if (!child.name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
				continue;
			if (string.Equals(child.name, keepName, StringComparison.Ordinal))
				continue;
			doomed.Add(child.gameObject);
		}
		for (var i = 0; i < doomed.Count; i++)
		{
			if (doomed[i])
				UnityEngine.Object.Destroy(doomed[i]);
		}
	}

	private static string SanitizeDwellingMeshName(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return "unknown";
		var chars = sid.Trim().ToCharArray();
		for (var i = 0; i < chars.Length; i++)
		{
			var c = chars[i];
			var keep = (c >= 'a' && c <= 'z')
			           || (c >= 'A' && c <= 'Z')
			           || (c >= '0' && c <= '9')
			           || c == '_'
			           || c == '-';
			if (!keep)
				chars[i] = '_';
		}
		return new string(chars);
	}

	private static void SetDwellingMeshLayerRecursive(GameObject root, int layer)
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

	private static bool ApplyBillboard(GameObject root, string sid, ManualLogSource log)
	{
		if (Homm3MapBuildingMeshBundle.IsEnabled()
		    && Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out var meshRelativePath)
		    && Homm3MapBuildingMeshBundle.HasMeshForRelativePath(meshRelativePath))
		{
			return ApplyDwellingMapBuildingMesh(root, sid, meshRelativePath, log);
		}

		if (HasVisualForSid(root, sid))
		{
			HideExistingRenderers(root);
			var existingVisual = root.transform.Find(VisualRootName);
			if (existingVisual)
				Homm3BattleBillboardCameraFacing.TryAttachMapObject(existingVisual, log);
			return true;
		}
		var donor = FindBestMapDonorRenderer(root);
		var material = GetOrCreateMaterial(sid, donor ? donor.sharedMaterial : null, log);
		if (!material || !material.mainTexture)
			return false;

		HideExistingRenderers(root);

		var visual = root.transform.Find(VisualRootName);
		if (visual == null)
		{
			var go = new GameObject(VisualRootName);
			visual = go.transform;
			visual.SetParent(root.transform, false);
		}
		visual.localPosition = Vector3.up * ((BillboardHeight * 0.5f) + GroundClearance)
		                       + Vector3.forward * BillboardSouthOffset;
		visual.localRotation = Quaternion.identity;
		visual.localScale = Vector3.one;
		visual.gameObject.layer = root.layer;

		var quad = visual.Find("quad");
		var quadGo = quad == null ? new GameObject("quad") : quad.gameObject;
		if (quad == null)
			quadGo.transform.SetParent(visual, false);
		quadGo.layer = root.layer;
		quadGo.transform.localPosition = new Vector3(0f, 0f, 0.04f);
		quadGo.transform.localRotation = Quaternion.identity;
		var tex = material.mainTexture;
		var width = tex.height > 0 ? BillboardHeight * tex.width / tex.height : BillboardHeight;
		quadGo.transform.localScale = new Vector3(width, BillboardHeight, 1f);

		var mf = quadGo.GetComponent<MeshFilter>() ?? quadGo.AddComponent<MeshFilter>();
		var nd = quadGo.GetComponent<MeshRenderer>() ?? quadGo.AddComponent<MeshRenderer>();
		mf.sharedMesh = GetOrCreateQuadMesh();
		nd.sharedMaterial = material;
		try { nd.SetPropertyBlock(null); } catch { }
		if (donor)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donor, visual.gameObject);
		nd.shadowCastingMode = ShadowCastingMode.On;
		nd.receiveShadows = false;
		nd.allowOcclusionWhenDynamic = false;
		Homm3BattleBillboardCameraFacing.TryAttachMapObject(visual, log);
		if (Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out var animRelativePath)
		    && Homm3MapBuildingAnim.HasBillboardFrames(animRelativePath))
			Homm3MapBuildingAnim.TryRegisterBillboard(material, nd, animRelativePath, log);

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out var relativePath);
			log?.LogInfo("HoMM3 custom dwelling billboard: applied sid='" + sid + "' image='" + (relativePath ?? "?") + "' root='" + (root.name ?? "?") + "' donor='" + (donor ? donor.name : "(none)") + "'.");
		}
		return true;
	}

	private static bool HasVisualForSid(GameObject root, string sid)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return false;
		var meshRoot = root.transform.Find(Homm3MapBuildingMeshBundle.MeshRootPrefix + SanitizeDwellingMeshName(sid));
		if (meshRoot && meshRoot.gameObject.activeSelf)
		{
			var meshRenderers = meshRoot.GetComponentsInChildren<MeshRenderer>(true);
			if (meshRenderers != null)
			{
				for (var i = 0; i < meshRenderers.Length; i++)
				{
					var r = meshRenderers[i];
					if (r && r.enabled && !r.forceRenderingOff && r.sharedMaterial)
						return true;
				}
			}
		}
		var visual = root.transform.Find(VisualRootName);
		if (!visual || !visual.gameObject.activeSelf)
			return false;
		var quad = visual.Find("quad");
		var renderer = quad ? quad.GetComponent<MeshRenderer>() : null;
		if (!renderer || !renderer.enabled || renderer.forceRenderingOff || !renderer.sharedMaterial)
			return false;
		var materialName = renderer.sharedMaterial.name ?? string.Empty;
		return materialName.IndexOf(sid, StringComparison.Ordinal) >= 0;
	}

	private static Material GetOrCreateMaterial(string sid, Material donor, ManualLogSource log)
	{
		if (MaterialsBySid.TryGetValue(sid, out var cached) && cached)
			return cached;
		// Animated billboards (Homm3MapBuildingAnim billboard_frames) start on their first composite
		// frame and carry the map-anim material prefix so frame swaps only touch the main slots.
		var animated = Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out var animRelativePath)
		               && Homm3MapBuildingAnim.HasBillboardFrames(animRelativePath);
		var texture = animated
			? Homm3MapBuildingAnim.TryGetBillboardFirstFrame(animRelativePath, log)
			: GetOrCreateTexture(sid, log);
		if (!texture)
			return null;
		var materialName = (animated ? Homm3MapBuildingAnim.MaterialPrefix + "dwelling_" : "HOMM3_stronghold_dwelling_") + sid + "_hexlit";
		Material material = null;
		if (IsHexLitMaterial(donor))
			material = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(donor, texture, materialName);
		if (!material)
		{
			var shader = Shader.Find("Hex/Lit");
			if (!shader)
				return null;
			material = new Material(shader) { name = materialName + "_generated" };
			SetBillboardTexture(material, texture);
			if (material.HasProperty("_AlphaClip"))
				material.SetFloat("_AlphaClip", 1f);
			if (material.HasProperty("_AlphaCutoff"))
				material.SetFloat("_AlphaCutoff", 0.08f);
			if (material.HasProperty("_Cutoff"))
				material.SetFloat("_Cutoff", 0.08f);
			if (material.HasProperty("_Color"))
				material.SetColor("_Color", Color.white);
			try { material.EnableKeyword("HEX_ALPHA_CLIP_ENABLED"); } catch { }
			try { material.EnableKeyword("_ALPHATEST_ON"); } catch { }
			EsquirePikemanVisuals.FinalizeHexLitMapBillboardMaterial(material, null);
		}
		MaterialsBySid[sid] = material;
		return material;
	}

	private static bool IsHexLitMaterial(Material material)
	{
		return material
		       && material.shader
		       && !string.IsNullOrWhiteSpace(material.shader.name)
		       && material.shader.name.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static void SetBillboardTexture(Material material, Texture texture)
	{
		if (!material || !texture)
			return;
		if (material.HasProperty("_MainTex"))
			material.SetTexture("_MainTex", texture);
		material.mainTexture = texture;
		if (material.HasProperty("_BaseMap"))
			material.SetTexture("_BaseMap", texture);
		if (material.HasProperty("_BaseColorMap"))
			material.SetTexture("_BaseColorMap", texture);
		if (material.HasProperty("_AlbedoMap"))
			material.SetTexture("_AlbedoMap", texture);
		if (material.HasProperty("_MainTexture"))
			material.SetTexture("_MainTexture", texture);
	}

	private static Texture2D GetOrCreateTexture(string sid, ManualLogSource log)
	{
		if (TexturesBySid.TryGetValue(sid, out var cached) && cached)
			return cached;

		// Phase 2 pilot: homm3_map_billboards AssetBundle before PNG decode; PNG stays the per-sid
		// fallback. The bundle texture is the shared sprite texture (compressed, not CPU-readable) —
		// this path only sets sampler modes, which is allowed on non-readable textures.
		if (Homm3MapBillboardBundle.IsEnabled())
		{
			if (Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out var bundleRelativePath)
			    && Homm3MapBillboardBundle.TryLoadTexture(bundleRelativePath, out var bundleTexture)
			    && bundleTexture)
			{
				LogDwellingBundleResolution(sid, hit: true, log);
				bundleTexture.filterMode = FilterMode.Point;
				bundleTexture.wrapMode = TextureWrapMode.Clamp;
				TexturesBySid[sid] = bundleTexture;
				return bundleTexture;
			}
			LogDwellingBundleResolution(sid, hit: false, log);
		}

		var path = ResolveImagePath(sid);
		if (path == null)
		{
			if (LoggedMissingImage.Add(sid))
				log?.LogWarning("HoMM3 custom dwelling billboard: missing image for " + sid + ".");
			return null;
		}
		var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		var bytes = File.ReadAllBytes(path);
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		if (!ImageConversion.LoadImage(tex, il2cppBytes))
		{
			UnityEngine.Object.Destroy(tex);
			return null;
		}
		tex.name = "HOMM3_stronghold_dwelling_" + sid;
		tex.filterMode = FilterMode.Point;
		tex.wrapMode = TextureWrapMode.Clamp;
		TexturesBySid[sid] = tex;
		return tex;
	}

	private static readonly HashSet<string> LoggedDwellingBundleResolution = new(StringComparer.Ordinal);

	private static void LogDwellingBundleResolution(string sid, bool hit, ManualLogSource log)
	{
		if (!LoggedDwellingBundleResolution.Add(sid ?? "?"))
			return;
		log?.LogInfo(
			"HoMM3 custom dwelling billboard: "
			+ (hit ? "bundle-hit" : "bundle-miss")
			+ " sid='"
			+ (sid ?? "?")
			+ "' (homm3_map_billboards"
			+ (hit ? "" : "; falling back to PNG")
			+ ").");
	}

	private static string ResolveImagePath(string sid)
	{
		if (!Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out var relativePath))
			return null;
		return Homm3CustomFactionRegistry.TryGetStartupAssetPath(relativePath, out var path) ? path : null;
	}

	private static bool TryGetStrongholdDwellingSid(object meta, out string sid)
	{
		sid = null;
		if (meta == null)
			return false;
		var config = DeobfInteropCompat.TryGetMapObjectMetaConfig(meta, out var compatConfig) ? compatConfig : null;
		if (config == null)
			config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		// GetConfigElementId first — ConfigIdFields field_Public_String_0 can be ObjectConfig.tag.
		sid = DeobfInteropCompat.GetConfigElementId(config);
		if (string.IsNullOrWhiteSpace(sid))
			sid = GetFirstMemberValue(config, GameSymbols.CustomTownMapBillboard.ConfigIdFields) as string;
		return Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out _);
	}

	private static bool TryGetStrongholdDwellingSidReflective(object meta, out string sid)
	{
		sid = null;
		if (meta == null)
			return false;
		sid = GetConfigSidReflective(meta);
		return Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(sid, out _);
	}

	private static string GetConfigSidReflective(object meta)
	{
		if (meta == null)
			return null;
		if (meta is Hex.Map.MapObjectInfo info && DeobfInteropCompat.TryGetMapObjectInfoSid(info, out var infoSid))
			return infoSid;
		var config = DeobfInteropCompat.TryGetMapObjectMetaConfig(meta, out var compatConfig) ? compatConfig : null;
		if (config == null)
			config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		return DeobfInteropCompat.GetConfigElementId(config)
		       ?? GetFirstMemberValue(config, GameSymbols.CustomTownMapBillboard.ConfigIdFields) as string;
	}

	private static string GetPlacedObjectSidReflective(object instance)
	{
		return GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields) as string;
	}

	private static object GetReleaseMapObjectMeta(object instance)
	{
		return GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.MetaFields);
	}

	private static GameObject GetReleaseMapObjectRoot(object instance)
	{
		var root = GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.RootGameObjectFields) as GameObject
		           ?? InvokeFirstNoArg(instance, typeof(GameObject), GameSymbols.CustomTownMapBillboard.RootGameObjectGetter) as GameObject;
		if (root)
			return root;

		var transform = GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.RootTransformFields) as Transform
		                ?? InvokeFirstNoArg(instance, typeof(Transform), GameSymbols.CustomTownMapBillboard.RootTransformGetter) as Transform;
		return transform ? transform.gameObject : null;
	}

	private static int GetReleaseMapObjectId(object instance, object[] args)
	{
		return GetMapObjectPropertyId(instance);
	}

	private static int? TryGetIntArg(object[] args, int index)
	{
		if (args == null || index < 0 || index >= args.Length || args[index] == null)
			return null;
		try { return Convert.ToInt32(args[index]); }
		catch { return null; }
	}

	private static int GetMapObjectId(object owner)
	{
		var id = GetMapObjectPropertyId(owner);
		if (id >= 0)
			return id;
		var value = GetFirstMemberValue(owner, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields);
		try
		{
			if (value != null)
				return Convert.ToInt32(value);
		}
		catch { }
		return -1;
	}

	private static int GetMapObjectPropertyId(object owner)
	{
		var compatId = DeobfInteropCompat.GetIntMember(owner, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields);
		if (compatId > 0)
			return compatId;
		var value = GetFirstMemberValue(owner, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields)
		            ?? GetFirstMemberValue(owner, GameSymbols.CustomDwellingRandomHire.DataObjectIdFields);
		try
		{
			if (value != null)
				return Convert.ToInt32(value);
		}
		catch { }
		return -1;
	}

	private static int GetOwnerSide(object owner)
	{
		var value = GetFirstMemberValue(owner, GameSymbols.CustomDwellingRandomHire.DataObjectOwnerSideFields);
		try
		{
			if (value != null)
				return Convert.ToInt32(value);
		}
		catch { }
		return -1;
	}

	private static void RememberCustomCityOwnerSide(object cityData, object cityConfig)
	{
		if (cityData == null)
			return;
		var ownerSide = GetOwnerSide(cityData);
		if (ownerSide < 0)
			return;
		var citySid = GetFirstMemberValue(cityData, GameSymbols.CustomDwellingRandomHire.DataObjectConfigSidFields) as string;
		string factionSid = null;
		if (!string.IsNullOrWhiteSpace(citySid))
		{
			var canonicalCitySid = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(citySid.Trim());
			Homm3CustomFactionRegistry.TryGetFactionSidForCitySid(canonicalCitySid, out factionSid);
		}
		if (string.IsNullOrWhiteSpace(factionSid))
			factionSid = GetFirstMemberValue(cityConfig, GameSymbols.CustomDwellingHire.HireConfigFactionFields) as string;
		if (string.IsNullOrWhiteSpace(factionSid) || !Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return;

		CustomFactionSidByOwnerSide[ownerSide] = factionSid.Trim();
		if (LoggedCityOwnerSides.Add(ownerSide))
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: mapped ownerSide=" + ownerSide
			                           + " citySid='" + (citySid ?? "?")
			                           + "' to custom faction '" + factionSid.Trim() + "'.");
		}
		FlushPendingOwnerSideHires(ownerSide, factionSid.Trim());
	}

	private static bool TryResolveRandomHireDwellingSid(int mapObjectId, object randomHireData, object randomHireConfig, out string dwellingSid)
	{
		dwellingSid = null;
		var matches = new Dictionary<string, Homm3CustomFactionRegistry.DwellingUnitMatch>(StringComparer.Ordinal);
		var dataSidCount = CollectRandomHireDwellingMatches(randomHireData, matches);
		var configSidCount = CollectRandomHireDwellingMatches(randomHireConfig, matches);
		if (matches.Count == 0)
		{
			if (_loggedRandomHireNoMatch < 60)
			{
				_loggedRandomHireNoMatch++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: random-hire map object " + mapObjectId
				                           + " produced no custom dwelling match; dataSids=" + dataSidCount
				                           + " configSids=" + configSidCount
				                           + " data=" + DescribeObject(randomHireData)
				                           + " config=" + DescribeObject(randomHireConfig)
				                           + " dataMembers=" + DescribeAvailableMembers(randomHireData, 12)
				                           + " configMembers=" + DescribeAvailableMembers(randomHireConfig, 12) + ".");
			}
			return false;
		}
		if (matches.Count > 1)
		{
			if (LoggedRandomHireAmbiguous.Add(mapObjectId))
				Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: refusing random-hire map object " + mapObjectId + " because its unit payload maps to multiple custom dwellings: " + string.Join(", ", matches.Keys) + ".");
			return false;
		}
		foreach (var match in matches.Values)
		{
			dwellingSid = match.CustomDwellingSid;
			if (_loggedRandomHireResolved < 40)
			{
				_loggedRandomHireResolved++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: random-hire map object " + mapObjectId + " resolved from unit '" + match.UnitSid + "' to '" + dwellingSid + "'.");
			}
			return true;
		}
		return false;
	}

	private static bool TryResolveHireDwellingSid(int mapObjectId, object hireData, object hireConfig, out string dwellingSid)
	{
		dwellingSid = null;
		var matches = new Dictionary<string, Homm3CustomFactionRegistry.DwellingUnitMatch>(StringComparer.Ordinal);
		var dataSidCount = CollectHireDwellingMatches(hireData, matches);
		var configSidCount = CollectHireDwellingMatches(hireConfig, matches);
		if (matches.Count == 0)
		{
			var rawSid = GetFirstMemberValue(hireData, GameSymbols.CustomDwellingHire.HireDataConfigSidFields) as string;
			var nativeFaction = GetFirstMemberValue(hireConfig, GameSymbols.CustomDwellingHire.HireConfigFactionFields) as string;
			if (TryResolveOwnerSideDonorAliasFromHireContext(mapObjectId, hireData, rawSid, out dwellingSid))
				return true;
			if (TryResolveSeenCityDonorAliasFromHireContext(mapObjectId, rawSid, nativeFaction, out dwellingSid))
				return true;
			if (_loggedHireNoMatch < 60)
			{
				_loggedHireNoMatch++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: hire map object " + mapObjectId
				                           + " produced no custom dwelling match; dataSids=" + dataSidCount
				                           + " configSids=" + configSidCount
				                           + " data=" + DescribeObject(hireData)
				                           + " config=" + DescribeObject(hireConfig)
				                           + " dataMembers=" + DescribeAvailableMembers(hireData, 12)
				                           + " configMembers=" + DescribeAvailableMembers(hireConfig, 12) + ".");
			}
			return false;
		}
		if (matches.Count > 1)
		{
			if (LoggedRandomHireAmbiguous.Add(mapObjectId))
				Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: refusing hire map object " + mapObjectId + " because its unit payload maps to multiple custom dwellings: " + string.Join(", ", matches.Keys) + ".");
			return false;
		}
		foreach (var match in matches.Values)
		{
			dwellingSid = match.CustomDwellingSid;
			if (_loggedRandomHireResolved < 40)
			{
				_loggedRandomHireResolved++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: hire map object " + mapObjectId + " resolved from unit '" + match.UnitSid + "' to '" + dwellingSid + "'.");
			}
			return true;
		}
		return false;
	}

	private static bool TryResolveOwnerSideDonorAliasFromHireContext(int mapObjectId, object hireData, string rawSid, out string dwellingSid)
	{
		dwellingSid = null;
		if (string.IsNullOrWhiteSpace(rawSid) || !TryParseBarracksTier(rawSid, out var tier))
			return false;
		var ownerSide = GetOwnerSide(hireData);
		if (ownerSide < 0)
			return false;
		if (!CustomFactionSidByOwnerSide.TryGetValue(ownerSide, out var factionSid))
		{
			QueuePendingOwnerSideHire(mapObjectId, ownerSide, rawSid);
			return false;
		}
		if (!Homm3CustomFactionRegistry.TryGetDwellingSidForDonorAlias(rawSid, factionSid, out var aliasDwellingSid, out _))
		{
			if (_loggedHireNoMatch < 60)
			{
				_loggedHireNoMatch++;
				Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: ownerSide=" + ownerSide
				                           + " maps to custom faction '" + factionSid
				                           + "', but donor sid='" + rawSid
				                           + "' is not a declared donor alias for that faction.");
			}
			return false;
		}
		if (!Homm3CustomFactionRegistry.TryGetDirectDwellingSidForFactionTier(factionSid, tier, out dwellingSid))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard found exact custom ownerSide " + ownerSide
			                                    + " faction '" + factionSid
			                                    + "' for donor sid='" + rawSid
			                                    + "' but no manifest-owned direct dwelling tier " + tier + ".");
		if (!string.Equals(aliasDwellingSid, dwellingSid, StringComparison.Ordinal))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard donor alias mismatch for faction '" + factionSid
			                                    + "' donor sid='" + rawSid
			                                    + "': alias resolved '" + aliasDwellingSid
			                                    + "' but direct tier resolved '" + dwellingSid + "'.");

		if (_loggedRandomHireResolved < 40)
		{
			_loggedRandomHireResolved++;
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: hire map object " + mapObjectId
			                           + " resolved donor sid='" + rawSid
			                           + "' ownerSide=" + ownerSide
			                           + " to '" + dwellingSid + "'.");
		}
		return true;
	}

	private static bool TryResolvePropCityDonorDwellingSid(object placedInstance, object mapInstance, string rawSid, int mapObjectId, out string dwellingSid)
	{
		dwellingSid = null;
		if (placedInstance == null || string.IsNullOrWhiteSpace(rawSid) || !TryParseBarracksTier(rawSid, out var tier))
			return false;

		var hasAlias = false;
		foreach (var _ in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid.Trim()))
		{
			hasAlias = true;
			break;
		}
		if (!hasAlias)
			return false;

		var objectId = mapObjectId >= 0
			? mapObjectId
			: GetMapObjectPropertyId(placedInstance);
		if (objectId <= 0)
			return false;
		LogPropCityProbe(placedInstance, mapInstance, objectId, rawSid, null);

		if (!Homm3MapObjectPropCityResolver.TryGetPlacedObjectPropCityFaction(
			    placedInstance,
			    mapInstance,
			    objectId,
			    out var factionSid,
			    out var reason))
		{
			LogPropCityDonorMiss(rawSid, objectId, reason);
			return false;
		}
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetDwellingSidForDonorAlias(rawSid.Trim(), factionSid.Trim(), out var aliasDwellingSid, out _))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetDirectDwellingSidForFactionTier(factionSid.Trim(), tier, out dwellingSid))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard resolved PropCity faction '" + factionSid.Trim()
			                                    + "' for donor sid='" + rawSid
			                                    + "' but no manifest-owned direct dwelling tier " + tier + ".");
		if (!string.Equals(aliasDwellingSid, dwellingSid, StringComparison.Ordinal))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard PropCity donor alias mismatch for faction '" + factionSid.Trim()
			                                    + "' donor sid='" + rawSid
			                                    + "': alias resolved '" + aliasDwellingSid
			                                    + "' but direct tier resolved '" + dwellingSid + "'.");

		if (_loggedRandomHireResolved < 40)
		{
			_loggedRandomHireResolved++;
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: map object " + objectId
			                           + " resolved donor sid='" + rawSid
			                           + "' PropCity faction='" + factionSid.Trim()
			                           + "' to '" + dwellingSid + "'.");
		}
		return true;
	}

	private static void LogPropCityProbe(object placedInstance, object mapInstance, int objectId, string rawSid, int? nodeId)
	{
		if (_loggedPropCityProbe >= 30 || !Homm3DiagnosticFlags.IsEnabled(PropCityProbeFlagName))
			return;
		_loggedPropCityProbe++;
		try
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard PropCity probe: "
			                           + Homm3MapObjectPropCityResolver.DescribePlacedObjectPropCityProbe(placedInstance, mapInstance, objectId, rawSid, nodeId));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard PropCity probe failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void LogPropCityDonorMiss(string rawSid, int objectId, Homm3MapObjectPropCityResolver.MissReason reason)
	{
		if (_loggedHireNoMatch >= 60 || reason == Homm3MapObjectPropCityResolver.MissReason.None)
			return;
		_loggedHireNoMatch++;
		Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard diag: PropCity donor route missed for sid='"
		                           + (rawSid ?? "?")
		                           + "' objectId=" + objectId
		                           + " reason='" + reason + "'.");
	}

	private static bool TryResolvePropRandomHireNativeBiomeDwellingSid(object placedInstance, object mapInstance, int mapObjectId, int? nodeId, out string dwellingSid)
	{
		dwellingSid = null;
		if (placedInstance == null || mapObjectId <= 0 || !nodeId.HasValue)
			return false;
		if (!Homm3MapObjectPropCityResolver.TryGetPlacedObjectPropRandomHireNativeBiomeFaction(
			    placedInstance,
			    mapInstance,
			    mapObjectId,
			    nodeId,
			    out var tier,
			    out var fractionText,
			    out var areaBiome,
			    out var factionSid,
			    out _))
			return false;
		if (string.IsNullOrWhiteSpace(factionSid) || !Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetDirectDwellingSidForFactionTier(factionSid.Trim(), tier, out dwellingSid))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard resolved PropRandomHire native biome '" + areaBiome
			                                    + "' to faction '" + factionSid.Trim()
			                                    + "' but no manifest-owned direct dwelling tier " + tier + ".");
		if (_loggedRandomHireResolved < 40)
		{
			_loggedRandomHireResolved++;
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: map object " + mapObjectId
			                           + " node=" + nodeId.Value
			                           + " PropRandomHire fraction='" + (fractionText ?? "?")
			                           + "' biome='" + (areaBiome ?? "?")
			                           + "' faction='" + factionSid.Trim()
			                           + "' tier=" + tier
			                           + " -> '" + dwellingSid + "'.");
		}
		return true;
	}

	private static void LogPropRandomHireProbe(object placedInstance, object mapInstance, int objectId, string rawSid, int? nodeId)
	{
		if (_loggedPropCityProbe >= 30 || !Homm3DiagnosticFlags.IsEnabled(PropCityProbeFlagName) || objectId <= 0)
			return;
		if (!Homm3MapObjectPropCityResolver.TryGetPlacedObjectPropRandomHire(
			    placedInstance,
			    mapInstance,
			    objectId,
			    out _,
			    out _,
			    out _))
			return;
		_loggedPropCityProbe++;
		try
		{
			var root = GetReleaseMapObjectRoot(placedInstance);
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard PropRandomHire probe: "
			                           + Homm3MapObjectPropCityResolver.DescribePlacedObjectPropRandomHireProbe(placedInstance, mapInstance, objectId, rawSid, nodeId)
			                           + " root='" + (root ? root.name : "?") + "'");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard PropRandomHire probe failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void LogMapObjectSample(object placedInstance, object mapInstance, string rawSid, object meta)
	{
		if (_loggedMapObjectSamples >= 80 || !Homm3DiagnosticFlags.IsEnabled(PropCityProbeFlagName))
			return;
		var root = GetReleaseMapObjectRoot(placedInstance);
		var rootName = root ? root.name : "?";
		if (string.IsNullOrWhiteSpace(rawSid) && !IsLikelyDwellingRootName(rootName) && _loggedMapObjectSamples >= 12)
			return;
		var hasBarracksTier = TryParseBarracksTier(rawSid, out var tier);
		var hasAlias = false;
		if (!string.IsNullOrWhiteSpace(rawSid))
		{
			foreach (var _ in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid.Trim()))
			{
				hasAlias = true;
				break;
			}
		}
		var isDirect = TryResolveCustomDwellingSid(rawSid, out var directSid, out var waitsForCitySid);
		if (!hasBarracksTier && !hasAlias && !isDirect && waitsForCitySid == null && _loggedMapObjectSamples >= 30)
			return;
		_loggedMapObjectSamples++;
		var objectId = GetReleaseMapObjectId(placedInstance, null);
		Plugin.LogSource?.LogInfo(
			"HoMM3 custom dwelling billboard diag: map-object sample rawSid='" + (rawSid ?? "?") + "'"
			+ " objectId=" + objectId
			+ " tier=" + (hasBarracksTier ? tier.ToString() : "?")
			+ " donorAlias=" + hasAlias
			+ " direct='" + (isDirect ? directSid : "?") + "'"
			+ " waitsForCity='" + (waitsForCitySid ?? "?") + "'"
			+ " root='" + rootName + "'"
			+ " placedType='" + DescribeObject(placedInstance) + "'"
			+ " metaType='" + DescribeObject(meta) + "'"
			+ " mapType='" + DescribeObject(mapInstance) + "'.");
		if (string.IsNullOrWhiteSpace(rawSid))
			LogMissingSidBreakdown(placedInstance, meta, rootName, objectId);
	}

	private static bool IsLikelyDwellingRootName(string rootName)
	{
		if (string.IsNullOrWhiteSpace(rootName))
			return false;
		return rootName.IndexOf("barracks", StringComparison.OrdinalIgnoreCase) >= 0
		       || rootName.IndexOf("dwelling", StringComparison.OrdinalIgnoreCase) >= 0
		       || rootName.IndexOf("hire", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool IsRandomHireRootName(string rootName)
	{
		return string.Equals(rootName, "random-hire", StringComparison.OrdinalIgnoreCase);
	}

	private static bool IsUnknownSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) || string.Equals(sid.Trim(), "?", StringComparison.Ordinal);
	}

	private static void LogMissingSidBreakdown(object placedInstance, object meta, string rootName, int objectId)
	{
		if (_loggedMissingSidBreakdown >= 12 || !Homm3DiagnosticFlags.IsEnabled(PropCityProbeFlagName))
			return;
		_loggedMissingSidBreakdown++;
		object config = null;
		if (meta != null)
		{
			config = DeobfInteropCompat.TryGetMapObjectMetaConfig(meta, out var compatConfig) ? compatConfig : null;
			if (config == null)
				config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		}
		Plugin.LogSource?.LogInfo(
			"HoMM3 custom dwelling billboard diag: missing sid breakdown objectId=" + objectId
			+ " root='" + (rootName ?? "?") + "'"
			+ " placedStrings=[" + DescribeStringFields(placedInstance, 10) + "]"
			+ " metaStrings=[" + DescribeStringFields(meta, 10) + "]"
			+ " configType='" + DescribeObject(config) + "'"
			+ " configId='" + (DeobfInteropCompat.GetConfigElementId(config) ?? "?") + "'"
			+ " configStrings=[" + DescribeStringFields(config, 10) + "].");
	}

	private static string DescribeStringFields(object obj, int max)
	{
		if (obj == null)
			return "<null>";
		var parts = new List<string>();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		try
		{
			for (var t = obj.GetType(); t != null && t != typeof(object) && parts.Count < max; t = t.BaseType)
			{
				FieldInfo[] fields;
				try { fields = t.GetFields(flags); }
				catch { fields = Array.Empty<FieldInfo>(); }
				foreach (var field in fields)
				{
					if (parts.Count >= max)
						break;
					if (field.FieldType != typeof(string))
						continue;
					string value;
					try { value = field.GetValue(obj) as string; }
					catch { value = "<throw>"; }
					if (string.IsNullOrWhiteSpace(value))
						continue;
					parts.Add(field.Name + "='" + value.Trim() + "'");
				}
			}
		}
		catch (Exception ex)
		{
			parts.Add("error:" + ex.GetType().Name);
		}
		return parts.Count == 0 ? "<none>" : string.Join(",", parts);
	}

	private static void QueuePendingOwnerSideHire(int mapObjectId, int ownerSide, string rawSid)
	{
		var hasAlias = false;
		foreach (var _ in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid))
		{
			hasAlias = true;
			break;
		}
		if (!hasAlias)
			return;
		if (!PendingOwnerSideHireBySide.TryGetValue(ownerSide, out var entries))
		{
			entries = new List<PendingOwnerSideHireEntry>();
			PendingOwnerSideHireBySide[ownerSide] = entries;
		}
		for (var i = 0; i < entries.Count; i++)
		{
			if (entries[i].MapObjectId == mapObjectId)
				return;
		}
		entries.Add(new PendingOwnerSideHireEntry { MapObjectId = mapObjectId, OwnerSide = ownerSide, RawSid = rawSid });
	}

	private static void FlushPendingOwnerSideHires(int ownerSide, string factionSid)
	{
		if (!PendingOwnerSideHireBySide.TryGetValue(ownerSide, out var entries) || entries.Count == 0)
			return;
		for (var i = entries.Count - 1; i >= 0; i--)
		{
			var pending = entries[i];
			if (pending == null || !TryResolveOwnerSideDonorAlias(pending.MapObjectId, pending.OwnerSide, pending.RawSid, factionSid, out var dwellingSid))
				continue;
			ResolvedRandomHireDwellingById[pending.MapObjectId] = dwellingSid;
			ApplyResolvedRandomHireDwelling(pending.MapObjectId, pending.RawSid, dwellingSid, "owner-side-city");
			entries.RemoveAt(i);
		}
		if (entries.Count == 0)
			PendingOwnerSideHireBySide.Remove(ownerSide);
	}

	private static bool TryResolveOwnerSideDonorAlias(int mapObjectId, int ownerSide, string rawSid, string factionSid, out string dwellingSid)
	{
		dwellingSid = null;
		if (string.IsNullOrWhiteSpace(factionSid) || !TryParseBarracksTier(rawSid, out var tier))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetDwellingSidForDonorAlias(rawSid, factionSid, out var aliasDwellingSid, out _))
			return false;
		if (!Homm3CustomFactionRegistry.TryGetDirectDwellingSidForFactionTier(factionSid, tier, out dwellingSid))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard found exact custom ownerSide " + ownerSide
			                                    + " faction '" + factionSid
			                                    + "' for donor sid='" + rawSid
			                                    + "' but no manifest-owned direct dwelling tier " + tier + ".");
		if (!string.Equals(aliasDwellingSid, dwellingSid, StringComparison.Ordinal))
			throw new InvalidOperationException("HoMM3 custom dwelling billboard donor alias mismatch for faction '" + factionSid
			                                    + "' donor sid='" + rawSid
			                                    + "': alias resolved '" + aliasDwellingSid
			                                    + "' but direct tier resolved '" + dwellingSid + "'.");
		if (_loggedRandomHireResolved < 40)
		{
			_loggedRandomHireResolved++;
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: hire map object " + mapObjectId
			                           + " resolved donor sid='" + rawSid
			                           + "' ownerSide=" + ownerSide
			                           + " to '" + dwellingSid + "'.");
		}
		return true;
	}

	private static bool TryResolveSeenCityDonorAliasFromHireContext(int mapObjectId, string rawSid, string nativeFaction, out string dwellingSid)
	{
		dwellingSid = null;
		if (string.IsNullOrWhiteSpace(rawSid) || string.IsNullOrWhiteSpace(nativeFaction))
			return false;

		var aliases = new List<Homm3CustomFactionRegistry.DwellingDonorAlias>();
		foreach (var alias in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid.Trim()))
		{
			if (!SeenCitySids.Contains(alias.CitySid))
				continue;
			if (!string.Equals(alias.DefaultDonorFactionSid, nativeFaction.Trim(), StringComparison.OrdinalIgnoreCase))
				continue;
			aliases.Add(alias);
		}

		if (aliases.Count == 0)
			return false;
		if (aliases.Count > 1)
		{
			LogAmbiguousDonorAlias(rawSid, aliases);
			return false;
		}

		dwellingSid = aliases[0].CustomDwellingSid;
		if (_loggedRandomHireResolved < 40)
		{
			_loggedRandomHireResolved++;
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: hire map object " + mapObjectId + " resolved donor sid='" + rawSid + "' fraction='" + nativeFaction + "' to '" + dwellingSid + "' via seen custom city '" + aliases[0].CitySid + "'.");
		}
		return true;
	}

	private static bool TryParseBarracksTier(string sid, out int tier)
	{
		tier = 0;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		const string prefix = "barracks_";
		if (!key.StartsWith(prefix, StringComparison.Ordinal))
			return false;
		var index = key.LastIndexOf('_');
		return index > prefix.Length
		       && index + 1 < key.Length
		       && int.TryParse(key.Substring(index + 1), out tier)
		       && tier >= 1
		       && tier <= 7;
	}

	private static int CollectRandomHireDwellingMatches(object owner, Dictionary<string, Homm3CustomFactionRegistry.DwellingUnitMatch> matches)
	{
		if (owner == null || matches == null)
			return 0;
		var count = 0;
		var assortment = GetFirstMemberValue(owner, GameSymbols.CustomDwellingRandomHire.AssortmentFields);
		var unitSets = GetFirstMemberValue(assortment, GameSymbols.CustomDwellingRandomHire.UnitSetsFields);
		count += CollectDwellingMatchesFromUnitSetList(unitSets, matches);

		var randomHireUnits = GetFirstMemberValue(owner, GameSymbols.CustomDwellingRandomHire.RandomHireUnitsFields);
		count += CollectDwellingMatchesFromUnitSetList(randomHireUnits, matches);
		return count;
	}

	private static int CollectHireDwellingMatches(object owner, Dictionary<string, Homm3CustomFactionRegistry.DwellingUnitMatch> matches)
	{
		if (owner == null || matches == null)
			return 0;
		var count = CollectRandomHireDwellingMatches(owner, matches);
		var unitsData = GetFirstMemberValue(owner, GameSymbols.CustomDwellingHire.HireConfigUnitsDataFields);
		var units = GetFirstMemberValue(unitsData, GameSymbols.CustomDwellingHire.HireConfigUnitsFields);
		count += CollectDwellingMatchesFromUnitSetList(units, matches);

		var guardUnits = GetFirstMemberValue(owner, GameSymbols.CustomDwellingHire.HireDataGuardUnitsFields);
		foreach (var unit in EnumerateIl2CppList(guardUnits))
		{
			var sid = GetFirstMemberValue(unit, GameSymbols.CustomDwellingHire.UnitSidFields) as string;
			if (string.IsNullOrWhiteSpace(sid))
				continue;
			count++;
			if (!Homm3CustomFactionRegistry.TryGetDwellingSidForUnitSid(sid, out var match))
				continue;
			matches[match.CustomDwellingSid] = match;
		}
		return count;
	}

	private static int CollectDwellingMatchesFromUnitSetList(object unitSets, Dictionary<string, Homm3CustomFactionRegistry.DwellingUnitMatch> matches)
	{
		var count = 0;
		foreach (var unitSet in EnumerateIl2CppList(unitSets))
		{
			var sidList = GetFirstMemberValue(unitSet, GameSymbols.CustomDwellingRandomHire.UnitSidListFields);
			foreach (var sid in EnumerateStringList(sidList))
			{
				count++;
				if (!Homm3CustomFactionRegistry.TryGetDwellingSidForUnitSid(sid, out var match))
					continue;
				matches[match.CustomDwellingSid] = match;
			}
		}
		return count;
	}

	private static void ApplyResolvedRandomHireDwelling(int mapObjectId, string rawSid, string dwellingSid, string source)
	{
		if (string.IsNullOrWhiteSpace(dwellingSid))
			return;
		// Random-hire payloads bind by exact map object id; donor/raw SIDs are shared across custom dwellings.
		if (mapObjectId < 0 || !PendingRandomHireMapObjectsById.TryGetValue(mapObjectId, out var entry))
			return;
		if (entry?.Root == null || !entry.Root)
			return;
		if (!string.IsNullOrWhiteSpace(rawSid)
		    && !string.IsNullOrWhiteSpace(entry.RawSid)
		    && !string.Equals(entry.RawSid, rawSid, StringComparison.Ordinal))
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: refused to apply resolved dwelling '"
			                             + dwellingSid
			                             + "' for mapObjectId="
			                             + mapObjectId
			                             + " because pending raw sid='"
			                             + entry.RawSid
			                             + "' does not match resolved raw sid='"
			                             + rawSid
			                             + "'.");
			return;
		}
		if (HasAppliedLiveRoot(entry.Root, dwellingSid))
		{
			EnsureAppliedBillboardSuppressesDonor(entry.Root, dwellingSid);
			return;
		}
		if (!ApplyBillboard(entry.Root, dwellingSid, Plugin.LogSource))
			return;
		MarkAppliedLiveRoot(entry.Root, dwellingSid);
		if (LoggedLiveApplied.Add(dwellingSid))
			Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: applied live billboard to " + dwellingSid + " via release random-hire payload (" + source + ").");
	}

	private static void ApplyResolvedHireIdentity(object hireData, string rawSid, string dwellingSid, int mapObjectId)
	{
		if (hireData == null || string.IsNullOrWhiteSpace(dwellingSid))
			return;
		var currentSid = GetFirstMemberValue(hireData, GameSymbols.CustomDwellingHire.HireDataConfigSidFields) as string;
		if (string.Equals(currentSid, dwellingSid, StringComparison.Ordinal))
			return;
		if (!string.IsNullOrWhiteSpace(currentSid)
		    && !string.IsNullOrWhiteSpace(rawSid)
		    && !string.Equals(currentSid, rawSid, StringComparison.Ordinal))
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: refused to stamp hire data sidConfig for mapObjectId=" + mapObjectId
			                             + " because current sidConfig='" + currentSid
			                             + "' no longer matches resolved donor sid='" + rawSid + "'.");
			return;
		}

		foreach (var member in GameSymbols.CustomDwellingHire.HireDataConfigSidFields)
		{
			TrySetMemberValue(hireData, member, dwellingSid);
			if (string.Equals(GetFirstMemberValue(hireData, GameSymbols.CustomDwellingHire.HireDataConfigSidFields) as string, dwellingSid, StringComparison.Ordinal))
			{
				if (LoggedHireIdentityStamps.Add(mapObjectId))
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: stamped hire data sidConfig for mapObjectId=" + mapObjectId + " to '" + dwellingSid + "'.");
				return;
			}
		}

		Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: failed to stamp hire data sidConfig for mapObjectId=" + mapObjectId + " to '" + dwellingSid + "'.");
	}

	private static bool TryResolveCustomDwellingSid(string rawSid, out string strongholdSid, out string waitsForCitySid)
	{
		strongholdSid = null;
		waitsForCitySid = null;
		if (rawSid == null)
			return false;
		if (Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset(rawSid, out _))
		{
			// Land-on visit-gate clones resolve to the canonical barracks_homm3_* SID.
			strongholdSid = Homm3CustomFactionRegistry.ResolveMapBillboardSidAlias(rawSid);
			return true;
		}

		var aliases = new List<Homm3CustomFactionRegistry.DwellingDonorAlias>();
		foreach (var alias in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid))
			aliases.Add(alias);
		if (aliases.Count == 0)
			return false;

		LogDonorAliasRefused(rawSid, aliases);
		return false;
	}

	private static void ResetMapStateIfChanged(object mapInstance)
	{
		var sceneKey = GetActiveSceneKey();
		if (!string.IsNullOrEmpty(sceneKey))
		{
			// One map load runs many bvb.Init passes with different Map wrapper instances; scene key is stable.
			if (string.Equals(CurrentMapSceneKey, sceneKey, StringComparison.Ordinal))
			{
				if (mapInstance != null)
					CurrentMapInstance = mapInstance;
				return;
			}

			CurrentMapSceneKey = sceneKey;
			CurrentMapInstance = mapInstance;
			ClearMapState();
			return;
		}

		if (mapInstance == null)
			return;
		if (CurrentMapInstance != null)
			return;
		CurrentMapInstance = mapInstance;
		ClearMapState();
	}

	private static string GetActiveSceneKey()
	{
		try
		{
			var scene = SceneManager.GetActiveScene();
			return scene.IsValid() ? scene.handle + ":" + (scene.name ?? "") : null;
		}
		catch
		{
			return null;
		}
	}

	private static void ClearMapState()
	{
		SeenCitySids.Clear();
		PendingDungeonBarracks.Clear();
		PendingRandomHireMapObjectsById.Clear();
		ResolvedRandomHireDwellingById.Clear();
		CustomFactionSidByOwnerSide.Clear();
		PendingOwnerSideHireBySide.Clear();
		LoggedCityOwnerSides.Clear();
		LoggedHireIdentityStamps.Clear();
		LoggedDonorAliases.Clear();
		LoggedAmbiguousDonorAlias.Clear();
		LoggedDonorAliasRefused.Clear();
		AppliedLiveRootKeys.Clear();
		_loggedQueuedAlias = 0;
		Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: reset per-map donor alias state.");
	}

	private static void QueuePendingBarracksAliases(GameObject root, object meta, string rawSid, string resolvedSid, string requiredCitySid)
	{
		if (string.Equals(requiredCitySid, "homm3_any_custom_city", StringComparison.Ordinal))
		{
			foreach (var alias in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid))
				QueuePendingDungeonBarracks(root, meta, rawSid, alias.CustomDwellingSid, alias.CitySid);
			return;
		}
		QueuePendingDungeonBarracks(root, meta, rawSid, resolvedSid, requiredCitySid);
	}

	private static void QueuePendingDungeonBarracks(GameObject root, object meta, string rawSid, string strongholdSid, string requiredCitySid)
	{
		if (!root || string.IsNullOrEmpty(strongholdSid))
			return;
		PendingDungeonBarracks.Add(new PendingDungeonBarracksEntry { Root = root, Meta = meta, RawSid = rawSid, CustomDwellingSid = strongholdSid, RequiredCitySid = requiredCitySid });
	}

	private static void FlushPendingDungeonBarracks(string requiredCitySid)
	{
		if (PendingDungeonBarracks.Count == 0)
			return;
		for (var i = PendingDungeonBarracks.Count - 1; i >= 0; i--)
		{
			var pending = PendingDungeonBarracks[i];
			if (pending == null || !string.Equals(pending.RequiredCitySid, requiredCitySid, StringComparison.Ordinal))
				continue;
			if (HasMultipleSeenAliases(pending.RawSid, requiredCitySid))
			{
				PendingDungeonBarracks.RemoveAt(i);
				continue;
			}
			LogDonorAliasOnce(pending.RawSid, requiredCitySid, pending.CustomDwellingSid);
			if (pending?.Root && HasAppliedLiveRoot(pending.Root, pending.CustomDwellingSid))
			{
				EnsureAppliedBillboardSuppressesDonor(pending.Root, pending.CustomDwellingSid);
			}
			else if (pending?.Root && ApplyBillboard(pending.Root, pending.CustomDwellingSid, Plugin.LogSource))
			{
				MarkAppliedLiveRoot(pending.Root, pending.CustomDwellingSid);
				if (LoggedLiveApplied.Add(pending.CustomDwellingSid))
					Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: applied live billboard to " + pending.CustomDwellingSid + " via release random-hire barracks alias.");
			}
			PendingDungeonBarracks.RemoveAt(i);
		}
	}

	private static void TryRewriteConfigSidReflective(object meta, string rawSid, string strongholdSid)
	{
		if (meta == null || string.IsNullOrEmpty(rawSid) || string.IsNullOrEmpty(strongholdSid))
			return;
		var matchedAlias = false;
		foreach (var alias in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid))
		{
			if (!string.Equals(alias.CustomDwellingSid, strongholdSid, StringComparison.Ordinal))
				continue;
			matchedAlias = true;
			break;
		}
		if (!matchedAlias)
			return;
		var config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		if (config == null)
			return;
		foreach (var member in GameSymbols.CustomTownMapBillboard.ConfigIdFields)
		{
			if (string.Equals(GetMemberValue(config, member) as string, rawSid, StringComparison.Ordinal))
				TrySetMemberValue(config, member, strongholdSid);
		}
	}

	private static bool HasMultipleSeenAliases(string rawSid, string requiredCitySid)
	{
		var seen = 0;
		var aliases = new List<Homm3CustomFactionRegistry.DwellingDonorAlias>();
		foreach (var alias in Homm3CustomFactionRegistry.EnumerateDwellingDonorAliases(rawSid))
		{
			aliases.Add(alias);
			if (SeenCitySids.Contains(alias.CitySid))
				seen++;
		}
		if (seen <= 1)
			return false;
		LogAmbiguousDonorAlias(rawSid, aliases);
		return true;
	}

	private static void LogDonorAliasOnce(string rawSid, Homm3CustomFactionRegistry.DwellingDonorAlias alias)
	{
		LogDonorAliasOnce(rawSid, alias.CitySid, alias.CustomDwellingSid);
	}

	private static void LogDonorAliasOnce(string rawSid, string citySid, string customDwellingSid)
	{
		var key = rawSid + "|" + citySid;
		if (!LoggedDonorAliases.Add(key))
			return;
		Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: release random-hire " + rawSid + " will use " + customDwellingSid + " art on maps where " + citySid + " is present.");
	}

	private static void LogAmbiguousDonorAlias(string rawSid, List<Homm3CustomFactionRegistry.DwellingDonorAlias> aliases)
	{
		if (!LoggedAmbiguousDonorAlias.Add(rawSid))
			return;
		var seen = new List<string>();
		for (var i = 0; i < aliases.Count; i++)
		{
			if (SeenCitySids.Contains(aliases[i].CitySid))
				seen.Add(aliases[i].CitySid + "->" + aliases[i].CustomDwellingSid);
		}
		Plugin.LogSource?.LogWarning("HoMM3 custom dwelling billboard: refusing donor-only reverse lookup for " + rawSid + " because multiple custom cities are present: " + string.Join(", ", seen) + ".");
	}

	private static void LogDonorAliasRefused(string rawSid, List<Homm3CustomFactionRegistry.DwellingDonorAlias> aliases)
	{
		if (!LoggedDonorAliasRefused.Add(rawSid))
			return;
		var candidates = new List<string>();
		for (var i = 0; i < aliases.Count; i++)
			candidates.Add(aliases[i].CitySid + "->" + aliases[i].CustomDwellingSid);
		Plugin.LogSource?.LogInfo("HoMM3 custom dwelling billboard: refusing donor barracks sid='" + rawSid + "' without exact custom hire payload; candidates=" + string.Join(", ", candidates) + ".");
	}

	private static bool TryGetFirstPrefabArray(object owner, out object prefs, out GameObject prefab)
	{
		prefs = null;
		prefab = null;
		prefs = GetMemberValue(owner, "prefs")
		        ?? GetMemberValue(owner, "buwz")
		        ?? GetMemberValue(owner, "bvlm")
		        ?? GetMemberValue(owner, "_bvlm_k__BackingField")
		        ?? GetMemberValue(owner, "<bvlm>k__BackingField")
		        ?? GetMemberValue(owner, "bvna")
		        ?? GetMemberValue(owner, "_bvna_k__BackingField")
		        ?? GetMemberValue(owner, "<bvna>k__BackingField")
		        ?? GetMemberValue(owner, "bvln")
		        ?? GetMemberValue(owner, "_bvln_k__BackingField");
		if (prefs is GameObject[] managed && managed.Length > 0)
		{
			prefab = managed[0];
			return true;
		}
		if (prefs is Il2CppReferenceArray<GameObject> il2Cpp && il2Cpp.Length > 0)
		{
			prefab = il2Cpp[0];
			return true;
		}
		return false;
	}

	private static bool TryGetFirstPrefabArrayReflective(object owner, out object prefs, out GameObject prefab)
	{
		prefs = null;
		prefab = null;
		if (owner == null)
			return false;
		prefs = GetMemberValue(owner, "prefs")
		        ?? GetMemberValue(owner, "buwz")
		        ?? GetMemberValue(owner, "bvnx")
		        ?? GetMemberValue(owner, "_bvnx_k__BackingField")
		        ?? GetMemberValue(owner, "<bvnx>k__BackingField")
		        ?? GetMemberValue(owner, "bvlm")
		        ?? GetMemberValue(owner, "_bvlm_k__BackingField")
		        ?? GetMemberValue(owner, "<bvlm>k__BackingField")
		        ?? GetMemberValue(owner, "bvna")
		        ?? GetMemberValue(owner, "_bvna_k__BackingField")
		        ?? GetMemberValue(owner, "<bvna>k__BackingField")
		        ?? GetMemberValue(owner, "bvln")
		        ?? GetMemberValue(owner, "_bvln_k__BackingField");
		if (prefs is GameObject[] managed && managed.Length > 0)
		{
			prefab = managed[0];
			return true;
		}
		if (prefs is Il2CppReferenceArray<GameObject> il2Cpp && il2Cpp.Length > 0)
		{
			prefab = il2Cpp[0];
			return true;
		}
		return false;
	}

	private static void SetFirstPrefab(object prefs, GameObject prefab)
	{
		if (prefs is GameObject[] managed)
			managed[0] = prefab;
		else if (prefs is Il2CppReferenceArray<GameObject> il2Cpp)
			il2Cpp[0] = prefab;
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null)
			return null;
		// Il2CppInterop exposes native fields as properties (e.g. field_Private_ObjHire_0 on the live hire world
		// object). Golden Era keeps the field-only read it shipped with; other builds also read interop
		// properties, behind the same name gate as TrySetMemberValue (no prop_/get_/backing-field names).
		var readProperties = !GameBuild.IsGolden && CanUseInteropProperty(name);
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (f != null)
				return f.GetValue(obj);
			if (!readProperties)
				continue;
			var p = t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (p != null && p.CanRead && p.GetIndexParameters().Length == 0)
				return p.GetValue(obj);
		}
		return null;
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

	private static object InvokeFirstNoArg(object obj, Type expectedReturnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null || expectedReturnType == null || symbol.NameHints == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			for (var i = 0; i < symbol.NameHints.Length; i++)
			{
				var name = symbol.NameHints[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				MethodInfo method;
				try { method = t.GetMethod(name, flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null || !expectedReturnType.IsAssignableFrom(method.ReturnType))
					continue;
				try { return method.Invoke(obj, null); }
				catch { return null; }
			}
		}
		return null;
	}

	private static string DescribeObject(object obj)
	{
		if (obj == null)
			return "<null>";
		try
		{
			return obj.GetType().FullName ?? obj.GetType().Name;
		}
		catch
		{
			return "<unreadable>";
		}
	}

	private static string DescribeAvailableMembers(object obj, int max)
	{
		if (obj == null)
			return "<null>";
		var parts = new List<string>();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		try
		{
			for (var t = obj.GetType(); t != null && parts.Count < max; t = t.BaseType)
			{
				foreach (var f in t.GetFields(flags))
				{
					if (parts.Count >= max)
						break;
					parts.Add(f.Name + ":" + DescribeMemberValue(obj, f));
				}
			}
		}
		catch (Exception ex)
		{
			parts.Add("error:" + ex.GetType().Name);
		}
		return parts.Count == 0 ? "<none>" : string.Join(", ", parts);
	}

	private static string DescribeMemberValue(object owner, MemberInfo member)
	{
		try
		{
			object value = null;
			if (member is not FieldInfo field)
				return "<skipped>";
			value = field.GetValue(owner);
			if (value == null)
				return "<null>";
			if (value is string s)
				return "'" + s + "'";
			if (value is int i)
				return i.ToString();
			if (value is bool b)
				return b ? "true" : "false";
			if (value is float f)
				return f.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
			return value.GetType().FullName ?? value.GetType().Name;
		}
		catch (Exception ex)
		{
			return "<" + ex.GetType().Name + ">";
		}
	}

	private static bool CanUseInteropProperty(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return false;
		if (name.StartsWith("prop_", StringComparison.Ordinal)
		    || name.StartsWith("get_", StringComparison.Ordinal)
		    || name.StartsWith("<", StringComparison.Ordinal)
		    || name.StartsWith("_", StringComparison.Ordinal)
		    || name.EndsWith("k__BackingField", StringComparison.Ordinal))
			return false;
		return true;
	}

	private static Type GetHexType(string name)
	{
		var type = typeof(Hex.Configs.ObjCityConfig).Assembly.GetType(name, throwOnError: false);
		if (type != null)
			return type;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try { type = asm.GetType(name, throwOnError: false); }
			catch { type = null; }
			if (type != null)
				return type;
		}
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types; }
			catch { continue; }
			if (types == null)
				continue;
			for (var i = 0; i < types.Length; i++)
			{
				type = types[i];
				if (type == null)
					continue;
				if (string.Equals(type.Name, name, StringComparison.Ordinal) || string.Equals(type.FullName, name, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	private static Type GetFirstHexType(string id, string[] names)
	{
		if (names == null || names.Length == 0)
			return null;
		return GameMember.FindTypeFromHints(id, names, hint => GetHexType(hint));
	}

	private static void TrySetMemberValue(object obj, string name, object value)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (f != null)
			{
				f.SetValue(obj, value);
				return;
			}
			if (!CanUseInteropProperty(name))
				continue;
			var p = t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (p != null && p.CanWrite)
			{
				p.SetValue(obj, value);
				return;
			}
		}
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
			if (listObj is not System.Collections.IEnumerable enumerable)
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

	private static IEnumerable<string> EnumerateStringList(object listObj)
	{
		foreach (var item in EnumerateIl2CppList(listObj))
		{
			if (item is string sid && !string.IsNullOrWhiteSpace(sid))
				yield return sid;
		}
	}

	private static bool HasVisual(GameObject root)
	{
		return root && root.transform.Find(VisualRootName) != null;
	}

	private static bool HasAppliedLiveRoot(GameObject root, string sid)
	{
		return root && !string.IsNullOrWhiteSpace(sid) && AppliedLiveRootKeys.Contains(BuildLiveRootKey(root, sid));
	}

	private static void EnsureAppliedBillboardSuppressesDonor(GameObject root, string sid)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return;
		if (!HasVisualForSid(root, sid))
			return;
		HideExistingRenderers(root);
	}

	private static void MarkAppliedLiveRoot(GameObject root, string sid)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return;
		AppliedLiveRootKeys.Add(BuildLiveRootKey(root, sid));
	}

	private static string BuildLiveRootKey(GameObject root, string sid)
	{
		return root.GetInstanceID().ToString() + "|" + sid;
	}

	private static void HideExistingRenderers(GameObject root)
	{
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderVisual(r.transform))
				continue;
			r.enabled = false;
		}
	}

	private static bool IsUnderVisual(Transform t)
	{
		for (var cur = t; cur != null; cur = cur.parent)
		{
			if (cur.name == VisualRootName)
				return true;
			// Our own HoMM3 mesh instance (and its FX / animation children) is a visual too.
			var name = cur.name ?? string.Empty;
			if (name.StartsWith(Homm3MapBuildingMeshBundle.MeshRootPrefix, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static Renderer FindBestMapDonorRenderer(GameObject root)
	{
		Renderer fallback = null;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderVisual(r.transform))
				continue;
			fallback ??= r;
			var m = r.sharedMaterial;
			if (m && m.shader && m.shader.name.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
				return r;
		}
		return fallback;
	}

	private static Mesh GetOrCreateQuadMesh()
	{
		if (_quadMesh)
			return _quadMesh;
		_quadMesh = new Mesh { name = "HOMM3_stronghold_dwelling_quad" };
		_quadMesh.vertices = new[] { new Vector3(-0.5f, -0.5f, 0f), new Vector3(0.5f, -0.5f, 0f), new Vector3(-0.5f, 0.5f, 0f), new Vector3(0.5f, 0.5f, 0f) };
		_quadMesh.uv = new[] { new Vector2(0f, 0f), new Vector2(1f, 0f), new Vector2(0f, 1f), new Vector2(1f, 1f) };
		_quadMesh.uv2 = _quadMesh.uv;
		_quadMesh.colors = new[] { Color.white, Color.white, Color.white, Color.white };
		_quadMesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
		_quadMesh.RecalculateNormals();
		_quadMesh.RecalculateBounds();
		return _quadMesh;
	}
}
