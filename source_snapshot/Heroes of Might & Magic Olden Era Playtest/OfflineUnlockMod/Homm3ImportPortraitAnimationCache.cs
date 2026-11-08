using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>Loads pre-rendered HoMM3 creature preview animation frames for recruitment UI overlays.</summary>
internal static class Homm3ImportPortraitAnimationCache
{
	private const float DefaultFrameRateMs = 120f;
	private const float MinimumFrameRateMs = 8f;
	private const float DefaultSpritePixelsPerUnit = 100f;
	private const float RifeRecruitmentSpritePixelsPerUnit = DefaultSpritePixelsPerUnit / 3f;
	private const float RifeRecruitmentShowcaseFrameRateMs = 1000f / 60f;
	// Must match TouchGroup order in tools/homm3_import/unity_editor/Homm3BillboardAnimatorBuild.ArrayBattle.cs.
	private static readonly int[] RifeBattleGlobalGroupOrder =
	{
		2, 0, 1, 3, 5, 12, 11, 13, 15, 14, 16, 20, 21
	};

	internal sealed class Clip
	{
		private readonly Sprite[] _sprites;
		private readonly Texture2D[] _textures;
		private readonly string _sid;
		private readonly bool _useRifeScale;


		internal Clip(string sid, Texture2D[] textures, float[] durationsMs, bool useRifeScale = false)
		{
			_sid = sid;
			_textures = textures;
			_useRifeScale = useRifeScale;
			DurationsMs = durationsMs;
			_sprites = new Sprite[textures.Length];
		}

		internal int FrameCount => _textures?.Length ?? 0;
		internal bool UseRifeScale => _useRifeScale;
		internal float[] DurationsMs { get; }

		internal Sprite GetSprite(int index)
		{
			if (index < 0 || index >= FrameCount)
				return null;
			var sprite = _sprites[index];
			if (sprite)
				return sprite;
			sprite = LoadSprite(_textures[index], _sid, index, _useRifeScale);
			_sprites[index] = sprite;
			return sprite;
		}
	}

	private static readonly Dictionary<string, Clip> ClipsBySid = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Clip> UnityShowcaseClipsBySid = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Clip> IdleClipsBySid = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Clip> UnityIdleClipsBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> MissingBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> MissingIdleBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedUnityShowcaseMissBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedUnityIdleMissBySid = new(StringComparer.Ordinal);

	internal static bool TryGetClip(string sid, out Clip clip, out float frameRateMs)
	{
		clip = null;
		frameRateMs = DefaultFrameRateMs;
		if (string.IsNullOrWhiteSpace(sid))
			return false;

		var key = sid.Trim();
		if (ClipsBySid.TryGetValue(key, out clip) && clip != null && clip.FrameCount > 1)
		{
			if (clip.UseRifeScale)
				return true;
			if (TryGetUnityRifeShowcaseClip(key, out var rifeClip, out frameRateMs))
			{
				clip = rifeClip;
				ClipsBySid[key] = clip;
				MissingBySid.Remove(key);
				return true;
			}
			return true;
		}

		if (MissingBySid.Contains(key))
			return false;

		if (TryGetUnityRifeShowcaseClip(key, out clip, out frameRateMs))
		{
			ClipsBySid[key] = clip;
			MissingBySid.Remove(key);
			return true;
		}

		MissingBySid.Add(key);
		return false;
	}

	private sealed class RifeClipDef
	{
		internal string Name;
		internal int[] Indices;
		internal float Fps;
	}

	private sealed class RifeBattleManifestInfo
	{
		internal List<RifeClipDef> Clips;
		internal int ChunkSize;
		internal int FrameCount;
	}

	internal static bool TryGetUnityRifeShowcaseClip(string sid, out Clip clip, out float frameRateMs)
	{
		clip = null;
		frameRateMs = 1000f / 60f;
		if (string.IsNullOrWhiteSpace(sid))
			return false;

		var key = sid.Trim();
		if (UnityShowcaseClipsBySid.TryGetValue(key, out clip))
			return clip != null && clip.FrameCount > 1;

		try
		{
			var assetKey = ResolveRecruitmentRifeAssetSid(key);
			var hasEntry = TryResolveRecruitmentRifeImportEntry(key, out var entry);
			var hasArrayManifest = TryReadArrayBattleManifest(assetKey, out var manifestInfo)
			                       && manifestInfo?.Clips != null
			                       && manifestInfo.Clips.Count > 0;
			if (hasArrayManifest)
			{
				if (!TryBuildShowcaseIndexSequence(manifestInfo.Clips, out var indices, out var durations, out frameRateMs))
				{
					LogUnityShowcaseMiss(key, "showcase clip sequence unavailable");
					return false;
				}

				if (!hasEntry)
				{
					LogUnityShowcaseMiss(key, "battle bundle entry missing");
					return false;
				}

				var textures = ResolveUnityRifeTexturesByIndices(assetKey, entry, indices, manifestInfo.ChunkSize);
				if (textures != null && textures.Length > 1)
				{
					clip = new Clip(key + "_rife_showcase", textures, durations, useRifeScale: true);
					UnityShowcaseClipsBySid[key] = clip;
					Plugin.LogSource?.LogInfo("Homm3 portrait RIFE showcase cache: using " + textures.Length + " bundled frame(s) for sid='" + key + "'" + (string.Equals(assetKey, key, StringComparison.Ordinal) ? "" : " via '" + assetKey + "'") + ".");
					return true;
				}

				LogUnityShowcaseMiss(key, "showcase RIFE bundled frames unavailable");
				return false;
			}

			if (hasEntry && TryBuildLegacyBundleRifeShowcaseClip(key, assetKey, entry, out clip, out frameRateMs))
			{
				UnityShowcaseClipsBySid[key] = clip;
				return true;
			}
			LogUnityShowcaseMiss(key, "array battle manifest and legacy bundle RIFE frames unavailable");
			return false;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 portrait RIFE showcase cache: failed for sid='" + key + "': " + ex.Message);
			return false;
		}
	}

	internal static bool TryGetRecruitmentIdleClip(string sid, out Clip clip, out float frameRateMs)
	{
		return TryGetRecruitmentIdleClip(sid, out clip, out frameRateMs, out _);
	}

	internal static bool TryGetRecruitmentIdleClip(string sid, out Clip clip, out float frameRateMs, out bool usedUnityRife)
	{
		usedUnityRife = TryGetUnityRifeIdleClip(sid, out clip, out frameRateMs);
		return usedUnityRife;
	}

	internal static bool TryGetIdleClip(string sid, out Clip clip, out float frameRateMs)
	{
		return TryGetUnityRifeIdleClip(sid, out clip, out frameRateMs);
	}
	private static bool TryGetUnityRifeIdleClip(string sid, out Clip clip, out float frameRateMs)
	{
		clip = null;
		frameRateMs = DefaultFrameRateMs;
		if (string.IsNullOrWhiteSpace(sid))
			return false;

		var key = sid.Trim();
		if (UnityIdleClipsBySid.TryGetValue(key, out clip))
			return clip != null && clip.FrameCount > 1;

		try
		{
			var assetKey = ResolveRecruitmentRifeAssetSid(key);
			if (!TryResolveRecruitmentRifeImportEntry(key, out var entry))
			{
				LogUnityIdleMiss(key, "battle bundle entry missing");
				return false;
			}

			var textures = ResolveUnityRifeIdleTextures(assetKey, entry, out frameRateMs);
			if (textures == null || textures.Length <= 1)
			{
				LogUnityIdleMiss(key, "22.Idle RIFE frames unavailable");
				return false;
			}

			clip = new Clip(key + "_rife_idle", textures, BuildConstantDurations(textures.Length, frameRateMs), useRifeScale: true);
			UnityIdleClipsBySid[key] = clip;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 portrait RIFE idle cache: failed for sid='" + key + "': " + ex.Message);
			return false;
		}
	}

	private static Texture2D[] ResolveUnityRifeIdleTextures(string sid, Homm3ImportVisuals.Entry entry, out float frameRateMs)
	{
		frameRateMs = 1000f / 60f;
		if (TryResolveArrayIdleTextures(sid, entry, out var arrayTextures, out var arrayFrameMs)
		    && arrayTextures != null
		    && arrayTextures.Length > 1)
		{
			frameRateMs = arrayFrameMs;
			return arrayTextures;
		}

		if (TryResolveIndexedMaterialIdleTextures(sid, entry, out var materialTextures, out var materialFrameMs)
		    && materialTextures != null
		    && materialTextures.Length > 1)
		{
			frameRateMs = materialFrameMs;
			return materialTextures;
		}

		return null;
	}

	private static bool TryResolveIndexedMaterialIdleTextures(string sid, Homm3ImportVisuals.Entry entry, out Texture2D[] textures, out float frameRateMs)
	{
		textures = null;
		frameRateMs = 1000f / 60f;
		if (!TryReadArrayIdleClip(sid, out var indices, out var fps, out _) || indices == null || indices.Length <= 1)
			return false;
		if (fps > 0f)
			frameRateMs = 1000f / fps;
		else
			frameRateMs = ResolveRifeFrameMs(sid, frameRateMs);
		if (!Homm3ImportVisuals.TryGetBundleBattleFrameTextures(entry, Plugin.LogSource, out var frameTextures, out _)
		    || frameTextures == null
		    || frameTextures.Length <= 1)
		{
			return false;
		}

		var result = new List<Texture2D>(indices.Length);
		for (var i = 0; i < indices.Length; i++)
		{
			var index = indices[i];
			if (index < 0 || index >= frameTextures.Length || !frameTextures[index])
				return false;
			result.Add(frameTextures[index]);
		}
		textures = result.ToArray();
		return textures.Length > 1;
	}

	private static Texture2D[] ResolveUnityRifeTexturesByIndices(string sid, Homm3ImportVisuals.Entry entry, int[] indices, int chunkSize)
	{
		if (indices == null || indices.Length <= 1)
			return null;
		if (TryResolveArrayTexturesByIndices(sid, entry, indices, chunkSize, out var arrayTextures)
		    && arrayTextures != null
		    && arrayTextures.Length > 1)
		{
			return arrayTextures;
		}
		if (TryResolveIndexedMaterialTextures(sid, entry, indices, out var materialTextures)
		    && materialTextures != null
		    && materialTextures.Length > 1)
		{
			return materialTextures;
		}
		return null;
	}

	private static bool TryResolveIndexedMaterialTextures(string sid, Homm3ImportVisuals.Entry entry, int[] indices, out Texture2D[] textures)
	{
		textures = null;
		if (indices == null || indices.Length <= 1)
			return false;
		if (!Homm3ImportVisuals.TryGetBundleBattleFrameTextures(entry, Plugin.LogSource, out var frameTextures, out _)
		    || frameTextures == null
		    || frameTextures.Length <= 1)
		{
			return false;
		}

		var result = new List<Texture2D>(indices.Length);
		for (var i = 0; i < indices.Length; i++)
		{
			var index = indices[i];
			if (index < 0 || index >= frameTextures.Length || !frameTextures[index])
				return false;
			result.Add(frameTextures[index]);
		}
		textures = result.ToArray();
		return textures.Length > 1;
	}

	private static bool TryResolveArrayIdleTextures(string sid, Homm3ImportVisuals.Entry entry, out Texture2D[] textures, out float frameRateMs)
	{
		textures = null;
		frameRateMs = 1000f / 60f;
		if (!TryReadArrayIdleClip(sid, out var indices, out var fps, out var chunkSize) || indices == null || indices.Length <= 1)
			return false;
		if (fps > 0f)
			frameRateMs = 1000f / fps;

		var bundle = Homm3ImportVisuals.TryGetLoadedBundle(entry.BundleName, Plugin.LogSource);
		if (!bundle)
			return false;
		var arrays = ResolveBattleTextureArrays(bundle);
		if (arrays.Count == 0)
			return false;

		return TryCopyArraySlices(sid, indices, chunkSize, arrays, out textures);
	}

	private static bool TryResolveArrayTexturesByIndices(string sid, Homm3ImportVisuals.Entry entry, int[] indices, int chunkSize, out Texture2D[] textures)
	{
		textures = null;
		if (indices == null || indices.Length <= 1)
			return false;
		var bundle = Homm3ImportVisuals.TryGetLoadedBundle(entry.BundleName, Plugin.LogSource);
		if (!bundle)
			return false;
		var arrays = ResolveBattleTextureArrays(bundle);
		if (arrays.Count == 0)
			return false;
		return TryCopyArraySlices(sid, indices, chunkSize, arrays, out textures);
	}

	private static bool TryCopyArraySlices(string sid, int[] indices, int chunkSize, SortedDictionary<int, Texture2DArray> arrays, out Texture2D[] textures)
	{
		textures = null;
		var result = new List<Texture2D>(indices.Length);
		try
		{
			for (var i = 0; i < indices.Length; i++)
			{
				var globalIndex = indices[i];
				var arrayIndex = chunkSize > 0 ? globalIndex / chunkSize : 0;
				var slice = chunkSize > 0 ? globalIndex % chunkSize : globalIndex;
				if (!arrays.TryGetValue(arrayIndex, out var array) || !array || slice < 0 || slice >= array.depth)
					return false;
				var texture = CopyArraySlice(array, slice, sid, i);
				if (!texture)
					return false;
				result.Add(texture);
			}
		}
		finally
		{
			if (result.Count != indices.Length)
			{
				for (var i = 0; i < result.Count; i++)
					if (result[i])
						UnityEngine.Object.Destroy(result[i]);
			}
		}
		textures = result.ToArray();
		return textures.Length > 1;
	}

	private static SortedDictionary<int, Texture2DArray> ResolveBattleTextureArrays(AssetBundle bundle)
	{
		var result = new SortedDictionary<int, Texture2DArray>();
		try
		{
			var names = bundle.GetAllAssetNames();
			if (names == null)
				return result;
			for (var i = 0; i < names.Length; i++)
			{
				var assetName = names[i];
				if (string.IsNullOrEmpty(assetName)
				    || assetName.IndexOf("/generated/billboardanim/array/", StringComparison.OrdinalIgnoreCase) < 0
				    || assetName.IndexOf("battle_frames_array_", StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				var index = TryParseTrailingIndex(assetName, "battle_frames_array_");
				if (index < 0)
					continue;
				var array = bundle.LoadAsset<Texture2DArray>(assetName);
				if (!array)
					continue;
				array.filterMode = FilterMode.Bilinear;
				array.wrapMode = TextureWrapMode.Clamp;
				result[index] = array;
			}
		}
		catch
		{
		}
		return result;
	}

	private static bool TryBuildLegacyBundleRifeShowcaseClip(string key, string assetKey, Homm3ImportVisuals.Entry entry, out Clip clip, out float frameRateMs)
	{
		clip = null;
		frameRateMs = ResolveRifeFrameMs(assetKey, RifeRecruitmentShowcaseFrameRateMs);
		if (entry == null || string.IsNullOrEmpty(entry.BundleName))
			return false;

		if (!TryResolveLegacyBundleBattleTextures(entry, out var textures)
		    || textures == null
		    || textures.Length <= 1)
		{
			return false;
		}

		clip = new Clip(key + "_rife_showcase", textures, BuildConstantDurations(textures.Length, frameRateMs), useRifeScale: true);
		Plugin.LogSource?.LogInfo("Homm3 portrait RIFE showcase cache: using " + textures.Length + " legacy bundle frame(s) for sid='" + key + "'" + (string.Equals(assetKey, key, StringComparison.Ordinal) ? "" : " via '" + assetKey + "'") + ".");
		return true;
	}

	private static bool TryResolveLegacyBundleBattleTextures(Homm3ImportVisuals.Entry entry, out Texture2D[] textures)
	{
		textures = null;
		if (!Homm3ImportVisuals.TryGetBundleBattleFrameTextures(entry, Plugin.LogSource, out var frameTextures, out _)
		    || frameTextures == null
		    || frameTextures.Length <= 1)
		{
			return false;
		}

		var ordered = new List<Texture2D>(frameTextures.Length);
		for (var i = 0; i < frameTextures.Length; i++)
		{
			var texture = frameTextures[i];
			if (texture)
				ordered.Add(texture);
		}
		textures = ordered.ToArray();
		return textures.Length > 1;
	}

	private static bool TryReadArrayIdleClip(string sid, out int[] indices, out float fps, out int chunkSize)
	{
		indices = null;
		fps = 0f;
		chunkSize = 2048;
		if (!TryReadArrayBattleManifest(sid, out var manifest) || manifest?.Clips == null)
			return false;
		try
		{
			chunkSize = manifest.ChunkSize > 0 ? manifest.ChunkSize : 2048;
			for (var i = 0; i < manifest.Clips.Count; i++)
			{
				var clip = manifest.Clips[i];
				if (clip == null || !string.Equals(clip.Name, "22.Idle", StringComparison.OrdinalIgnoreCase))
					continue;
				fps = clip.Fps;
				indices = clip.Indices;
				return indices != null && indices.Length > 1;
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 portrait RIFE idle cache: manifest parse failed for sid='" + sid + "': " + ex.Message);
		}
		return false;
	}

	private static bool TryReadArrayBattleManifest(string sid, out RifeBattleManifestInfo info)
	{
		info = null;
		var path = ResolveArrayBattleManifestPath(sid);
		if (string.IsNullOrEmpty(path) || !File.Exists(path))
			return false;
		try
		{
			var root = JObject.Parse(File.ReadAllText(path));
			if (!int.TryParse(root["arrayChunkSize"]?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var chunkSize))
				chunkSize = 2048;
			if (chunkSize <= 0)
				chunkSize = 2048;
			var clipsToken = root["clips"];
			if (clipsToken == null || clipsToken.Type != JTokenType.Array || !TryParseJsonArray(clipsToken, out var clips) || clips.Count == 0)
			{
				LogUnityShowcaseMiss(sid, "array battle manifest has no clips");
				return false;
			}
			var result = new List<RifeClipDef>();
			for (var i = 0; i < clips.Count; i++)
			{
				if (!TryParseJsonObject(clips[i], out var row))
					continue;
				var name = row["name"]?.ToString();
				var indicesToken = row["indices"];
				if (string.IsNullOrWhiteSpace(name)
				    || indicesToken == null
				    || indicesToken.Type != JTokenType.Array
				    || !TryParseJsonArray(indicesToken, out var indicesArray)
				    || indicesArray.Count == 0)
				{
					continue;
				}
				var indices = new List<int>();
				for (var j = 0; j < indicesArray.Count; j++)
				{
					if (int.TryParse(indicesArray[j]?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var index) && index >= 0)
						indices.Add(index);
				}
				if (indices.Count <= 1)
					continue;
				if (!Homm3JsonNumber.TryParseFloat(row["fps"]?.ToString(), out var fps) || fps <= 0f)
					fps = 60f;
				result.Add(new RifeClipDef { Name = name, Indices = indices.ToArray(), Fps = fps });
			}
			if (result.Count == 0)
			{
				LogUnityShowcaseMiss(sid, "array battle manifest clips contain no usable indices");
				return false;
			}
			info = new RifeBattleManifestInfo
			{
				Clips = result,
				ChunkSize = chunkSize,
				FrameCount = int.TryParse(root["frameCount"]?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var frameCount)
					? frameCount
					: 0
			};
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 portrait RIFE showcase cache: manifest parse failed for sid='" + sid + "': " + ex.Message);
			return false;
		}
	}

	private static bool TryBuildShowcaseIndexSequence(List<RifeClipDef> clipDefs, out int[] indices, out float[] durations, out float frameRateMs)
	{
		indices = null;
		durations = null;
		frameRateMs = 1000f / 60f;
		if (clipDefs == null || clipDefs.Count == 0)
			return false;
		RifeClipDef idle = null;
		for (var i = 0; i < clipDefs.Count; i++)
			if (string.Equals(clipDefs[i]?.Name, "22.Idle", StringComparison.OrdinalIgnoreCase))
			{
				idle = clipDefs[i];
				break;
			}
		if (idle == null || idle.Indices == null || idle.Indices.Length <= 1)
			return false;

		var sequence = new List<int>();
		var durationList = new List<float>();
		void Append(RifeClipDef clip)
		{
			var ms = RifeRecruitmentShowcaseFrameRateMs;
			for (var i = 0; i < clip.Indices.Length; i++)
			{
				sequence.Add(clip.Indices[i]);
				durationList.Add(ms);
			}
		}

		Append(idle);
		for (var i = 0; i < clipDefs.Count; i++)
		{
			var clip = clipDefs[i];
			if (clip == null || clip.Indices == null || clip.Indices.Length <= 1)
				continue;
			if (string.Equals(clip.Name, "22.Idle", StringComparison.OrdinalIgnoreCase))
				continue;
			Append(clip);
			Append(idle);
		}
		if (sequence.Count <= idle.Indices.Length)
			return false;
		frameRateMs = RifeRecruitmentShowcaseFrameRateMs;
		indices = sequence.ToArray();
		durations = durationList.ToArray();
		return indices.Length > 1;
	}

	private static bool TryParseJsonArray(JToken token, out JArray array)
	{
		array = null;
		if (token == null || token.Type != JTokenType.Array)
			return false;
		try
		{
			array = JArray.Parse(token.ToString());
			return array != null;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryParseJsonObject(JToken token, out JObject obj)
	{
		obj = null;
		if (token == null || token.Type != JTokenType.Object)
			return false;
		try
		{
			obj = JObject.Parse(token.ToString());
			return obj != null;
		}
		catch
		{
			return false;
		}
	}

	private static string ResolveArrayBattleManifestPath(string sid)
	{
		if (string.IsNullOrEmpty(sid))
			return null;
		var relative = Path.Combine("homm3_lab", sid, "Generated", "BillboardAnim", "array_battle_manifest.json");
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(relative, out var startupPath) && File.Exists(startupPath))
			return startupPath;
		var directPlugin = Path.Combine(BepInEx.Paths.PluginPath, relative);
		if (File.Exists(directPlugin))
			return directPlugin;
		var offlinePlugin = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", relative);
		if (File.Exists(offlinePlugin))
			return offlinePlugin;
		return null;
	}

	private static string ResolveRecruitmentRifeAssetSid(string sid)
	{
		if (TryResolveRecruitmentRifeImportEntry(sid, out var entry))
		{
			var labSid = Homm3ImportVisuals.TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
			if (!string.IsNullOrEmpty(labSid))
				return labSid;
		}
		if (HasRecruitmentRifeManifest(sid))
			return sid;
		var mapped = ResolveKnownRecruitmentRifeAlias(sid);
		if (!string.IsNullOrEmpty(mapped) && HasRecruitmentRifeAsset(mapped))
			return mapped;
		if (HasRecruitmentRifeAsset(sid))
			return sid;
		return sid;
	}

	private static bool TryResolveRecruitmentRifeImportEntry(string sid, out Homm3ImportVisuals.Entry entry)
	{
		entry = null;
		return !string.IsNullOrWhiteSpace(sid)
		       && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(sid.Trim(), Plugin.LogSource, out entry)
		       && entry != null
		       && !string.IsNullOrEmpty(entry.BundleName);
	}

	private static string ResolveKnownRecruitmentRifeAlias(string sid)
	{
		if (string.IsNullOrEmpty(sid))
			return null;
		switch (sid)
		{
			case "h3_gnoll_upg":
				return "h3_gnoll_marauder";
			case "h3_gnoll_upg_alt":
				return "h3_gnoll_shaman";
			case "h3_lizardman_upg":
				return "h3_lizard_warrior";
			case "h3_lizardman_upg_alt":
				return "h3_lizard_assassin";
			case "h3_basilisk_upg":
				return "h3_greater_basilisk";
			case "h3_basilisk_upg_alt":
				return "h3_basilisk_flamespitter";
			case "h3_gorgon_upg":
				return "h3_mighty_gorgon";
			case "h3_gorgon_upg_alt":
				return "h3_corrosive_gorgon";
			case "h3_wyvern_upg":
				return "h3_wyvern_monarch";
			case "h3_wyvern_upg_alt":
				return "h3_paokai";
			case "h3_hydra_upg":
				return "h3_chaos_hydra";
			case "h3_hydra_upg_alt":
				return "h3_ruinous_hydra";
		}
		if (string.Equals(sid, "h3_serpent_fly_upg_alt", StringComparison.Ordinal) && HasRecruitmentRifeAsset("h3_damsel_fly"))
			return "h3_damsel_fly";
		if (string.Equals(sid, "h3_serpent_fly_upg", StringComparison.Ordinal) && HasRecruitmentRifeAsset("h3_dragon_fly"))
			return "h3_dragon_fly";
		if (!string.IsNullOrEmpty(sid)
		    && sid.StartsWith("h3_serpent_fly", StringComparison.Ordinal)
		    && HasRecruitmentRifeAsset("h3_serpent_fly"))
		{
			return "h3_serpent_fly";
		}
		return null;
	}

	private static bool HasRecruitmentRifeAsset(string sid)
	{
		if (HasRecruitmentRifeManifest(sid))
			return true;
		return Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(sid, null, out var entry)
		       && entry != null
		       && !string.IsNullOrEmpty(entry.BundleName);
	}

	private static bool HasRecruitmentRifeManifest(string sid)
	{
		return !string.IsNullOrEmpty(sid)
		       && !string.IsNullOrEmpty(ResolveArrayBattleManifestPath(sid));
	}

	private static Texture2D CopyArraySlice(Texture2DArray array, int slice, string sid, int frameIndex)
	{
		Texture2D texture = null;
		try
		{
			texture = new Texture2D(array.width, array.height, array.format, mipChain: false);
			texture.name = "homm3_portrait_rife_array_" + sid + "_" + frameIndex.ToString("000");
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			Graphics.CopyTexture(array, slice, 0, texture, 0, 0);
			texture.hideFlags = HideFlags.DontUnloadUnusedAsset;
			return texture;
		}
		catch (Exception ex)
		{
			if (texture)
				UnityEngine.Object.Destroy(texture);
			Plugin.LogSource?.LogWarning("Homm3 portrait RIFE idle cache: array slice copy failed for sid='" + sid + "' slice=" + slice + ": " + ex.Message);
			return null;
		}
	}

	private static int TryParseTrailingIndex(string assetName, string prefix)
	{
		if (string.IsNullOrEmpty(assetName) || string.IsNullOrEmpty(prefix))
			return -1;
		var file = Path.GetFileNameWithoutExtension(assetName.Replace('\\', '/'));
		var start = file.LastIndexOf(prefix, StringComparison.OrdinalIgnoreCase);
		if (start < 0)
			return -1;
		start += prefix.Length;
		return int.TryParse(file.Substring(start), out var parsed) ? parsed : -1;
	}

	private static float ResolveRifeFrameMs(string sid, float fallback)
	{
		var path = ResolveLabSidecarPath(sid, "extracted_battle", ".rife120_done.json");
		if (File.Exists(path))
		{
			try
			{
				var json = JObject.Parse(File.ReadAllText(path));
				var fpsToken = json["targetFps"];
				if (fpsToken != null && Homm3JsonNumber.TryParseFloat(fpsToken.ToString(), out var fps) && fps > 0f)
					return 1000f / fps;
			}
			catch
			{
			}
		}
		return fallback;
	}

	private static string ResolveLabSidecarPath(string sid, string folder, string fileName)
	{
		if (string.IsNullOrEmpty(sid) || string.IsNullOrEmpty(folder) || string.IsNullOrEmpty(fileName))
			return null;
		var relative = Path.Combine("homm3_lab", sid, folder, fileName);
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(relative, out var startupPath) && File.Exists(startupPath))
			return startupPath;
		var directPlugin = Path.Combine(BepInEx.Paths.PluginPath, relative);
		if (File.Exists(directPlugin))
			return directPlugin;
		var offlinePlugin = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", relative);
		return File.Exists(offlinePlugin) ? offlinePlugin : null;
	}

	private static void LogUnityShowcaseMiss(string sid, string reason)
	{
		if (string.IsNullOrEmpty(sid) || !LoggedUnityShowcaseMissBySid.Add(sid))
			return;
		Plugin.LogSource?.LogInfo("Homm3 portrait RIFE showcase cache: bundled showcase unavailable for sid='" + sid + "' because " + reason + ".");
	}

	private static void LogUnityIdleMiss(string sid, string reason)
	{
		if (string.IsNullOrEmpty(sid) || !LoggedUnityIdleMissBySid.Add(sid))
			return;
		Plugin.LogSource?.LogInfo("Homm3 portrait RIFE idle cache: bundled idle unavailable for sid='" + sid + "' because " + reason + ".");
	}

	internal static int ValidateRequiredIdleClipMetadata()
	{
		var required = new SortedSet<string>(Homm3CustomFactionRegistry.EnumerateCustomUnitSids(), StringComparer.Ordinal);
		var count = 0;
		foreach (var sid in required)
		{
			var key = sid?.Trim();
			if (string.IsNullOrEmpty(key))
				throw new InvalidOperationException("HoMM3 custom unit registry produced a blank SID during required recruitment portrait idle clip validation.");

			var assetKey = ResolveRecruitmentRifeAssetSid(key);
			if (!TryResolveRecruitmentRifeImportEntry(key, out var entry) || entry == null || string.IsNullOrEmpty(entry.BundleName))
			{
				throw new InvalidOperationException(
					"required HoMM3 recruitment portrait idle clip is missing a bundled battle import entry for sid='"
					+ key
					+ "'.");
			}

			if (!TryReadArrayIdleClip(assetKey, out var indices, out _, out _)
			    || indices == null
			    || indices.Length <= 1)
			{
				throw new InvalidOperationException(
					"required HoMM3 recruitment portrait idle clip metadata is missing 22.Idle bundled RIFE frames for sid='"
					+ key
					+ "' asset='"
					+ assetKey
					+ "'.");
			}

			count++;
		}
		return count;
	}

	private static float ReadDuration(JArray durations, int index, float fallback)
	{
		if (durations != null && index < durations.Count && Homm3JsonNumber.TryParseFloat(durations[index]?.ToString(), out var parsed))
			return Mathf.Max(MinimumFrameRateMs, parsed);
		return Mathf.Max(MinimumFrameRateMs, fallback);
	}

	private static float[] BuildConstantDurations(int count, float durationMs)
	{
		var durations = new float[count];
		var clamped = Mathf.Max(MinimumFrameRateMs, durationMs);
		for (var i = 0; i < durations.Length; i++)
			durations[i] = clamped;
		return durations;
	}

	private static Sprite LoadSprite(Texture2D texture, string sid, int index, bool useRifeScale)
	{
		if (!texture)
			return null;
		var sprite = Sprite.Create(
			texture,
			new Rect(0f, 0f, texture.width, texture.height),
			new Vector2(0.5f, 0.5f),
			GetSpritePixelsPerUnit(useRifeScale),
			0,
			SpriteMeshType.FullRect);
		sprite.name = texture.name ?? ("homm3_portrait_rife_" + sid + "_" + index.ToString("000"));
		return sprite;
	}

	private static float GetSpritePixelsPerUnit(bool useRifeScale)
	{
		return useRifeScale ? RifeRecruitmentSpritePixelsPerUnit : DefaultSpritePixelsPerUnit;
	}

}
