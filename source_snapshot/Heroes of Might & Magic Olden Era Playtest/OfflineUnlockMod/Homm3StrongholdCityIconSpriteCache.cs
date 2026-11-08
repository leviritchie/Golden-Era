using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdCityIconSpriteCache
{
	private static readonly Dictionary<string, Sprite> SpritesByKey = new(StringComparer.Ordinal);

	internal static bool IsStrongholdCityIconKey(string key)
	{
		return Homm3CustomFactionRegistry.TryGetCityIconAsset(key, out _, out _);
	}

	internal static bool TryGetOrCreateSprite(string iconKey, out Sprite sprite)
	{
		sprite = null;
		if (!Homm3CustomFactionRegistry.TryGetCityIconAsset(iconKey, out var spriteKey, out var relativePath))
			return false;

		if (SpritesByKey.TryGetValue(spriteKey, out sprite) && sprite)
			return true;

		if (!Homm3CustomFactionRegistry.TryGetStartupAssetPath(relativePath, out var path))
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

			texture.name = spriteKey;
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = spriteKey + "_sprite";
			// Prewarmed at the main menu and handed to native UI (catalog, city list Pic). Only managed
			// wrappers hold these, and the GameLoading / session-end UnloadUnusedAssets passes free
			// such objects, so pin both (gate: tools/validate_runtime_ui_sprite_persistence_contract.py).
			texture.hideFlags = HideFlags.DontUnloadUnusedAsset;
			sprite.hideFlags = HideFlags.DontUnloadUnusedAsset;
			SpritesByKey[spriteKey] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3StrongholdCityIcon: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

	internal static int PrewarmManifestSprites()
	{
		var loaded = 0;
		foreach (var citySid in Homm3CustomFactionRegistry.EnumerateCitySids())
		{
			if (!TryGetOrCreateSprite(citySid, out _))
				throw new InvalidOperationException("Failed to prewarm HoMM3 city icon sprite for " + citySid + ".");
			loaded++;
		}
		return loaded;
	}

}
