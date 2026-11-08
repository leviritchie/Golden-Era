using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Loads HoMM3 artifact menu icons from plugin PNGs under
/// <c>homm3_runtime_assets/artifacts/icons/{sid}.png</c>.
/// Proof boundary: source/static + generated assets; runtime UI bind unvalidated until live inventory open.
/// </summary>
internal static class Homm3ArtifactIconSpriteCache
{
	private const string IconFolder = "homm3_runtime_assets/artifacts/icons";
	private const string SidPrefix = "homm3_artifact_";
	private static readonly Dictionary<string, Sprite> SpritesByKey = new(StringComparer.Ordinal);

	internal static bool IsArtifactIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		return key.Trim().StartsWith(SidPrefix, StringComparison.Ordinal);
	}

	internal static bool TryGetOrCreateSprite(string iconKey, out Sprite sprite)
	{
		sprite = null;
		if (!IsArtifactIconKey(iconKey))
			return false;

		var key = iconKey.Trim();
		if (SpritesByKey.TryGetValue(key, out sprite) && sprite)
			return true;

		var path = ResolveIconPath(key);
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

			texture.name = "homm3_artifact_icon_" + key;
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = "homm3_artifact_icon_sprite_" + key;
			SpritesByKey[key] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3ArtifactIcon: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

	private static string ResolveIconPath(string sid)
	{
		var file = sid + ".png";
		var roots = new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath };
		foreach (var root in roots)
		{
			var path = Path.Combine(root, "OfflineUnlockMod", IconFolder, file);
			if (File.Exists(path))
				return path;
			// Also accept assets deployed beside the plugin without OfflineUnlockMod nesting.
			path = Path.Combine(root, IconFolder, file);
			if (File.Exists(path))
				return path;
		}
		return null;
	}
}
