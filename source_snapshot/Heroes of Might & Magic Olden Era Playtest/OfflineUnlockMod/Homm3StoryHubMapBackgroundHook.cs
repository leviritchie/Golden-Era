using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.StoryHub;
using Hex.StoryHub.Data;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Per-campaign StoryHub canvas map swap: assign baked *_BG_1920x1080 sprites
/// (HoMM3 map art centered in the middle 2/3 of a 1080p canvas) to MapCanvas/MapImage
/// and MapImage (1). Does not touch BhScrollImage smoke overlays, map_paper, or
/// Mission_*_QuestFrame art.
///
/// Proof boundary: source/static + generated-artifact for baked PNGs and hook wiring.
/// Runtime MapImage assignment remains separately confirmed in live StoryHub.
/// </summary>
internal static class Homm3StoryHubMapBackgroundHook
{
	internal const string AssetFolder = "homm3_storyhub_maps";
	internal const string MapCanvasName = "MapCanvas";
	internal const int TargetWidth = 1920;
	internal const int TargetHeight = 1080;

	private static readonly Dictionary<string, string> LegacyHubSidToPlayOrder =
		new(StringComparer.Ordinal)
		{
			["homm3_roe_castle_good1"] = "homm3_01_roe_castle_good1",
			["homm3_roe_castle_good2"] = "homm3_02_roe_castle_good2",
			["homm3_roe_castle_good3"] = "homm3_03_roe_castle_good3",
			["homm3_roe_dungeon_evil1"] = "homm3_04_roe_dungeon_evil1",
			["homm3_roe_necropolis_evil2"] = "homm3_05_roe_necropolis_evil2",
			["homm3_roe_neutral_neutral1"] = "homm3_06_roe_neutral_neutral1",
			["homm3_roe_rampart_secret1"] = "homm3_07_roe_rampart_secret1",
			["homm3_roe_necropolis_secret"] = "homm3_08_roe_necropolis_secret",
			["homm3_ab_conflux_ab"] = "homm3_09_ab_conflux_ab",
			["homm3_ab_dungeon_blood"] = "homm3_10_ab_dungeon_blood",
			["homm3_ab_tower_slayer"] = "homm3_11_ab_tower_slayer",
			["homm3_ab_stronghold_festival"] = "homm3_12_ab_stronghold_festival",
			["homm3_ab_fortress_fire"] = "homm3_13_ab_fortress_fire",
			["homm3_ab_castle_fool"] = "homm3_14_ab_castle_fool",
			["homm3_sod_necropolis_sandro"] = "homm3_15_sod_necropolis_sandro",
			["homm3_sod_stronghold_crag"] = "homm3_16_sod_stronghold_crag",
			["homm3_sod_stronghold_yog"] = "homm3_17_sod_stronghold_yog",
			["homm3_sod_rampart_gem"] = "homm3_18_sod_rampart_gem",
			["homm3_sod_rampart_gelu"] = "homm3_19_sod_rampart_gelu",
			["homm3_sod_necropolis_final"] = "homm3_20_sod_necropolis_final",
		};

	private static readonly Dictionary<string, string> BackgroundPrefixByHubSid =
		BuildBackgroundPrefixByHubSid();

	private static readonly HashSet<string> MapImageNames = new(StringComparer.Ordinal)
	{
		"MapImage",
		"MapImage (1)",
	};

	private static readonly Dictionary<string, Sprite> SpritesByPrefix = new(StringComparer.Ordinal);
	private static readonly object SyncRoot = new();

	private static ManualLogSource _log;
	private static bool _patched;
	private static int _loggedApply;
	private static int _loggedSkip;
	private static int _loggedFail;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		_log = log;
		if (_patched)
			return;
		if (harmony == null)
		{
			log?.LogWarning("Homm3StoryHubMapBackground: Harmony was null; hook not registered.");
			return;
		}

		var type = ResolveBhStoryHubType();
		if (type == null)
		{
			log?.LogWarning(
				"Homm3StoryHubMapBackground: BhStoryHub type not found ("
				+ string.Join(", ", GameSymbols.StoryHubMapBackground.BhStoryHubTypeHints)
				+ "); MapImage swap disabled.");
			return;
		}

		var init = FindInitMethod(type);
		if (init == null)
		{
			log?.LogWarning(
				"Homm3StoryHubMapBackground: BhStoryHub.Init not found via "
				+ string.Join("/", GameSymbols.StoryHubMapBackground.BhStoryHubInit.NameHints)
				+ "; MapImage swap disabled.");
			return;
		}

		harmony.Patch(init, postfix: new HarmonyMethod(typeof(Homm3StoryHubMapBackgroundHook), nameof(PostfixBhStoryHubInit)));
		_patched = true;
		Homm3PreviewApplyNextFrame.Ensure(log);
		log?.LogInfo(
			"Homm3StoryHubMapBackground: patched "
			+ type.FullName
			+ "."
			+ init.Name
			+ " for per-campaign MapImage sprite swap.");
	}

	private static Dictionary<string, string> BuildBackgroundPrefixByHubSid()
	{
		// Distinct Complete-edition *_BG stems (CampText geography + SoD titles).
		// Must stay in sync with experiments/campaign_port_poc/storyhub_map_background.py
		// DEFAULT_HUBS and baked OfflineUnlockMod/homm3_storyhub_maps/*_1920x1080.png.
		var playOrder = new Dictionary<string, string>(StringComparer.Ordinal)
		{
			[Homm3CampaignContinuityContract.HubSid] = "G1_BG",
			["homm3_02_roe_castle_good2"] = "G2_BG",
			["homm3_03_roe_castle_good3"] = "G3_BG",
			["homm3_04_roe_dungeon_evil1"] = "E1_BG",
			["homm3_05_roe_necropolis_evil2"] = "E2_BG",
			["homm3_06_roe_neutral_neutral1"] = "N1_BG",
			["homm3_07_roe_rampart_secret1"] = "S1_BG",
			["homm3_08_roe_necropolis_secret"] = "SP_BG",
			["homm3_09_ab_conflux_ab"] = "AR_BG",
			["homm3_10_ab_dungeon_blood"] = "NI_BG",
			["homm3_11_ab_tower_slayer"] = "BR_BG",
			["homm3_12_ab_stronghold_festival"] = "KR_BG",
			["homm3_13_ab_fortress_fire"] = "TA_BG",
			["homm3_14_ab_castle_fool"] = "IS_BG",
			["homm3_15_sod_necropolis_sandro"] = "RN_BG",
			["homm3_16_sod_stronghold_crag"] = "HS_BG",
			["homm3_17_sod_stronghold_yog"] = "BB_BG",
			["homm3_18_sod_rampart_gem"] = "NB_BG",
			["homm3_19_sod_rampart_gelu"] = "EL_BG",
			["homm3_20_sod_necropolis_final"] = "UA_BG",
		};

		foreach (var pair in LegacyHubSidToPlayOrder)
		{
			if (!playOrder.TryGetValue(pair.Value, out var prefix))
				continue;
			playOrder.TryAdd(pair.Key, prefix);
		}

		return playOrder;
	}

	private static void PostfixBhStoryHubInit(object __instance, object __0)
	{
		Homm3PreviewApplyNextFrame.QueueOrRun(_log, () =>
		{
			try
			{
				TryApplyForStoryHubInstance(__instance, __0);
			}
			catch (Exception ex)
			{
				if (_loggedFail++ < 12)
					_log?.LogWarning("Homm3StoryHubMapBackground: apply failed: " + ex.Message);
			}
		});
	}

	internal static bool TryApplyForStoryHubInstance(object storyHubInstance, object storyHubSave = null)
	{
		if (storyHubInstance == null)
			return false;

		if (!TryResolveHubSid(storyHubInstance, storyHubSave, out var hubSid) || string.IsNullOrWhiteSpace(hubSid))
		{
			LogSkip("hub-sid-unresolved");
			return false;
		}

		hubSid = NormalizeHubSid(hubSid);
		if (!BackgroundPrefixByHubSid.TryGetValue(hubSid, out var prefix))
		{
			LogSkip("non-homm3-hub:" + hubSid);
			return false;
		}

		if (!TryGetOrCreateSprite(prefix, out var sprite, out var reason) || !sprite)
		{
			LogFail("sprite:" + prefix + ":" + reason);
			return false;
		}

		var images = FindMapImages();
		if (images.Count < 2)
		{
			LogFail("map-images-found=" + images.Count + " (need MapImage and MapImage (1) under MapCanvas)");
			return false;
		}

		var assigned = 0;
		for (var i = 0; i < images.Count; i++)
		{
			var image = images[i];
			if (!image)
				continue;
			image.preserveAspect = false;
			image.sprite = sprite;
			assigned++;
		}

		if (assigned < 2)
		{
			LogFail("assigned=" + assigned + " after finding " + images.Count);
			return false;
		}

		if (_loggedApply++ < 20)
		{
			_log?.LogInfo(
				"Homm3StoryHubMapBackground: hubSid='"
				+ hubSid
				+ "' prefix='"
				+ prefix
				+ "' assigned sprite '"
				+ sprite.name
				+ "' to "
				+ assigned
				+ " MapImage object(s).");
		}

		return true;
	}

	private static string NormalizeHubSid(string hubSid)
	{
		if (string.IsNullOrWhiteSpace(hubSid))
			return null;
		hubSid = hubSid.Trim();
		return LegacyHubSidToPlayOrder.TryGetValue(hubSid, out var playOrder) ? playOrder : hubSid;
	}

	private static Type ResolveBhStoryHubType()
	{
		foreach (var hint in GameSymbols.StoryHubMapBackground.BhStoryHubTypeHints)
		{
			var type = ModActions.GetHexType(hint) ?? AccessTools.TypeByName(hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static MethodInfo FindInitMethod(Type type)
	{
		foreach (var name in GameSymbols.StoryHubMapBackground.BhStoryHubInit.NameHints)
		{
			foreach (var method in AccessTools.GetDeclaredMethods(type))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsStatic || method.ContainsGenericParameters)
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 1)
					continue;
				return method;
			}
		}
		return AccessTools.Method(type, "Init");
	}

	private static bool TryResolveHubSid(object storyHubInstance, object storyHubSave, out string hubSid)
	{
		hubSid = null;

		if (TryResolveHubSidFromTypedSave(CastStoryHubSave(storyHubSave), out hubSid))
			return true;

		if (storyHubInstance is Il2CppObjectBase hubBase)
		{
			var hub = hubBase.TryCast<BhStoryHub>();
			if (hub != null && TryResolveHubSidFromHubInstance(hub, out hubSid))
				return true;
		}

		if (TryResolveHubSidFromSave(storyHubSave, out hubSid))
			return true;

		var type = storyHubInstance.GetType();
		foreach (var accessorName in GameSymbols.StoryHubMapBackground.BhStoryHubConfigAccessor.NameHints)
		{
			MethodInfo method = null;
			try
			{
				method = AccessTools.Method(type, accessorName, Type.EmptyTypes);
			}
			catch
			{
				// AccessTools warns when the deobfuscated name is absent; keep scanning.
			}
			if (method == null || method.GetParameters().Length != 0)
				continue;
			object config;
			try
			{
				config = method.Invoke(storyHubInstance, null);
			}
			catch
			{
				continue;
			}
			if (TryReadConfigSid(config, out hubSid))
				return true;
		}

		return TryScanObjectTreeForHubSid(storyHubInstance, depth: 0, out hubSid);
	}

	private static bool TryResolveHubSidFromHubInstance(BhStoryHub hub, out string hubSid)
	{
		hubSid = null;
		if (hub == null)
			return false;

		foreach (var method in AccessTools.GetDeclaredMethods(hub.GetType()))
		{
			if (method.IsStatic || method.GetParameters().Length != 0)
				continue;
			if (method.ReturnType != typeof(StoryHubSave))
				continue;
			StoryHubSave save;
			try
			{
				save = method.Invoke(hub, null) as StoryHubSave;
			}
			catch
			{
				continue;
			}
			if (TryResolveHubSidFromTypedSave(save, out hubSid))
				return true;
		}

		foreach (var method in AccessTools.GetDeclaredMethods(hub.GetType()))
		{
			if (method.IsStatic || method.GetParameters().Length != 0)
				continue;
			if (method.ReturnType != typeof(StoryHub))
				continue;
			StoryHub data;
			try
			{
				data = method.Invoke(hub, null) as StoryHub;
			}
			catch
			{
				continue;
			}
			hubSid = data?.activeProfile?.campaignSid;
			if (!string.IsNullOrWhiteSpace(hubSid))
				return true;
		}

		return false;
	}

	private static StoryHubSave CastStoryHubSave(object storyHubSave)
	{
		return storyHubSave is Il2CppObjectBase saveBase
			? saveBase.TryCast<StoryHubSave>()
			: null;
	}

	private static bool TryResolveHubSidFromTypedSave(StoryHubSave save, out string hubSid)
	{
		hubSid = save?.storyHubData?.activeProfile?.campaignSid;
		return !string.IsNullOrWhiteSpace(hubSid);
	}

	private static bool TryResolveHubSidFromSave(object storyHubSave, out string hubSid)
	{
		hubSid = null;
		if (storyHubSave == null)
			return false;

		var data = TryReadObjectMember(
			storyHubSave,
			GameSymbols.StoryHubMapBackground.StoryHubSaveDataFieldHints);
		if (data == null)
			return false;

		var profile = TryReadObjectMember(
			data,
			GameSymbols.StoryHubMapBackground.StoryHubActiveProfileFieldHints);
		if (profile != null)
		{
			hubSid = DeobfInteropCompat.TryReadNativeStringMember(
				profile,
				GameSymbols.StoryHubMapBackground.ProfileCampaignSidFieldHints);
			if (!string.IsNullOrWhiteSpace(hubSid))
				return true;
		}

		return TryReadConfigSid(data, out hubSid) || TryReadConfigSid(storyHubSave, out hubSid);
	}

	private static bool TryReadConfigSid(object config, out string hubSid)
	{
		hubSid = null;
		if (config == null)
			return false;
		hubSid = DeobfInteropCompat.TryReadNativeStringMember(
			config,
			GameSymbols.StoryHubMapBackground.StoryHubConfigSidFieldHints);
		if (!string.IsNullOrWhiteSpace(hubSid))
			return true;
		hubSid = DeobfInteropCompat.TryReadNativeStringMember(
			config,
			GameSymbols.StoryHubMapBackground.ProfileCampaignSidFieldHints);
		return !string.IsNullOrWhiteSpace(hubSid);
	}

	private static object TryReadObjectMember(object owner, string[] names)
	{
		if (owner == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var native = DeobfInteropCompat.TryReadNativeObjectMember(owner, typeof(Il2CppObjectBase), name);
			if (native != null)
				return native;

			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var type = owner.GetType();
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
				{
					var value = field.GetValue(owner);
					if (value != null)
						return value;
				}
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					var value = prop.GetValue(owner, null);
					if (value != null)
						return value;
				}
			}
			catch
			{
				// continue
			}
		}
		return null;
	}

	private static bool TryScanObjectTreeForHubSid(object root, int depth, out string hubSid)
	{
		hubSid = null;
		if (root == null || depth > 2)
			return false;

		if (TryReadConfigSid(root, out hubSid))
			return true;

		var type = root.GetType();
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		FieldInfo[] fields;
		try
		{
			fields = type.GetFields(flags);
		}
		catch
		{
			return false;
		}

		for (var i = 0; i < fields.Length; i++)
		{
			object child;
			try
			{
				child = fields[i].GetValue(root);
			}
			catch
			{
				continue;
			}
			if (child == null || child is string || child.GetType().IsValueType)
				continue;
			if (TryScanObjectTreeForHubSid(child, depth + 1, out hubSid))
				return true;
		}

		return false;
	}

	private static List<Image> FindMapImages()
	{
		var result = new List<Image>(2);
		var seen = new HashSet<int>();

		foreach (var canvas in Resources.FindObjectsOfTypeAll<Canvas>())
		{
			if (!canvas || !canvas.gameObject)
				continue;
			if (!string.Equals(canvas.gameObject.name, MapCanvasName, StringComparison.Ordinal))
				continue;
			CollectMapImagesUnder(canvas.transform, result, seen);
		}

		if (result.Count >= 2)
			return result;

		foreach (var image in Resources.FindObjectsOfTypeAll<Image>())
		{
			if (!image || !image.gameObject)
				continue;
			if (!MapImageNames.Contains(image.gameObject.name))
				continue;
			if (!IsUnderNamedAncestor(image.transform, MapCanvasName))
				continue;
			var id = image.GetInstanceID();
			if (!seen.Add(id))
				continue;
			result.Add(image);
		}

		return result;
	}

	private static void CollectMapImagesUnder(Transform root, List<Image> result, HashSet<int> seen)
	{
		if (!root)
			return;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image || !image.gameObject)
				continue;
			if (!MapImageNames.Contains(image.gameObject.name))
				continue;
			var id = image.GetInstanceID();
			if (!seen.Add(id))
				continue;
			result.Add(image);
		}
	}

	private static bool IsUnderNamedAncestor(Transform node, string ancestorName)
	{
		var current = node;
		while (current != null)
		{
			if (string.Equals(current.name, ancestorName, StringComparison.Ordinal))
				return true;
			current = current.parent;
		}
		return false;
	}

	private static bool TryGetOrCreateSprite(string prefix, out Sprite sprite, out string reason)
	{
		sprite = null;
		reason = null;
		if (string.IsNullOrWhiteSpace(prefix))
		{
			reason = "empty-prefix";
			return false;
		}

		lock (SyncRoot)
		{
			if (SpritesByPrefix.TryGetValue(prefix, out sprite) && sprite)
				return true;

			var relative = Path.Combine(AssetFolder, prefix + "_" + TargetWidth + "x" + TargetHeight + ".png");
			var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(relative);
			if (path == null)
			{
				reason = "missing-png:" + relative.Replace('\\', '/');
				return false;
			}

			try
			{
				var bytes = File.ReadAllBytes(path);
				var texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: false)
				{
					name = "homm3_storyhub_map_" + prefix,
					filterMode = FilterMode.Point,
					wrapMode = TextureWrapMode.Clamp,
				};
				var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
				for (var i = 0; i < bytes.Length; i++)
					il2cppBytes[i] = bytes[i];
				if (!ImageConversion.LoadImage(texture, il2cppBytes))
				{
					UnityEngine.Object.Destroy(texture);
					reason = "loadimage-failed";
					return false;
				}

				if (texture.width != TargetWidth || texture.height != TargetHeight)
				{
					reason = "size-" + texture.width + "x" + texture.height;
					UnityEngine.Object.Destroy(texture);
					return false;
				}

				sprite = Sprite.Create(
					texture,
					new Rect(0f, 0f, texture.width, texture.height),
					new Vector2(0.5f, 0.5f),
					100f,
					0,
					SpriteMeshType.FullRect);
				sprite.name = "homm3_storyhub_map_" + prefix;
				SpritesByPrefix[prefix] = sprite;
				return true;
			}
			catch (Exception ex)
			{
				reason = "exception:" + ex.GetType().Name;
				return false;
			}
		}
	}

	private static void LogSkip(string reason)
	{
		if (_loggedSkip++ < 20)
			_log?.LogInfo("Homm3StoryHubMapBackground: skip " + reason);
	}

	private static void LogFail(string reason)
	{
		if (_loggedFail++ < 20)
			_log?.LogWarning("Homm3StoryHubMapBackground: fail " + reason);
	}
}
