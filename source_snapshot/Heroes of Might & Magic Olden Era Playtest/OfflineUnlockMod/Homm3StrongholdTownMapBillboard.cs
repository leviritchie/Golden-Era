using System;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdTownMapBillboard
{
	private const string CitySid = "homm3_stronghold_city";
	private const string BillboardRootName = "homm3_stronghold_city_homm3_billboard";
	private const string ImageRelativePath = "homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcstrc0.dir/00_00.png";
	private const float BillboardHeight = 4.5f;
	private const float BillboardLiftRatio = 0.5f;
	private const float BillboardGroundClearance = 0.08f;
	private const float BillboardSouthOffset = 0.22f;
	private const int TextureBottomPaddingPixels = 96;

	private static Texture2D _texture;
	private static int _textureVisibleWidth;
	private static int _textureVisibleHeight;
	private static int _textureBottomPaddingPixels;
	private static Material _material;
	private static int _materialDiagRemaining = 4;
	private static Mesh _quadMesh;
	private static bool _registered;
	private static bool _releaseMetaRegistered;
	private static bool _loggedApplied;
	private static bool _loggedLiveApplied;
	private static bool _loggedMissingImage;
	private static int _loggedPathMiss;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		try
		{
			var metaType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId, GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints);
			if (metaType == null)
			{
				log?.LogWarning("HoMM3 Stronghold town billboard: MapObjectMeta type not found.");
				return;
			}
			var metaPatched = 0;
			foreach (var m in FindMapObjectMetaResourceHooks(metaType))
			{
				harmony.Patch(
					m,
					postfix: new HarmonyMethod(typeof(Homm3StrongholdTownMapBillboard), nameof(PostfixMapObjectMetaInitResources)));
				metaPatched++;
			}
			if (metaPatched == 0)
				log?.LogWarning("HoMM3 Stronghold town billboard: buv/MapObjectMeta resource hooks not found.");

			var objectType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId, GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints);
			if (objectType == null)
			{
				log?.LogWarning("HoMM3 Stronghold town billboard: MapObject type not found.");
				return;
			}
			var objectPatched = 0;
			foreach (var m in FindMapObjectInitHooks(objectType, metaType))
			{
				harmony.Patch(
					m,
					postfix: new HarmonyMethod(typeof(Homm3StrongholdTownMapBillboard), nameof(PostfixMapObjectInit)));
				objectPatched++;
			}
			if (objectPatched == 0)
				log?.LogWarning("HoMM3 Stronghold town billboard: but/MapObject.Init hooks not found.");

			_registered = metaPatched > 0 || objectPatched > 0;
			log?.LogInfo(
				"HoMM3 Stronghold town billboard: registered map-object hooks "
				+ "(meta="
				+ metaPatched
				+ ", live="
				+ objectPatched
				+ ").");
		}
		catch (Exception ex)
		{
			log?.LogError("HoMM3 Stronghold town billboard: hook registration failed: " + ex);
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
			// Release bvd.Init(ObjectConfig) runs while ObjectConfig string fields can still point at
			// transient Il2Cpp memory. Reading ConfigElementBase.id here has caused native AVs.
			// Apply the visible billboard from the placed bvb.Init(...) hook instead.

			var objectType = GetFirstHexType(GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId, GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints);
			if (objectType == null)
				throw new InvalidOperationException("release live placed map-object type did not resolve.");
			var objectPatched = 0;
			foreach (var m in FindReleaseMapObjectInitHooks(objectType, metaType))
			{
				harmony.Patch(
					m,
					postfix: new HarmonyMethod(typeof(Homm3StrongholdTownMapBillboard), nameof(PostfixReleaseMapObjectInit)));
				objectPatched++;
			}
			if (objectPatched == 0)
				throw new InvalidOperationException("no release placed map-object init surfaces resolved.");

			_registered = true;
			log?.LogInfo(
				"HoMM3 Stronghold town billboard release slice: registered map-object hooks "
				+ "(meta="
				+ metaPatched
				+ ", live="
				+ objectPatched
				+ ").");
		}
		catch (Exception ex)
		{
			if (required)
			{
				log?.LogFatal("HoMM3 Stronghold town billboard release slice: required hook registration failed: " + ex);
				throw;
			}
			log?.LogWarning("HoMM3 Stronghold town billboard release slice: hook registration failed: " + ex);
		}
	}

	internal static int PrewarmManifestTexture(ManualLogSource log)
	{
		if (!GetOrCreateTexture(log))
			throw new InvalidOperationException("Failed to prewarm HoMM3 Stronghold town map billboard texture.");
		return 1;
	}

	private static MethodInfo[] FindMapObjectMetaResourceHooks(Type metaType)
	{
		if (metaType == null)
			return Array.Empty<MethodInfo>();

		var list = new System.Collections.Generic.List<MethodInfo>();
		foreach (var m in metaType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (!string.Equals(m.Name, "Init", StringComparison.Ordinal))
				continue;
			if (m.IsSpecialName || m.ReturnType != typeof(void))
				continue;
			if (m.GetParameters().Length != 0)
				continue;

			// InitResources is obfuscated in this build. The no-arg void methods are all MapObjectMeta
			// lifecycle/resource aliases; the postfix is idempotent and only mutates the Stronghold city.
			list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindMapObjectInitHooks(Type objectType, Type metaType)
	{
		if (objectType == null)
			return Array.Empty<MethodInfo>();
		var list = new System.Collections.Generic.List<MethodInfo>();
		foreach (var m in objectType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 5)
				continue;
			if (metaType != null && ps[1].ParameterType != metaType)
				continue;
			list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindReleaseMapObjectMetaResourceHooks(Type metaType)
	{
		if (metaType == null)
			return Array.Empty<MethodInfo>();

		var list = new System.Collections.Generic.List<MethodInfo>();
		foreach (var m in metaType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.IsSpecialName || m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 1)
				continue;
			if (ps[0].ParameterType.FullName == "Hex.Map.ObjectConfig")
				list.Add(m);
		}
		return list.ToArray();
	}

	private static MethodInfo[] FindReleaseMapObjectInitHooks(Type objectType, Type metaType)
	{
		if (objectType == null)
			return Array.Empty<MethodInfo>();

		var list = new System.Collections.Generic.List<MethodInfo>();
		foreach (var m in objectType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (!string.Equals(m.Name, "Init", StringComparison.Ordinal))
				continue;
			if (m.IsSpecialName || m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 5)
				continue;
			if (metaType != null && ps[1].ParameterType != metaType)
				continue;
			if (ps[2].ParameterType != typeof(int) || ps[3].ParameterType != typeof(byte) || ps[4].ParameterType != typeof(float))
				continue;
			list.Add(m);
		}
		return list.ToArray();
	}

	private static void PostfixReleaseMapObjectMetaInitResources(object __instance)
	{
		try
		{
			TryReplaceMetaPrefabReflective(__instance);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town billboard: release MapObjectMeta postfix failed: " + ex.Message);
		}
	}

	private static void PostfixMapObjectMetaInitResources(object __instance)
	{
		try
		{
			if (!IsStrongholdMeta(__instance))
				return;
			if (!TryGetFirstPrefabArray(__instance, out var prefs, out var prefab)
			    || !prefab
			    || HasBillboardMarker(prefab))
				return;

			var clone = UnityEngine.Object.Instantiate(prefab);
			if (!clone)
				return;
			if (!ApplyBillboardPrefab(clone, Plugin.LogSource))
			{
				UnityEngine.Object.Destroy(clone);
				return;
			}

			SetFirstPrefab(prefs, clone);
			TrySetMemberValue(__instance, "IsCombinedGeometryOk", false);
			TrySetMemberValue(__instance, "<IsCombinedGeometryOk>k__BackingField", false);
			TrySetMemberValue(__instance, "buxc", false);
			TrySetMemberValue(__instance, "<buxc>k__BackingField", false);
			if (!_loggedApplied)
			{
				_loggedApplied = true;
				Plugin.LogSource?.LogInfo("HoMM3 Stronghold town billboard: replaced MapObjectMeta prefab for " + CitySid + ".");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town billboard: MapObjectMeta postfix failed: " + ex.Message);
		}
	}

	private static void PostfixReleaseMapObjectInit(object __instance)
	{
		try
		{
			if (__instance == null)
				return;
			var meta = GetReleaseMapObjectMeta(__instance);
			if (!IsStrongholdMetaReflective(meta))
				return;
			var root = GetReleaseMapObjectRoot(__instance);
			if (!root || HasBillboardMarker(root))
				return;
			if (!ApplyBillboardPrefab(root, Plugin.LogSource))
				return;
			Homm3StrongholdDwellingMapBillboard.NoteStrongholdCitySeen();
			LogLiveApplied();
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town billboard: release MapObject.Init postfix failed: " + ex.Message);
		}
	}

	private static void PostfixMapObjectInit(object __instance)
	{
		try
		{
			if (__instance == null)
				return;
			var meta = GetReleaseMapObjectMeta(__instance);
			if (!IsStrongholdMeta(meta))
				return;
			var root = GetReleaseMapObjectRoot(__instance);
			if (!root || HasBillboardMarker(root))
				return;
			if (!ApplyBillboardPrefab(root, Plugin.LogSource))
				return;
			Homm3StrongholdDwellingMapBillboard.NoteStrongholdCitySeen();
			LogLiveApplied();
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town billboard: MapObject.Init postfix failed: " + ex.Message);
		}
	}

	private static bool TryReplaceMetaPrefab(object meta)
	{
		if (!IsStrongholdMeta(meta))
			return false;

		if (!TryGetFirstPrefabArray(meta, out var prefs, out var prefab) || !prefab || HasBillboardMarker(prefab))
			return false;

		var clone = UnityEngine.Object.Instantiate(prefab);
		if (!clone)
			return false;
		if (!ApplyBillboardPrefab(clone, Plugin.LogSource))
		{
			UnityEngine.Object.Destroy(clone);
			return false;
		}

		SetFirstPrefab(prefs, clone);
		TrySetMemberValue(meta, "buxc", false);
		TrySetMemberValue(meta, "<buxc>k__BackingField", false);

		if (!_loggedApplied)
		{
			_loggedApplied = true;
			Plugin.LogSource?.LogInfo("HoMM3 Stronghold town billboard: replaced buv/MapObjectMeta prefab for " + CitySid + ".");
		}
		return true;
	}

	private static bool TryReplaceMetaPrefabReflective(object meta)
	{
		if (!IsStrongholdMetaReflective(meta))
			return false;
		if (!TryGetFirstPrefabArray(meta, out var prefs, out var prefab)
		    || !prefab
		    || HasBillboardMarker(prefab))
			return false;

		var clone = UnityEngine.Object.Instantiate(prefab);
		if (!clone)
			return false;
		if (!ApplyBillboardPrefab(clone, Plugin.LogSource))
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
		if (!_loggedApplied)
		{
			_loggedApplied = true;
			Plugin.LogSource?.LogInfo("HoMM3 Stronghold town billboard: replaced MapObjectMeta prefab for " + CitySid + ".");
		}
		return true;
	}

	private static void LogLiveApplied()
	{
		if (_loggedLiveApplied)
			return;
		_loggedLiveApplied = true;
		Plugin.LogSource?.LogInfo("HoMM3 Stronghold town billboard: applied live billboard to " + CitySid + " map object.");
	}

	private static object GetReleaseMapObjectMeta(object instance)
	{
		return GetMemberValue(instance, "meta")
		       ?? GetMemberValue(instance, "buvq")
		       ?? GetMemberValue(instance, "bvmo")
		       ?? GetMemberValue(instance, "_bvmo_k__BackingField")
		       ?? GetMemberValue(instance, "<bvmo>k__BackingField")
		       ?? GetMemberValue(instance, "bvkd")
		       ?? GetMemberValue(instance, "bvlr")
		       ?? GetMemberValue(instance, "_bvkd_k__BackingField")
		       ?? GetMemberValue(instance, "<bvkd>k__BackingField")
		       ?? GetMemberValue(instance, "_bvlr_k__BackingField")
		       ?? GetMemberValue(instance, "<bvlr>k__BackingField");
	}

	private static GameObject GetReleaseMapObjectRoot(object instance)
	{
		var root = GetMemberValue(instance, "gameObject") as GameObject
		           ?? GetMemberValue(instance, "buwc") as GameObject
		           ?? GetMemberValue(instance, "bvna") as GameObject
		           ?? GetMemberValue(instance, "_bvna_k__BackingField") as GameObject
		           ?? GetMemberValue(instance, "<bvna>k__BackingField") as GameObject
		           ?? GetMemberValue(instance, "bvnd") as GameObject
		           ?? GetMemberValue(instance, "_bvkp_k__BackingField") as GameObject
		           ?? GetMemberValue(instance, "<bvkp>k__BackingField") as GameObject
		           ?? GetMemberValue(instance, "_bvmd_k__BackingField") as GameObject
		           ?? GetMemberValue(instance, "<bvmd>k__BackingField") as GameObject
		           ?? GetMemberValue(instance, "bvks") as GameObject
		           ?? GetMemberValue(instance, "bvmg") as GameObject;
		if (root)
			return root;

		var transform = GetMemberValue(instance, "bvnb") as Transform
		                ?? GetMemberValue(instance, "_bvnb_k__BackingField") as Transform
		                ?? GetMemberValue(instance, "<bvnb>k__BackingField") as Transform
		                ?? GetMemberValue(instance, "bvne") as Transform
		                ?? GetMemberValue(instance, "bvkq") as Transform
		                ?? GetMemberValue(instance, "_bvkq_k__BackingField") as Transform
		                ?? GetMemberValue(instance, "<bvkq>k__BackingField") as Transform
		                ?? GetMemberValue(instance, "_bvme_k__BackingField") as Transform
		                ?? GetMemberValue(instance, "<bvme>k__BackingField") as Transform
		                ?? GetMemberValue(instance, "bvkt") as Transform
		                ?? GetMemberValue(instance, "bvmh") as Transform;
		return transform ? transform.gameObject : null;
	}

	internal static void PostfixResGetGameObject([HarmonyArgument(0)] string resPath, ref GameObject __result)
	{
		try
		{
			if (!IsStrongholdTownResourcePath(resPath))
			{
				if (_loggedPathMiss < 60 && resPath != null
				    && (resPath.IndexOf("city", StringComparison.OrdinalIgnoreCase) >= 0
				        || resPath.IndexOf("town", StringComparison.OrdinalIgnoreCase) >= 0
				        || resPath.IndexOf("stronghold", StringComparison.OrdinalIgnoreCase) >= 0))
				{
					_loggedPathMiss++;
					Plugin.LogSource?.LogInfo(
						"HoMM3 Stronghold town billboard: city-like path (no match) '" + resPath + "'.");
				}
				return;
			}

			if (!__result)
				return;

			if (HasBillboardMarker(__result))
				return;

			var clone = UnityEngine.Object.Instantiate(__result);
			if (!clone)
				return;

			if (!ApplyBillboardPrefab(clone, Plugin.LogSource))
			{
				UnityEngine.Object.Destroy(clone);
				return;
			}
			__result = clone;

			if (!_loggedApplied)
			{
				_loggedApplied = true;
				Plugin.LogSource?.LogInfo(
					"HoMM3 Stronghold town billboard: replaced resource '"
					+ resPath
					+ "' with prefab clone carrying AVCDUNG0.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town billboard: ResManager postfix failed: " + ex.Message);
		}
	}

	private static bool IsStrongholdTownResourcePath(string resPath)
	{
		if (string.IsNullOrWhiteSpace(resPath))
			return false;
		var p = resPath.Trim().Replace('\\', '/');
		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		return string.Equals(p, "objects/interactive/dungeon_city", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(p, "interactive/dungeon_city", StringComparison.OrdinalIgnoreCase)
		       || p.EndsWith("/interactive/dungeon_city", StringComparison.OrdinalIgnoreCase);
	}

	private static bool HasBillboardMarker(GameObject root)
	{
		if (!root)
			return false;
		var transforms = root.GetComponentsInChildren<Transform>(true);
		for (var i = 0; transforms != null && i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (t && t.name == BillboardRootName)
				return true;
		}
		return false;
	}

	private static bool ApplyBillboardPrefab(GameObject prefabRoot, ManualLogSource log)
	{
		if (!prefabRoot)
			return false;
		var donorRenderer = FindBestMapDonorRenderer(prefabRoot);
		var donorMaterial = donorRenderer ? donorRenderer.sharedMaterial : null;
		var material = GetOrCreateMaterial(donorMaterial, log);
		if (!material)
			return false;

		HideExistingRenderers(prefabRoot);

		var billboardRoot = prefabRoot.transform.Find(BillboardRootName);
		if (billboardRoot == null)
		{
			var go = new GameObject(BillboardRootName);
			billboardRoot = go.transform;
			billboardRoot.SetParent(prefabRoot.transform, false);
		}

		var billboardScale = GetBillboardScale(material.mainTexture);
		var bottomPaddingWorld = GetBottomPaddingWorld(material.mainTexture, billboardScale);
		billboardRoot.localPosition = Vector3.up * ((billboardScale.y * BillboardLiftRatio) - bottomPaddingWorld + BillboardGroundClearance)
		                              + Vector3.back * BillboardSouthOffset;
		billboardRoot.localRotation = Quaternion.identity;
		billboardRoot.localScale = Vector3.one;
		billboardRoot.gameObject.layer = prefabRoot.layer;

		var quad = billboardRoot.Find("quad");
		GameObject quadGo;
		if (quad == null)
		{
			quadGo = new GameObject("quad");
			quadGo.transform.SetParent(billboardRoot, false);
		}
		else
			quadGo = quad.gameObject;

		quadGo.layer = prefabRoot.layer;
		quadGo.transform.localRotation = Quaternion.identity;
		quadGo.transform.localPosition = new Vector3(0f, 0f, -0.04f);
		quadGo.transform.localScale = billboardScale;

		var mf = quadGo.GetComponent<MeshFilter>();
		if (!mf)
			mf = quadGo.AddComponent<MeshFilter>();
		var nd = quadGo.GetComponent<MeshRenderer>();
		if (!nd)
			nd = quadGo.AddComponent<MeshRenderer>();

		mf.sharedMesh = GetOrCreateQuadMesh();
		nd.sharedMaterial = material;
		ClearRendererPropertyBlock(nd);
		if (donorRenderer)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donorRenderer, billboardRoot.gameObject);
		else
		{
			nd.shadowCastingMode = ShadowCastingMode.On;
			nd.receiveShadows = true;
		}
		// Keep cast shadows for map readability, but do not receive terrain shadows on the upright cutout.
		nd.shadowCastingMode = ShadowCastingMode.On;
		nd.receiveShadows = false;
		nd.allowOcclusionWhenDynamic = false;
		Homm3BattleBillboardCameraFacing.TryAttachMapObject(billboardRoot, log);
		if (_materialDiagRemaining > 0)
		{
			_materialDiagRemaining--;
			log?.LogInfo(
				"HoMM3 Stronghold town billboard: applied native billboard material donor=["
				+ DescribeMaterial(donorMaterial)
				+ "] final=["
				+ DescribeMaterial(material)
				+ "] rendererFlags="
				+ DescribeRendererFlags(nd)
				+ " scale="
				+ billboardScale.ToString("0.###")
				+ " bottomPaddingWorld="
				+ bottomPaddingWorld.ToString("0.###")
				+ ".");
		}
		return true;
	}

	private static Vector3 GetBillboardScale(Texture texture)
	{
		if (texture && texture.height > 0 && _textureVisibleWidth > 0 && _textureVisibleHeight > 0)
		{
			var width = BillboardHeight * _textureVisibleWidth / _textureVisibleHeight;
			var height = BillboardHeight * texture.height / _textureVisibleHeight;
			return new Vector3(width, height, 1f);
		}
		var fallbackWidth = BillboardHeight;
		if (texture && texture.height > 0)
			fallbackWidth = BillboardHeight * texture.width / texture.height;
		return new Vector3(fallbackWidth, BillboardHeight, 1f);
	}

	private static float GetBottomPaddingWorld(Texture texture, Vector3 billboardScale)
	{
		if (!texture || texture.height <= 0 || _textureBottomPaddingPixels <= 0)
			return 0f;
		return billboardScale.y * _textureBottomPaddingPixels / texture.height;
	}

	private static void TryAttachFogSync(GameObject billboardRoot, ManualLogSource log)
	{
		if (!billboardRoot)
			return;
		try
		{
			EsquirePikemanVisuals.EnsureMapBillboardFogSyncTypeRegistered(log);
			if (!HasFogSyncComponent(billboardRoot))
			{
				billboardRoot.AddComponent<EsquirePikemanMapBillboardFogSync>();
				log?.LogInfo("HoMM3 Stronghold town billboard: attached fog sync to AVCDUNG0 billboard.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Stronghold town billboard: fog sync attach failed: " + ex.Message);
		}
	}

	private static bool HasFogSyncComponent(GameObject root)
	{
		if (!root)
			return false;
		foreach (var c in root.GetComponentsInChildren<Component>(true))
		{
			if (!c)
				continue;
			if (string.Equals(c.GetType().Name, "EsquirePikemanMapBillboardFogSync", StringComparison.Ordinal))
				return true;
		}

		return false;
	}

	private static bool IsStrongholdMeta(object meta)
	{
		if (meta == null)
			return false;
		var config = GetMemberValue(meta, "config") ?? GetMemberValue(meta, "buwy") ?? GetMemberValue(meta, "bvnw") ?? GetMemberValue(meta, "bvll") ?? GetMemberValue(meta, "bvmz") ?? GetMemberValue(meta, "bvlm");
		if (config == null)
			return false;
		var sid = GetMemberValue(config, "sid") as string
		          ?? GetMemberValue(config, "cluu") as string
		          ?? GetMemberValue(config, "id") as string
		          ?? GetMemberValue(config, "cmql") as string
		          ?? GetMemberValue(config, "cmsc") as string;
		return string.Equals(sid, CitySid, StringComparison.Ordinal);
	}

	private static bool IsStrongholdMetaReflective(object meta)
	{
		if (meta == null)
			return false;
		var config = GetMemberValue(meta, "config") ?? GetMemberValue(meta, "buwy") ?? GetMemberValue(meta, "bvnw") ?? GetMemberValue(meta, "bvll") ?? GetMemberValue(meta, "bvmz") ?? GetMemberValue(meta, "bvlm");
		if (config == null)
			return false;
		var sid = GetMemberValue(config, "sid") as string
		          ?? GetMemberValue(config, "cluu") as string
		          ?? GetMemberValue(config, "id") as string
		          ?? GetMemberValue(config, "cmql") as string
		          ?? GetMemberValue(config, "cmsc") as string;
		return string.Equals(sid, CitySid, StringComparison.Ordinal);
	}

	private static bool TryGetFirstPrefabArray(object owner, out object prefs, out GameObject prefab)
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
		if (prefs is GameObject[] managed)
		{
			if (managed.Length == 0)
				return false;
			prefab = managed[0];
			return true;
		}

		if (prefs is Il2CppReferenceArray<GameObject> il2Cpp)
		{
			if (il2Cpp.Length == 0)
				return false;
			prefab = il2Cpp[0];
			return true;
		}

		return false;
	}

	private static void SetFirstPrefab(object prefs, GameObject prefab)
	{
		if (prefs is GameObject[] managed)
		{
			managed[0] = prefab;
			return;
		}
		if (prefs is Il2CppReferenceArray<GameObject> il2Cpp)
			il2Cpp[0] = prefab;
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null)
			return null;
		var t = obj.GetType();
		var p = t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		if (p != null)
			return p.GetValue(obj);
		var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		return f == null ? null : f.GetValue(obj);
	}

	private static Type GetHexType(string name)
	{
		return typeof(Hex.Configs.ObjCityConfig).Assembly.GetType(name, throwOnError: false);
	}

	private static Type GetFirstHexType(string id, string[] names)
	{
		if (names == null || names.Length == 0)
			return null;
		return GameMember.FindTypeFromHints(id, names, hint => GetHexType(hint));
	}

	private static void TrySetMemberValue(object obj, string name, object value)
	{
		if (obj == null)
			return;
		var t = obj.GetType();
		var p = t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		if (p != null && p.CanWrite)
		{
			p.SetValue(obj, value);
			return;
		}
		var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		if (f != null)
			f.SetValue(obj, value);
	}

	private static void HideExistingRenderers(GameObject root)
	{
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			if (IsUnderMarker(r.transform))
				continue;
			r.enabled = false;
		}
	}

	private static bool IsUnderMarker(Transform t)
	{
		while (t != null)
		{
			if (t.name == BillboardRootName)
				return true;
			t = t.parent;
		}
		return false;
	}

	private static Material GetOrCreateMaterial(Material donor, ManualLogSource log)
	{
		if (_material)
			return _material;
		var tex = GetOrCreateTexture(log);
		if (!tex)
			return null;

		var unitStyleDonor = FindLoadedUnitStyleHexLitDonor(log);
		var selectedDonor = unitStyleDonor ? unitStyleDonor : donor;
		if (selectedDonor)
		{
			_material = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(
				selectedDonor,
				tex,
				"HOMM3_AVCSTRC0_map_billboard_unit_donor_hexlit_mat");
			if (_material)
			{
				log?.LogInfo(
					"HoMM3 Stronghold town billboard: selected Hex/Lit donor for town material source="
					+ (unitStyleDonor ? "loaded-unit-style" : "city-fallback")
					+ " donor=["
					+ DescribeMaterial(selectedDonor)
					+ "].");
				return _material;
			}
		}

		log?.LogWarning("HoMM3 Stronghold town billboard: no usable Hex/Lit donor found; town billboard material not created.");
		return null;
	}

	private static Material FindLoadedUnitStyleHexLitDonor(ManualLogSource log)
	{
		Material best = null;
		var bestScore = float.NegativeInfinity;
		try
		{
			var materials = Resources.FindObjectsOfTypeAll<Material>();
			for (var i = 0; materials != null && i < materials.Length; i++)
			{
				var m = materials[i];
				if (!m || !m.shader)
					continue;
				var shaderName = m.shader.name ?? string.Empty;
				if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				var score = ScoreUnitStyleHexLitDonor(m);
				if (score <= bestScore)
					continue;
				bestScore = score;
				best = m;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Stronghold town billboard: loaded Hex/Lit donor scan failed: " + ex.Message);
		}

		if (best)
		{
			log?.LogInfo(
				"HoMM3 Stronghold town billboard: best loaded unit-style Hex/Lit donor candidate score="
				+ bestScore.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
				+ " donor=["
				+ DescribeMaterial(best)
				+ "].");
		}
		return bestScore > 0f ? best : null;
	}

	private static float ScoreUnitStyleHexLitDonor(Material material)
	{
		if (!material)
			return float.NegativeInfinity;
		var name = material.name ?? string.Empty;
		var score = 0f;

		if (material.renderQueue is >= 2000 and <= 2500)
			score += 200f;
		if (HasKeyword(material, "HEX_DITHER_FADE_ENABLED"))
			score += 500f;
		if (HasKeyword(material, "HEX_ALPHA_CLIP_ENABLED"))
			score += 350f;
		if (HasKeyword(material, "HEX_EMISSION_MAP_ENABLED"))
			score += 60f;
		if (HasKeyword(material, "HEX_BLEND_INTO_TERRAIN_POSITION")
		    || HasKeyword(material, "HEX_BLEND_INTO_TERRAIN_COLOR"))
			score -= 1000f;

		if (ContainsAny(name, "troglodyte", "pet_", "minos", "medusa", "hydra"))
			score += 650f;
		if (ContainsAny(name, "byzantine", "palace", "city", "building", "terrain", "ground"))
			score -= 800f;
		if (ContainsAny(name, "weapon"))
			score -= 80f;
		if (!HasAnyMainTexture(material))
			score -= 200f;
		return score;
	}

	private static bool ContainsAny(string value, params string[] needles)
	{
		if (string.IsNullOrEmpty(value) || needles == null)
			return false;
		for (var i = 0; i < needles.Length; i++)
			if (!string.IsNullOrEmpty(needles[i]) && value.IndexOf(needles[i], StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		return false;
	}

	private static bool HasAnyMainTexture(Material material)
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

	private static void ClearRendererPropertyBlock(Renderer renderer)
	{
		if (!renderer)
			return;
		try
		{
			renderer.SetPropertyBlock(null);
		}
		catch
		{
			var empty = new MaterialPropertyBlock();
			renderer.SetPropertyBlock(empty);
		}
	}

	private static Renderer FindBestMapDonorRenderer(GameObject root)
	{
		if (!root)
			return null;
		Renderer best = null;
		var bestScore = int.MinValue;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderMarker(r.transform))
				continue;
			var m = r.sharedMaterial;
			if (!m || !m.shader)
				continue;
			var shaderName = m.shader.name ?? string.Empty;
			if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			var score = 0;
			if (r.enabled)
				score += 1000;
			if (m.renderQueue >= 2000 && m.renderQueue <= 2500)
				score += 500;
			if (HasKeyword(m, "HEX_DITHER_FADE_ENABLED"))
				score += 300;
			if (HasKeyword(m, "HEX_ALPHA_CLIP_ENABLED"))
				score += 300;
			if (r.shadowCastingMode != ShadowCastingMode.Off)
				score += 100;
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = r;
		}
		return best;
	}

	private static bool HasKeyword(Material m, string keyword)
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

	private static string DescribeMaterial(Material m)
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
		       + "]"
		       + " props=["
		       + DescribeTownMaterialProperties(m)
		       + "]";
	}

	private static string DescribeTownMaterialProperties(Material m)
	{
		if (!m)
			return string.Empty;
		return "textures="
		       + DescribeTextureSlots(m)
		       + " cutoffs="
		       + DescribeFloatProperties(m, "_AlphaClip", "_AlphaCutoff", "_Cutoff", "_AlphaClipThreshold")
		       + " colors="
		       + DescribeColorProperties(m, "_Color", "_EmissionColor")
		       + " mainTexScale="
		       + m.mainTextureScale.ToString("0.###")
		       + " mainTexOffset="
		       + m.mainTextureOffset.ToString("0.###");
	}

	private static string DescribeTextureSlots(Material m)
	{
		if (!m || !m.shader)
			return string.Empty;
		try
		{
			var result = string.Empty;
			var count = m.shader.GetPropertyCount();
			for (var i = 0; i < count; i++)
			{
				if (m.shader.GetPropertyType(i) != ShaderPropertyType.Texture)
					continue;
				var name = m.shader.GetPropertyName(i);
				if (string.IsNullOrEmpty(name) || !m.HasProperty(name))
					continue;
				var tex = m.GetTexture(name);
				if (result.Length > 0)
					result += ",";
				result += name
				          + "="
				          + (tex ? (tex.name ?? "(unnamed)") : "(null)")
				          + "@scale"
				          + m.GetTextureScale(name).ToString("0.###")
				          + "@offset"
				          + m.GetTextureOffset(name).ToString("0.###");
			}
			return result;
		}
		catch (Exception ex)
		{
			return "textureDiagFailed:" + ex.Message;
		}
	}

	private static string DescribeFloatProperties(Material m, params string[] names)
	{
		if (!m || names == null)
			return string.Empty;
		var result = string.Empty;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name) || !m.HasProperty(name))
				continue;
			if (result.Length > 0)
				result += ",";
			result += name + "=" + m.GetFloat(name).ToString("0.###");
		}
		return result;
	}

	private static string DescribeColorProperties(Material m, params string[] names)
	{
		if (!m || names == null)
			return string.Empty;
		var result = string.Empty;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name) || !m.HasProperty(name))
				continue;
			if (result.Length > 0)
				result += ",";
			result += name + "=" + m.GetColor(name).ToString("0.###");
		}
		return result;
	}

	private static string DescribeRendererFlags(Renderer r)
	{
		if (!r)
			return "(null)";
		return "layer="
		       + r.gameObject.layer
		       + " renderLayerMask="
		       + r.renderingLayerMask
		       + " shadows="
		       + r.shadowCastingMode
		       + " receiveShadows="
		       + r.receiveShadows
		       + " probes="
		       + r.lightProbeUsage
		       + "/"
		       + r.reflectionProbeUsage
		       + " occlusion="
		       + r.allowOcclusionWhenDynamic;
	}

	private static Texture2D GetOrCreateTexture(ManualLogSource log)
	{
		if (_texture)
			return _texture;

		var pluginPath = Path.Combine(
			Paths.BepInExRootPath,
			"plugins",
			"OfflineUnlockMod",
			ImageRelativePath.Replace('/', Path.DirectorySeparatorChar));
		if (!File.Exists(pluginPath))
		{
			pluginPath = Path.Combine(
				Paths.GameRootPath,
				"OfflineUnlockMod",
				ImageRelativePath.Replace('/', Path.DirectorySeparatorChar));
		}

		if (!File.Exists(pluginPath))
		{
			if (!_loggedMissingImage)
			{
				_loggedMissingImage = true;
				log?.LogWarning("HoMM3 Stronghold town billboard: missing image " + ImageRelativePath + ".");
			}
			return null;
		}

		var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		if (!TryLoadTextureImage(tex, File.ReadAllBytes(pluginPath)))
		{
			UnityEngine.Object.Destroy(tex);
			return null;
		}

		tex.name = "HOMM3_AVCstrc0_map_billboard_source";
		tex.filterMode = FilterMode.Point;
		tex.wrapMode = TextureWrapMode.Clamp;
		_textureVisibleWidth = tex.width;
		_textureVisibleHeight = tex.height;
		_texture = CreateBottomPaddedTexture(tex, TextureBottomPaddingPixels, log) ?? tex;
		_texture.filterMode = FilterMode.Point;
		_texture.wrapMode = TextureWrapMode.Clamp;
		return _texture;
	}

	private static Texture2D CreateBottomPaddedTexture(Texture2D source, int bottomPadding, ManualLogSource log)
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
				name = "HOMM3_AVCstrc0_map_billboard_padded_bottom_" + bottomPadding
			};
			var clear = new Color32(0, 0, 0, 0);
			var pixels = new Color32[width * paddedHeight];
			for (var i = 0; i < pixels.Length; i++)
				pixels[i] = clear;
			for (var y = 0; y < height; y++)
			{
				Array.Copy(
					sourcePixels,
					y * width,
					pixels,
					(y + bottomPadding) * width,
					width);
			}
			padded.SetPixels32(pixels);
			padded.Apply(false, false);
			_textureBottomPaddingPixels = bottomPadding;
			log?.LogInfo(
				"HoMM3 Stronghold town billboard: created bottom-padded texture source="
				+ width
				+ "x"
				+ height
				+ " padded="
				+ width
				+ "x"
				+ paddedHeight
				+ " bottomPad="
				+ bottomPadding
				+ ".");
			UnityEngine.Object.Destroy(source);
			return padded;
		}
		catch (Exception ex)
		{
			_textureBottomPaddingPixels = 0;
			log?.LogWarning("HoMM3 Stronghold town billboard: bottom padding texture build failed: " + ex.Message);
			return null;
		}
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

	private static Mesh GetOrCreateQuadMesh()
	{
		if (_quadMesh)
			return _quadMesh;

		_quadMesh = new Mesh { name = "HOMM3_map_billboard_quad" };
		_quadMesh.vertices = new[]
		{
			new Vector3(-0.5f, -0.5f, 0f),
			new Vector3(0.5f, -0.5f, 0f),
			new Vector3(-0.5f, 0.5f, 0f),
			new Vector3(0.5f, 0.5f, 0f)
		};
		_quadMesh.uv = new[]
		{
			new Vector2(0f, 0f),
			new Vector2(1f, 0f),
			new Vector2(0f, 1f),
			new Vector2(1f, 1f)
		};
		_quadMesh.uv2 = new[]
		{
			new Vector2(0f, 0f),
			new Vector2(1f, 0f),
			new Vector2(0f, 1f),
			new Vector2(1f, 1f)
		};
		_quadMesh.colors = new[]
		{
			Color.white,
			Color.white,
			Color.white,
			Color.white
		};
		_quadMesh.tangents = new[]
		{
			new Vector4(1f, 0f, 0f, 1f),
			new Vector4(1f, 0f, 0f, 1f),
			new Vector4(1f, 0f, 0f, 1f),
			new Vector4(1f, 0f, 0f, 1f)
		};
		_quadMesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
		_quadMesh.RecalculateNormals();
		_quadMesh.RecalculateBounds();
		return _quadMesh;
	}
}
