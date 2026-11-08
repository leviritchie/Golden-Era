using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3FactorySplitAssemblyHudSpriteCache
{
	internal const string FolderName = "homm3_factory_split_assembly_hud";

	internal static readonly string[] RequiredSpriteNames =
	{
		"rail_frame",
		"pip_natural_empty",
		"pip_natural_filled",
		"pip_natural_locked",
		"pip_industrial_empty",
		"pip_industrial_filled",
		"pip_industrial_locked",
		"header_natural",
		"header_industrial",
		"overclock_mark",
		"tooltip_banner",
	};

	private static readonly Dictionary<string, Sprite> SpritesByName = new(StringComparer.Ordinal);
	private static bool _missingLogged;

	internal static bool TryGetOrCreateSprite(string name, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(name))
			return false;
		var key = name.Trim();
		if (SpritesByName.TryGetValue(key, out sprite) && sprite)
			return true;

		var path = ResolveIconPath(key);
		if (path == null)
		{
			LogMissingOnce(key);
			return false;
		}

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

			texture.name = "homm3_factory_split_assembly_hud_" + key;
			texture.filterMode = FilterMode.Point;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = "homm3_factory_split_assembly_hud_sprite_" + key;
			SpritesByName[key] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(
				"HoMM3 Factory Split Assembly HUD: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

	internal static bool TryRequireAll(out string failReason)
	{
		failReason = null;
		for (var i = 0; i < RequiredSpriteNames.Length; i++)
		{
			var name = RequiredSpriteNames[i];
			if (TryGetOrCreateSprite(name, out var sprite) && sprite)
				continue;
			failReason = "missing required HUD sprite '" + name + "' under " + FolderName;
			return false;
		}
		return true;
	}

	private static string ResolveIconPath(string name)
	{
		var file = name + ".png";
		var path = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", FolderName, file);
		return File.Exists(path) ? path : null;
	}

	private static void LogMissingOnce(string name)
	{
		if (_missingLogged)
			return;
		_missingLogged = true;
		Plugin.LogSource?.LogWarning(
			"HoMM3 Factory Split Assembly HUD: required sprite missing fail-closed: "
			+ name
			+ " (folder "
			+ FolderName
			+ ")");
	}
}
