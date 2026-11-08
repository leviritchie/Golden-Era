using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdLawIconSpriteCache
{
	private const string FolderName = "homm3_law_icons";
	private static readonly Dictionary<string, Sprite> SpritesBySid = new(StringComparer.Ordinal);

	internal static bool IsStrongholdLawIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var sid = key.Trim();
		return sid.StartsWith("fraction_law_homm3_", StringComparison.Ordinal)
			&& sid.EndsWith("_icon", StringComparison.Ordinal)
			&& Homm3CustomFactionRegistry.TryGetFactionSidForCustomUiIconKey(sid, out _);
	}

	internal static bool TryGetOrCreateSprite(string iconKey, out Sprite sprite)
	{
		sprite = null;
		if (!IsStrongholdLawIconKey(iconKey))
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

			texture.name = "homm3_law_icon_" + sid;
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = "homm3_law_icon_sprite_" + sid;
			SpritesBySid[sid] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3StrongholdLawIcon: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

	private static string ResolveIconPath(string sid)
	{
		var file = sid + ".png";
		var roots = new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath };
		foreach (var root in roots)
		{
			var path = Path.Combine(root, "OfflineUnlockMod", FolderName, file);
			if (File.Exists(path))
				return path;
		}
		return null;
	}
}
