using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3FactionSkillIconSpriteCache
{
	private const string FolderName = "homm3_skill_icons";
	private static readonly Dictionary<string, Sprite> SpritesBySid = new(StringComparer.Ordinal);

	internal static bool IsFactionSkillIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var sid = key.Trim();
		return TryGetFactionSkillIconFaction(sid, out _) || IsPackagedCustomSubSkillIconKey(sid) || IsPackagedCastleEliteStrategemSpellIconKey(sid);
	}

	internal static bool TryGetFactionSkillIconFaction(string key, out string factionSid)
	{
		factionSid = null;
		if (string.IsNullOrWhiteSpace(key))
			return false;

		var sid = key.Trim();
		foreach (var current in Homm3CustomFactionRegistry.EnumerateFactionSids())
		{
			var baseKey = "skill_faction_" + current;
			if (string.Equals(sid, baseKey, StringComparison.Ordinal)
			    || string.Equals(sid, baseKey + "_2", StringComparison.Ordinal)
			    || string.Equals(sid, baseKey + "_3", StringComparison.Ordinal))
			{
				factionSid = current;
				return true;
			}
		}
		return false;
	}

	internal static bool TryGetOrCreateSprite(string iconKey, out Sprite sprite)
	{
		sprite = null;
		if (!IsFactionSkillIconKey(iconKey))
			return false;

		var sid = iconKey.Trim();
		if (SpritesBySid.TryGetValue(sid, out sprite) && sprite)
			return true;

		var path = ResolveIconPath(sid);
		if (path == null)
			return false;

		try
		{
			var bytes = File.ReadAllBytes(path);
			var texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: false);
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			if (!ImageConversion.LoadImage(texture, il2cppBytes))
			{
				UnityEngine.Object.Destroy(texture);
				return false;
			}

			texture.name = "homm3_skill_icon_" + sid;
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = "homm3_skill_icon_sprite_" + sid;
			SpritesBySid[sid] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3FactionSkillIcon: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

	private static bool IsPackagedCustomSubSkillIconKey(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && sid.Trim().StartsWith("sub_skill_faction_homm3_", StringComparison.Ordinal)
		       && ResolveIconPath(sid.Trim()) != null;
	}

	private static bool IsPackagedCastleEliteStrategemSpellIconKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		return (string.Equals(key, "homm3_castle_elite_strategem_spread_out", StringComparison.Ordinal)
		        || string.Equals(key, "homm3_castle_elite_strategem_compress", StringComparison.Ordinal)
		        || string.Equals(key, "homm3_castle_elite_strategem_ambush", StringComparison.Ordinal))
		       && ResolveIconPath(key) != null;
	}

	private static string ResolveIconPath(string sid)
	{
		var file = sid + ".png";
		var path = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", FolderName, file);
		return File.Exists(path) ? path : null;
	}
}
