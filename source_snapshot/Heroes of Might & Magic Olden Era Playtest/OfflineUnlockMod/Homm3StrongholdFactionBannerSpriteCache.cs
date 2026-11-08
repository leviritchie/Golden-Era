using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdFactionBannerSpriteCache
{
	private const string SpriteName = "homm3_stronghold_faction_banner";
	private const string CardSpriteName = "homm3_stronghold_faction_card";
	private static readonly string RelativePath = Path.Combine(
		"homm3_runtime_assets",
		"faction_icons",
		"homm3_stronghold",
		"Stronghold_H6_banner.png");
	private static readonly string CardRelativePath = Path.Combine(
		"homm3_runtime_assets",
		"town_scene_refs",
		"homm3_stronghold",
		"Stronghold-in-background.png");
	private static readonly Dictionary<string, Sprite> SpritesByKey = new(StringComparer.Ordinal);

	internal static bool TryGetOrCreateSprite(out Sprite sprite)
	{
		const string key = SpriteName;
		sprite = null;
		if (SpritesByKey.TryGetValue(key, out sprite) && sprite)
			return true;

		return TryLoadSprite(SpriteName, RelativePath, out sprite);
	}

	internal static bool TryGetOrCreateCardSprite(out Sprite sprite)
	{
		const string key = CardSpriteName;
		sprite = null;
		if (SpritesByKey.TryGetValue(key, out sprite) && sprite)
			return true;

		return TryLoadSprite(CardSpriteName, CardRelativePath, out sprite);
	}

	internal static bool TryGetOrCreateSpriteForFaction(string factionSid, out Sprite sprite)
	{
		sprite = null;
		return Homm3CustomFactionRegistry.TryGetFactionSpriteAsset(factionSid, card: false, out var key, out var relativePath)
		       && TryGetOrLoadSprite(key, relativePath, out sprite);
	}

	internal static bool TryGetOrCreateCardSpriteForFaction(string factionSid, out Sprite sprite)
	{
		sprite = null;
		return Homm3CustomFactionRegistry.TryGetFactionSpriteAsset(factionSid, card: true, out var key, out var relativePath)
		       && TryGetOrLoadSprite(key, relativePath, out sprite);
	}

	internal static int PrewarmManifestSprites()
	{
		var loaded = 0;
		foreach (var factionSid in Homm3CustomFactionRegistry.EnumerateFactionSids())
		{
			if (!TryGetOrCreateSpriteForFaction(factionSid, out _))
				throw new InvalidOperationException("Failed to prewarm HoMM3 faction icon sprite for " + factionSid + ".");
			loaded++;

			if (!TryGetOrCreateCardSpriteForFaction(factionSid, out _))
				throw new InvalidOperationException("Failed to prewarm HoMM3 faction card sprite for " + factionSid + ".");
			loaded++;
		}
		return loaded;
	}

	internal static bool IsStrongholdCardSprite(Sprite sprite)
	{
		return sprite != null
			&& string.Equals(sprite.name, CardSpriteName + "_sprite", StringComparison.Ordinal);
	}

	internal static bool IsStrongholdSprite(Sprite sprite)
	{
		return sprite != null
			&& (string.Equals(sprite.name, SpriteName + "_sprite", StringComparison.Ordinal)
			    || string.Equals(sprite.name, CardSpriteName + "_sprite", StringComparison.Ordinal));
	}

	internal static bool IsHomm3FactionSprite(Sprite sprite)
	{
		if (sprite == null)
			return false;
		foreach (var factionSid in Homm3CustomFactionRegistry.EnumerateFactionSids())
		{
			if (Homm3CustomFactionRegistry.TryGetFactionSpriteAsset(factionSid, card: false, out var iconKey, out _)
			    && string.Equals(sprite.name, iconKey + "_sprite", StringComparison.Ordinal))
				return true;
			if (Homm3CustomFactionRegistry.TryGetFactionSpriteAsset(factionSid, card: true, out var cardKey, out _)
			    && string.Equals(sprite.name, cardKey + "_sprite", StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool TryGetOrLoadSprite(string key, string relativePath, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(relativePath))
			return false;
		if (SpritesByKey.TryGetValue(key, out sprite) && sprite)
			return true;
		return TryLoadSprite(key, relativePath, out sprite);
	}

	private static bool TryLoadSprite(string key, string relativePath, out Sprite sprite)
	{
		sprite = null;
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

			texture.name = key;
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = key + "_sprite";
			// The SoFractions clone (Plugin.cs SoFractionsCustomFactionAliasPatch) keeps these in a
			// FractionLobbyAsset that only a managed GC handle roots. UnloadUnusedAssets at GameLoading
			// and at session end does not see that root and frees the sprite, which blanks the HUD
			// factionPic / side-timer faction icons. Pin both (gate: tools/validate_runtime_ui_sprite_persistence_contract.py).
			texture.hideFlags = HideFlags.DontUnloadUnusedAsset;
			sprite.hideFlags = HideFlags.DontUnloadUnusedAsset;
			SpritesByKey[key] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3StrongholdFactionBanner: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

}
