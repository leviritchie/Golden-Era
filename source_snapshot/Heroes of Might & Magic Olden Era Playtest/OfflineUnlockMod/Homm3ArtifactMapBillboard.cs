using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Adventure-map billboard for <c>homm3_artifact_*</c> pickups using HoMM3 AVA map frames,
/// and for <c>homm3_seer_hut</c> using the staged AVXseer0 map_object_refs frame, and for the
/// visual-only object billboards <c>homm3_objbb_&lt;def&gt;</c> (garrison, monolith, shipwreck, keymaster
/// tent...) on inert Interact hosts, whose frames come from
/// <c>tools/build_homm3_object_billboard_assets.py</c>. An object billboard that cannot draw is a LogError.
/// Donor map prefs remain a stock shell; this replaces visible renderers with a Hex/Lit quad.
/// </summary>
internal static class Homm3ArtifactMapBillboard
{
	private const string VisualRootName = "homm3_artifact_billboard";
	private const string MapFolder = "homm3_runtime_assets/artifacts/map";
	private const string SidPrefix = "homm3_artifact_";
	private const string SeerHutSid = "homm3_seer_hut";
	private const string SeerHutImageRelativePath =
		"homm3_runtime_assets/map_object_refs/homm3_seer_hut/avxseer0.dir/00_00.png";
	private const float BillboardHeight = 0.90f; // was 1.35; ~33% smaller for adventure-map read
	// Visual-only HoMM3 object billboards (experiments/campaign_port_poc/raw_translation/object_billboards.py).
	// Pinned by tools/validate_homm3_object_billboard_contract.py.
	internal const string ObjectBillboardSidPrefix = "homm3_objbb_";
	private const string ObjectBillboardFolder = "homm3_runtime_assets/map_object_refs/homm3_object_billboards";
	// Seer-hut scale: its cropped AVXseer0 frame is 59 px tall and draws 1.35 units tall, so an object
	// billboard keeps HoMM3's relative sizes (a 4-cell garrison stands taller than a tent).
	private const float ObjectBillboardUnitsPerPixel = 1.35f / 59f;
	private const float SeerHutBillboardHeight = 1.35f;
	private const float GroundClearance = 0.06f;
	private const float BillboardSouthOffset = 0.12f;

	private static readonly Dictionary<string, Texture2D> TexturesBySid = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Material> MaterialsBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissingImage = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedBillboardBundleResolution = new(StringComparer.Ordinal);
	private static readonly HashSet<string> AppliedLiveRootKeys = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedObjectBillboardApplied = new(StringComparer.Ordinal);
	private static Mesh _quadMesh;
	private static bool _registered;
	private static int _loggedApplied;
	private static int _loggedSkip;
	private static int _loggedResolveProbe;

	internal static bool IsRegistered => _registered;

	internal static void RegisterRequiredReleaseSafeMapObjectSlice(Harmony harmony, ManualLogSource log)
	{
		RegisterReleaseSafeMapObjectSlice(harmony, log, required: true);
	}

	internal static void TryRegisterReleaseSafeMapObjectSlice(Harmony harmony, ManualLogSource log)
	{
		RegisterReleaseSafeMapObjectSlice(harmony, log, required: false);
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
			var metaType = GetFirstHexType(
				GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId,
				GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints);
			var objectType = GetFirstHexType(
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId,
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints);
			if (objectType == null)
				throw new InvalidOperationException("release live placed map-object type did not resolve.");

			var patched = 0;
			foreach (var m in GameMember.FindPlacedObjectInitMethods(objectType, metaType))
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3ArtifactMapBillboard), nameof(PostfixReleaseMapObjectInit)));
				patched++;
			}
			if (patched == 0)
				throw new InvalidOperationException("no release placed map-object Init surfaces resolved for artifacts.");

			_registered = true;
			log?.LogInfo("HoMM3 artifact map billboard: registered " + patched + " map-object Init postfix(es).");
			LogObjectBillboardCatalog(log);
		}
		catch (Exception ex)
		{
			if (required)
			{
				log?.LogFatal("HoMM3 artifact map billboard: required hook registration failed: " + ex);
				throw;
			}
			log?.LogWarning("HoMM3 artifact map billboard: hook registration failed: " + ex);
		}
	}

	private static void PostfixReleaseMapObjectInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;

			var meta = (__args != null && __args.Length > 1) ? __args[1] : null;
			meta ??= GetFirstMemberValue(__instance, GameSymbols.CustomTownMapBillboard.MetaFields);
			var rawSid = ResolveArtifactSid(__instance, meta, out var resolveSource);
			if (!IsHandledMapBillboardSid(rawSid))
			{
				LogNonCatalogArtifactProbe(__instance, meta, rawSid, resolveSource);
				return;
			}

			var root = TryGetMapObjectRoot(__instance);
			if (!root)
			{
				if (_loggedSkip < 12)
				{
					_loggedSkip++;
					Plugin.LogSource?.LogInfo(
						"HoMM3 artifact map billboard: sid='" + rawSid + "' via " + resolveSource
						+ " but map-object root missing (RootGameObjectFields/Transform).");
				}
				return;
			}

			var key = root.GetInstanceID() + "|" + rawSid;
			if (AppliedLiveRootKeys.Contains(key) && HasVisualForSid(root, rawSid))
			{
				EnsureDonorSuppressed(root, rawSid, Plugin.LogSource);
				return;
			}

			if (!ApplyBillboard(root, rawSid, Plugin.LogSource))
			{
				AppliedLiveRootKeys.Remove(key);
				if (IsObjectBillboardSid(rawSid))
				{
					Plugin.LogSource?.LogError(
						"HoMM3 object billboard: FAILED to draw sid='" + rawSid + "' via " + resolveSource
						+ " root='" + (root.name ?? "?") + "'; the object is invisible on the map.");
					return;
				}
				if (_loggedSkip < 24)
				{
					_loggedSkip++;
					Plugin.LogSource?.LogWarning(
						"HoMM3 artifact map billboard: failed to apply sid='" + rawSid
						+ "' via " + resolveSource + " root='" + (root.name ?? "?") + "'.");
				}
				return;
			}

			AppliedLiveRootKeys.Add(key);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("HoMM3 artifact/object map billboard postfix failed: " + ex);
		}
	}

	internal static bool IsArtifactSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && sid.Trim().StartsWith(SidPrefix, StringComparison.OrdinalIgnoreCase);
	}

	internal static bool IsSeerHutSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && string.Equals(sid.Trim(), SeerHutSid, StringComparison.OrdinalIgnoreCase);
	}

	internal static bool IsObjectBillboardSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && sid.Trim().StartsWith(ObjectBillboardSidPrefix, StringComparison.OrdinalIgnoreCase);
	}

	internal static bool IsHandledMapBillboardSid(string sid)
	{
		return IsArtifactSid(sid) || IsSeerHutSid(sid) || IsObjectBillboardSid(sid);
	}

	private static string FindPluginRelativePath(string relative, bool directory)
	{
		var native = relative.Replace('/', Path.DirectorySeparatorChar);
		foreach (var root in new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath })
		{
			foreach (var candidate in new[] { Path.Combine(root, "OfflineUnlockMod", native), Path.Combine(root, native) })
			{
				if (directory ? Directory.Exists(candidate) : File.Exists(candidate))
					return candidate;
			}
		}
		return null;
	}

	/// <summary>Registration-time readback of the staged object billboard PNGs; a missing folder is a LogError.</summary>
	private static void LogObjectBillboardCatalog(ManualLogSource log)
	{
		try
		{
			var folder = FindPluginRelativePath(ObjectBillboardFolder, directory: true);
			if (folder == null)
			{
				log?.LogError("HoMM3 object billboard: image folder " + ObjectBillboardFolder
				              + " is missing; every " + ObjectBillboardSidPrefix + "* map object will be invisible.");
				return;
			}
			var sids = new List<string>();
			foreach (var dir in Directory.GetDirectories(folder, ObjectBillboardSidPrefix + "*"))
			{
				if (File.Exists(Path.Combine(dir, "00_00.png")))
					sids.Add(Path.GetFileName(dir));
			}
			sids.Sort(StringComparer.Ordinal);
			log?.LogInfo("HoMM3 object billboard: " + sids.Count + " staged sid(s) in '" + folder + "': "
			             + string.Join(",", sids) + ".");
		}
		catch (Exception ex)
		{
			log?.LogError("HoMM3 object billboard: catalog readback failed: " + ex);
		}
	}

	/// <summary>
	/// Dwelling/town parity: placed SID fields, then nested ObjectConfig id, then root name.
	/// Shallow meta.id/sid alone miss release ObjectMeta wrappers (land-on-style silent miss).
	/// </summary>
	private static string ResolveArtifactSid(object placed, object meta, out string source)
	{
		source = "none";
		var placedSid = DeobfInteropCompat.TryGetPlacedMapObjectSid(placed, out var compatSid)
			? compatSid
			: GetFirstMemberValue(placed, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields) as string;
		if (IsObjectConfigCategoryTag(placedSid))
			placedSid = null;
		if (IsHandledMapBillboardSid(placedSid))
		{
			source = "placed";
			return placedSid.Trim();
		}

		var configSid = TryReadNestedConfigSid(meta);
		if (IsObjectConfigCategoryTag(configSid))
			configSid = null;
		if (IsHandledMapBillboardSid(configSid))
		{
			source = "meta-config";
			return configSid.Trim();
		}

		var root = TryGetMapObjectRoot(placed);
		var rootName = root ? root.name : null;
		if (IsHandledMapBillboardSid(rootName))
		{
			source = "root-name";
			return rootName.Trim();
		}

		if (!string.IsNullOrWhiteSpace(placedSid))
		{
			source = "placed-non-catalog";
			return placedSid.Trim();
		}
		if (!string.IsNullOrWhiteSpace(configSid))
		{
			source = "meta-config-non-catalog";
			return configSid.Trim();
		}
		if (!string.IsNullOrWhiteSpace(rootName))
		{
			source = "root-name-non-catalog";
			return rootName.Trim();
		}
		return null;
	}

	private static void LogNonCatalogArtifactProbe(object placed, object meta, string rawSid, string source)
	{
		if (_loggedResolveProbe >= 16)
			return;
		// Only the shared HoMM3 donor prefab shell — not ObjectConfig.tag "Artifact", scroll boxes,
		// or OE-native *_artifact roots (those are intentionally non-catalog).
		var root = TryGetMapObjectRoot(placed);
		var rootName = root ? (root.name ?? string.Empty) : string.Empty;
		var looksLikeDonorShell =
			rootName.IndexOf("ukhtabar", StringComparison.OrdinalIgnoreCase) >= 0
			|| (!string.IsNullOrWhiteSpace(rawSid)
			    && rawSid.IndexOf("ukhtabar", StringComparison.OrdinalIgnoreCase) >= 0);
		if (!looksLikeDonorShell)
			return;
		_loggedResolveProbe++;
		Plugin.LogSource?.LogWarning(
			"HoMM3 artifact map billboard: donor-shell host without catalog sid"
			+ " rawSid='" + (rawSid ?? "<null>") + "' source=" + source
			+ " root='" + (string.IsNullOrWhiteSpace(rootName) ? "?" : rootName) + "'"
			+ " meta=" + (meta == null ? "<null>" : meta.GetType().Name) + ".");
	}

	private static bool ApplyBillboard(GameObject root, string sid, ManualLogSource log)
	{
		if (HasVisualForSid(root, sid))
		{
			EnsureDonorSuppressed(root, sid, log);
			var existingMesh = root.transform.Find(Homm3ArtifactMeshBundle.MeshRootPrefix + SanitizeSid(sid));
			if (existingMesh)
				return true;
			var existingVisual = root.transform.Find(VisualRootName);
			if (existingVisual)
				Homm3BattleBillboardCameraFacing.TryAttachMapObject(existingVisual, log);
			return true;
		}

		if (TryApplyArtifactMesh(root, sid, log))
			return true;

		var donor = FindBestMapDonorRenderer(root);
		var material = GetOrCreateMaterial(sid, donor ? donor.sharedMaterial : null, log);
		if (!material || !material.mainTexture)
			return false;

		var donorRenderers = HideExistingRenderers(root);

		var visual = root.transform.Find(VisualRootName);
		if (visual == null)
		{
			var go = new GameObject(VisualRootName);
			visual = go.transform;
			visual.SetParent(root.transform, false);
		}
		var objectBillboard = IsObjectBillboardSid(sid);
		var tex = material.mainTexture;
		var quadHeight = objectBillboard ? tex.height * ObjectBillboardUnitsPerPixel : BillboardHeight;
		visual.localPosition = Vector3.up * (((objectBillboard ? quadHeight : HeightForSid(sid)) * 0.5f) + GroundClearance)
		                       + Vector3.forward * BillboardSouthOffset;
		visual.localRotation = Quaternion.identity;
		visual.localScale = Vector3.one;
		// Town parity: map-visible layer lives on the donor child, not always the Object root.
		var mapLayer = donor ? donor.gameObject.layer : root.layer;
		visual.gameObject.layer = mapLayer;
		visual.gameObject.SetActive(true);

		var quad = visual.Find("quad");
		var quadGo = quad == null ? new GameObject("quad") : quad.gameObject;
		if (quad == null)
			quadGo.transform.SetParent(visual, false);
		quadGo.layer = mapLayer;
		quadGo.SetActive(true);
		quadGo.transform.localPosition = new Vector3(0f, 0f, 0.04f);
		quadGo.transform.localRotation = Quaternion.identity;
		var width = tex.height > 0 ? quadHeight * tex.width / tex.height : quadHeight;
		quadGo.transform.localScale = new Vector3(width, quadHeight, 1f);

		var mf = quadGo.GetComponent<MeshFilter>() ?? quadGo.AddComponent<MeshFilter>();
		var mr = quadGo.GetComponent<MeshRenderer>() ?? quadGo.AddComponent<MeshRenderer>();
		mf.sharedMesh = GetOrCreateQuadMesh();
		mr.sharedMaterial = material;
		try { mr.SetPropertyBlock(null); } catch { }
		if (donor)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donor, visual.gameObject);
		mr.enabled = true;
		mr.forceRenderingOff = false;
		mr.shadowCastingMode = ShadowCastingMode.On;
		mr.receiveShadows = false;
		mr.allowOcclusionWhenDynamic = false;
		Homm3BattleBillboardCameraFacing.TryAttachMapObject(visual, log);
		// Pass empty citySid: town late-scan matches root name == sid and would forceRenderingOff
		// the artifact quad every LateUpdate (silent invisible billboard).
		Homm3TownBillboardDonorSuppressor.TryAttach(
			visual.gameObject,
			donorRenderers,
			null,
			root.transform,
			root.transform,
			log);

		if (objectBillboard)
		{
			if (LoggedObjectBillboardApplied.Add(sid))
				log?.LogInfo(
					"HoMM3 object billboard: applied sid='" + sid + "' root='" + (root.name ?? "?") + "' texture="
					+ tex.width + "x" + tex.height + " height=" + quadHeight.ToString("0.00") + " layer=" + mapLayer + ".");
		}
		else if (_loggedApplied < 20)
		{
			_loggedApplied++;
			log?.LogInfo(
				"HoMM3 artifact map billboard: applied sid='" + sid + "' root='" + (root.name ?? "?")
				+ "' layer=" + mapLayer + " donorLayer=" + (donor ? donor.gameObject.layer.ToString() : "none") + ".");
		}
		return true;
	}

	private static string RelativeMapPngForSid(string sid) =>
		MapFolder + "/" + sid.Trim() + "/00_00.png";

	/// <summary>
	/// Catalog hit + flag on → Meshy mesh (fail-closed). Uncatalogued / flag off → false so PNG path runs.
	/// Seer hut stays PNG (not in the artifact mesh inventory).
	/// </summary>
	private static bool TryApplyArtifactMesh(GameObject root, string sid, ManualLogSource log)
	{
		if (!root || string.IsNullOrWhiteSpace(sid) || IsSeerHutSid(sid) || IsObjectBillboardSid(sid))
			return false;
		if (!Homm3ArtifactMeshBundle.IsEnabled())
			return false;
		var relativePath = RelativeMapPngForSid(sid);
		if (!Homm3ArtifactMeshBundle.HasMeshForRelativePath(relativePath))
			return false;
		if (!Homm3ArtifactMeshBundle.TryLoadPrefab(relativePath, out var prefab, out var entry, log) || !prefab)
		{
			log?.LogError(
				"HoMM3 artifact map mesh: prefab load failed for sid='"
				+ sid
				+ "' path='"
				+ relativePath
				+ "'; refuse apply (homm3ArtifactMeshes on — no PNG fallback for catalog hit).");
			return false;
		}

		var donor = FindBestMapDonorRenderer(root);
		var donorMaterial = donor ? donor.sharedMaterial : null;
		var donorRenderers = HideExistingRenderers(root);

		var staleBillboard = root.transform.Find(VisualRootName);
		if (staleBillboard)
			UnityEngine.Object.Destroy(staleBillboard.gameObject);

		var meshRootName = Homm3ArtifactMeshBundle.MeshRootPrefix + SanitizeSid(sid);
		var existing = root.transform.Find(meshRootName);
		if (existing)
			UnityEngine.Object.Destroy(existing.gameObject);

		var instance = UnityEngine.Object.Instantiate(prefab, root.transform, false);
		instance.name = meshRootName;
		var mapLayer = donor ? donor.gameObject.layer : root.layer;
		SetLayerRecursive(instance, mapLayer);

		var runtimeScale = Homm3ArtifactMeshBundle.GetRuntimeScale();
		instance.transform.localPosition = Vector3.forward * BillboardSouthOffset;
		var authoredScale = instance.transform.localScale;
		if (authoredScale.sqrMagnitude < 1e-8f)
			authoredScale = Vector3.one;
		instance.transform.localScale = authoredScale * runtimeScale;
		instance.SetActive(true);

		Homm3ArtifactMeshBundle.OrientToBillboardArtAndSeat(
			instance,
			mapFacingYawDegrees: 0f,
			artYawDegrees: entry != null ? entry.ArtYawDegrees : 0f,
			cacheKey: entry != null ? entry.PrefabKey : null,
			log);

		if (!Homm3ArtifactMeshBundle.TryRebindRenderersToMapDonor(instance, donorMaterial, log))
		{
			UnityEngine.Object.Destroy(instance);
			return false;
		}

		if (donor)
			EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donor, instance);

		if (!Homm3TownBillboardDonorSuppressor.TryAttach(
			    instance,
			    donorRenderers,
			    null,
			    root.transform,
			    root.transform,
			    log))
		{
			UnityEngine.Object.Destroy(instance);
			return false;
		}

		var meshRenderers = instance.GetComponentsInChildren<MeshRenderer>(true);
		if (meshRenderers == null || meshRenderers.Length == 0)
		{
			log?.LogError("HoMM3 artifact map mesh: no MeshRenderer after instantiate.");
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

		if (_loggedApplied < 20)
		{
			_loggedApplied++;
			log?.LogInfo(
				"HoMM3 artifact map mesh: applied sid='"
				+ sid
				+ "' prefab='"
				+ (entry?.PrefabKey ?? "?")
				+ "' root='"
				+ (root.name ?? "?")
				+ "'.");
		}
		return true;
	}

	private static string SanitizeSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return "unknown";
		var chars = sid.Trim().ToCharArray();
		for (var i = 0; i < chars.Length; i++)
		{
			var c = chars[i];
			if (!(char.IsLetterOrDigit(c) || c == '_'))
				chars[i] = '_';
		}
		return new string(chars);
	}

	private static void SetLayerRecursive(GameObject go, int layer)
	{
		if (!go)
			return;
		go.layer = layer;
		var t = go.transform;
		for (var i = 0; i < t.childCount; i++)
		{
			var child = t.GetChild(i);
			if (child)
				SetLayerRecursive(child.gameObject, layer);
		}
	}

	private static void EnsureDonorSuppressed(GameObject root, string sid, ManualLogSource log)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return;
		var donorRenderers = HideExistingRenderers(root);
		var meshRoot = root.transform.Find(Homm3ArtifactMeshBundle.MeshRootPrefix + SanitizeSid(sid));
		if (meshRoot)
		{
			Homm3TownBillboardDonorSuppressor.TryAttach(
				meshRoot.gameObject,
				donorRenderers,
				null,
				root.transform,
				root.transform,
				log);
			return;
		}
		var visual = root.transform.Find(VisualRootName);
		if (!visual)
			return;
		Homm3TownBillboardDonorSuppressor.TryAttach(
			visual.gameObject,
			donorRenderers,
			null,
			root.transform,
			root.transform,
			log);
	}

	private static bool HasVisualForSid(GameObject root, string sid)
	{
		if (!root || string.IsNullOrWhiteSpace(sid))
			return false;
		var meshRoot = root.transform.Find(Homm3ArtifactMeshBundle.MeshRootPrefix + SanitizeSid(sid));
		if (meshRoot && meshRoot.gameObject.activeSelf)
		{
			var meshRenderers = meshRoot.GetComponentsInChildren<MeshRenderer>(true);
			if (meshRenderers != null)
			{
				for (var i = 0; i < meshRenderers.Length; i++)
				{
					var mr = meshRenderers[i];
					if (mr && mr.enabled && !mr.forceRenderingOff && mr.sharedMaterial)
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
		var texture = GetOrCreateTexture(sid, log);
		if (!texture)
			return null;
		Material material = null;
		if (IsHexLitMaterial(donor))
			material = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(donor, texture, "HOMM3_artifact_" + sid + "_hexlit");
		if (!material)
		{
			var shader = Shader.Find("Hex/Lit");
			if (!shader)
				return null;
			material = new Material(shader) { name = "HOMM3_artifact_" + sid + "_hexlit_generated" };
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

	private static float HeightForSid(string sid)
	{
		return IsSeerHutSid(sid) ? SeerHutBillboardHeight : BillboardHeight;
	}

	private static Texture2D GetOrCreateTexture(string sid, ManualLogSource log)
	{
		if (TexturesBySid.TryGetValue(sid, out var cached) && cached)
			return cached;

		if (IsObjectBillboardSid(sid))
			return LoadObjectBillboardTexture(sid.Trim(), log);

		if (IsSeerHutSid(sid))
		{
			if (Homm3MapBillboardBundle.IsEnabled()
			    && Homm3MapBillboardBundle.TryLoadTexture(SeerHutImageRelativePath, out var seerBundle)
			    && seerBundle)
			{
				seerBundle.filterMode = FilterMode.Point;
				seerBundle.wrapMode = TextureWrapMode.Clamp;
				TexturesBySid[sid] = seerBundle;
				return seerBundle;
			}
			var seerPath = null as string;
			foreach (var root in new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath })
			{
				var candidate = Path.Combine(root, "OfflineUnlockMod", SeerHutImageRelativePath.Replace('/', Path.DirectorySeparatorChar));
				if (File.Exists(candidate))
				{
					seerPath = candidate;
					break;
				}
				candidate = Path.Combine(root, SeerHutImageRelativePath.Replace('/', Path.DirectorySeparatorChar));
				if (File.Exists(candidate))
				{
					seerPath = candidate;
					break;
				}
			}
			if (seerPath == null)
			{
				if (LoggedMissingImage.Add(sid))
					log?.LogWarning("HoMM3 seer hut map billboard: missing image for " + SeerHutImageRelativePath);
				return null;
			}
			var seerTex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			var seerBytes = File.ReadAllBytes(seerPath);
			var seerIl2cpp = new Il2CppStructArray<byte>(seerBytes.LongLength);
			for (var i = 0; i < seerBytes.Length; i++)
				seerIl2cpp[i] = seerBytes[i];
			if (!ImageConversion.LoadImage(seerTex, seerIl2cpp))
			{
				UnityEngine.Object.Destroy(seerTex);
				return null;
			}
			seerTex.name = "HOMM3_seer_hut_map_billboard";
			seerTex.filterMode = FilterMode.Point;
			seerTex.wrapMode = TextureWrapMode.Clamp;
			TexturesBySid[sid] = seerTex;
			return seerTex;
		}

		// Phase 2 pilot: homm3_artifact_map_billboards before PNG decode; PNG stays the per-sid
		// fallback. Bundle textures are shared/compressed — do not Destroy them.
		if (Homm3ArtifactMapBillboardBundle.IsEnabled())
		{
			if (Homm3ArtifactMapBillboardBundle.TryLoadTexture(sid, out var bundleTexture) && bundleTexture)
			{
				LogBillboardBundleResolution(sid, hit: true, log);
				bundleTexture.filterMode = FilterMode.Point;
				bundleTexture.wrapMode = TextureWrapMode.Clamp;
				TexturesBySid[sid] = bundleTexture;
				return bundleTexture;
			}
			LogBillboardBundleResolution(sid, hit: false, log);
		}

		var path = ResolveImagePath(sid);
		if (path == null)
		{
			if (LoggedMissingImage.Add(sid))
				log?.LogWarning("HoMM3 artifact map billboard: missing image for " + sid + ".");
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
		tex.name = "HOMM3_artifact_" + sid;
		tex.filterMode = FilterMode.Point;
		tex.wrapMode = TextureWrapMode.Clamp;
		TexturesBySid[sid] = tex;
		return tex;
	}

	/// <summary>PNG only (no bundle lane). Missing or undecodable image is a LogError, never a silent blank.</summary>
	private static Texture2D LoadObjectBillboardTexture(string sid, ManualLogSource log)
	{
		var rel = ObjectBillboardFolder + "/" + sid + "/00_00.png";
		var path = FindPluginRelativePath(rel, directory: false);
		if (path == null)
		{
			if (LoggedMissingImage.Add(sid))
				log?.LogError("HoMM3 object billboard: missing image " + rel + " for sid='" + sid + "'.");
			return null;
		}
		var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		var bytes = File.ReadAllBytes(path);
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		if (!ImageConversion.LoadImage(tex, il2cppBytes) || tex.height <= 0)
		{
			UnityEngine.Object.Destroy(tex);
			if (LoggedMissingImage.Add(sid))
				log?.LogError("HoMM3 object billboard: could not decode " + path + " for sid='" + sid + "'.");
			return null;
		}
		tex.name = "HOMM3_object_billboard_" + sid;
		tex.filterMode = FilterMode.Point;
		tex.wrapMode = TextureWrapMode.Clamp;
		TexturesBySid[sid] = tex;
		return tex;
	}

	private static void LogBillboardBundleResolution(string sid, bool hit, ManualLogSource log)
	{
		if (!LoggedBillboardBundleResolution.Add(sid ?? "?"))
			return;
		log?.LogInfo(
			"HoMM3 artifact map billboard: "
			+ (hit ? "bundle-hit" : "bundle-miss")
			+ " sid='"
			+ (sid ?? "?")
			+ "'.");
	}

	private static string ResolveImagePath(string sid)
	{
		var rel = Path.Combine(MapFolder, sid, "00_00.png");
		var roots = new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath };
		foreach (var root in roots)
		{
			var path = Path.Combine(root, "OfflineUnlockMod", rel);
			if (File.Exists(path))
				return path;
			path = Path.Combine(root, rel);
			if (File.Exists(path))
				return path;
		}
		return null;
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

	private static List<Renderer> HideExistingRenderers(GameObject root)
	{
		var hidden = new List<Renderer>();
		if (!root)
			return hidden;
		foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer)
				continue;
			if (renderer.transform != null
			    && (renderer.transform.name == VisualRootName
			        || (renderer.transform.parent && renderer.transform.parent.name == VisualRootName)
			        || renderer.transform.name == "quad"))
				continue;
			renderer.enabled = false;
			renderer.forceRenderingOff = true;
			hidden.Add(renderer);
		}
		return hidden;
	}

	private static Renderer FindBestMapDonorRenderer(GameObject root)
	{
		if (!root)
			return null;
		Renderer best = null;
		var bestArea = -1f;
		foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer)
				continue;
			// ParticleSystemRenderer is not always in the referenced UnityEngine surface.
			var rendererTypeName = renderer.GetType().Name;
			if (rendererTypeName.IndexOf("Particle", StringComparison.OrdinalIgnoreCase) >= 0)
				continue;
			if (renderer.transform && (renderer.transform.name == VisualRootName || renderer.transform.name == "quad"))
				continue;
			var bounds = renderer.bounds;
			var area = bounds.size.x * bounds.size.y;
			if (area > bestArea)
			{
				bestArea = area;
				best = renderer;
			}
		}
		return best;
	}

	private static Mesh GetOrCreateQuadMesh()
	{
		if (_quadMesh)
			return _quadMesh;
		_quadMesh = new Mesh
		{
			name = "HOMM3_artifact_billboard_quad",
			vertices = new[]
			{
				new Vector3(-0.5f, -0.5f, 0f),
				new Vector3(0.5f, -0.5f, 0f),
				new Vector3(-0.5f, 0.5f, 0f),
				new Vector3(0.5f, 0.5f, 0f),
			},
			uv = new[]
			{
				new Vector2(0f, 0f),
				new Vector2(1f, 0f),
				new Vector2(0f, 1f),
				new Vector2(1f, 1f),
			},
			triangles = new[] { 0, 2, 1, 2, 3, 1 },
		};
		_quadMesh.RecalculateBounds();
		_quadMesh.RecalculateNormals();
		return _quadMesh;
	}

	private static GameObject TryGetMapObjectRoot(object instance)
	{
		if (instance == null)
			return null;

		var root = GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.RootGameObjectFields) as GameObject
		           ?? InvokeFirstNoArg(instance, typeof(GameObject), GameSymbols.CustomTownMapBillboard.RootGameObjectGetter) as GameObject;
		if (root)
			return root;

		var transform = GetFirstMemberValue(instance, GameSymbols.CustomTownMapBillboard.RootTransformFields) as Transform
		                ?? InvokeFirstNoArg(instance, typeof(Transform), GameSymbols.CustomTownMapBillboard.RootTransformGetter) as Transform;
		if (transform)
			return transform.gameObject;

		// Last resort: Il2Cpp Component proxy (often fails; kept after field/getter path).
		if (instance is Component component && component)
			return component.gameObject;
		if (instance is GameObject go && go)
			return go;
		try
		{
			var prop = instance.GetType().GetProperty("gameObject", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (prop != null && prop.GetValue(instance) is GameObject g && g)
				return g;
		}
		catch
		{
			// ignore
		}
		return null;
	}

	private static string TryReadNestedConfigSid(object meta)
	{
		if (meta == null)
			return null;
		try
		{
			if (meta is Hex.Map.MapObjectInfo info && DeobfInteropCompat.TryGetMapObjectInfoSid(info, out var infoSid)
			    && !string.IsNullOrWhiteSpace(infoSid))
				return infoSid.Trim();

			var config = DeobfInteropCompat.TryGetMapObjectMetaConfig(meta, out var compatConfig) ? compatConfig : null;
			if (config == null)
				config = GetFirstMemberValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
			// GetConfigElementId owns tag-vs-id disambiguation; do not fall back to ConfigIdFields
			// field_Public_String_0 (ObjectConfig.tag collision → rawSid "Artifact").
			var id = DeobfInteropCompat.GetConfigElementId(config);
			if (!string.IsNullOrWhiteSpace(id))
				return id.Trim();

			// Shallow meta fields last — release ObjectMeta rarely stores the catalog id here.
			foreach (var name in new[] { "id", "sid", "Id", "Sid" })
			{
				var prop = meta.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (prop != null && prop.GetValue(meta) is string s && !string.IsNullOrWhiteSpace(s)
				    && !IsObjectConfigCategoryTag(s))
					return s.Trim();
				var field = meta.GetType().GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null && field.GetValue(meta) is string fs && !string.IsNullOrWhiteSpace(fs)
				    && !IsObjectConfigCategoryTag(fs))
					return fs.Trim();
			}
		}
		catch
		{
			// ignore
		}
		return null;
	}

	private static bool IsObjectConfigCategoryTag(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return false;
		var trimmed = value.Trim();
		return string.Equals(trimmed, "Artifact", StringComparison.Ordinal)
		       || string.Equals(trimmed, "Interact", StringComparison.Ordinal)
		       || string.Equals(trimmed, "Environment", StringComparison.Ordinal)
		       || string.Equals(trimmed, "Animals", StringComparison.Ordinal)
		       || string.Equals(trimmed, "FX", StringComparison.Ordinal)
		       || string.Equals(trimmed, "TEST", StringComparison.Ordinal)
		       || string.Equals(trimmed, "Resource", StringComparison.Ordinal)
		       || string.Equals(trimmed, "meta", StringComparison.Ordinal)
		       || string.Equals(trimmed, "Block", StringComparison.Ordinal);
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

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var p = t.GetProperty(name, flags);
			if (p != null)
			{
				try { return p.GetValue(obj); }
				catch { return null; }
			}
			var f = t.GetField(name, flags);
			if (f != null)
			{
				try { return f.GetValue(obj); }
				catch { return null; }
			}
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

	private static Type GetFirstHexType(string id, string[] names)
	{
		if (names == null || names.Length == 0)
			return null;
		return GameMember.FindTypeFromHints(id, names, hint => GetHexType(hint));
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
		return null;
	}
}
