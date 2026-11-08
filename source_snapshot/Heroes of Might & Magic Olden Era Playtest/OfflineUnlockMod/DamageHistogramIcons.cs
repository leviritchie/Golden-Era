using System;
using System.IO;
using BepInEx;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class DamageHistogramIcons
{
	private const string IconFolder = "histogram_icons";
	private const string AttackFile = "attack.png";
	private const string RetaliationFile = "retaliation.png";

	private static Texture2D s_attackTexture;
	private static Texture2D s_retaliationTexture;
	private static Sprite s_attackSprite;
	private static Sprite s_retaliationSprite;

	internal static Texture2D GetTexture(bool retaliation)
	{
		if (retaliation)
		{
			if (s_retaliationTexture == null || s_retaliationTexture.Equals(null))
				s_retaliationTexture = LoadOrBuildTexture(RetaliationFile, "damage_histogram_retaliation_icon", true);
			return s_retaliationTexture;
		}

		if (s_attackTexture == null || s_attackTexture.Equals(null))
			s_attackTexture = LoadOrBuildTexture(AttackFile, "damage_histogram_attack_icon", false);
		return s_attackTexture;
	}

	internal static Sprite GetSprite(bool retaliation)
	{
		if (retaliation)
		{
			if (s_retaliationSprite == null || s_retaliationSprite.Equals(null))
				s_retaliationSprite = SpriteFrom(GetTexture(true), "damage_histogram_retaliation_icon_sprite");
			return s_retaliationSprite;
		}

		if (s_attackSprite == null || s_attackSprite.Equals(null))
			s_attackSprite = SpriteFrom(GetTexture(false), "damage_histogram_attack_icon_sprite");
		return s_attackSprite;
	}

	private static Sprite SpriteFrom(Texture2D texture, string name)
	{
		if (texture == null || texture.Equals(null))
			return null;
		var sprite = Sprite.Create(
			texture,
			new Rect(0f, 0f, texture.width, texture.height),
			new Vector2(0.5f, 0.5f),
			100f,
			0,
			SpriteMeshType.FullRect);
		sprite.name = name;
		return sprite;
	}

	private static Texture2D LoadOrBuildTexture(string fileName, string textureName, bool retaliation)
	{
		var path = ResolveIconPath(fileName);
		if (path != null)
		{
			try
			{
				var bytes = File.ReadAllBytes(path);
				var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
				var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
				for (var i = 0; i < bytes.Length; i++)
					il2cppBytes[i] = bytes[i];
				if (ImageConversion.LoadImage(texture, il2cppBytes))
				{
					texture.name = textureName;
					texture.filterMode = FilterMode.Bilinear;
					texture.wrapMode = TextureWrapMode.Clamp;
					return texture;
				}
				UnityEngine.Object.Destroy(texture);
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning("Damage histogram icon load failed: " + fileName + " (" + ex.Message + ")");
			}
		}

		return BuildFallbackTexture(textureName, retaliation);
	}

	private static string ResolveIconPath(string fileName)
	{
		var candidates = new[]
		{
			Path.Combine(Paths.PluginPath, "DamageHistogramMod", IconFolder, fileName),
			Path.Combine(Paths.BepInExRootPath, "plugins", "DamageHistogramMod", IconFolder, fileName),
			Path.Combine(Paths.PluginPath, "OfflineUnlockMod", IconFolder, fileName),
			Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", IconFolder, fileName),
			Path.Combine(Application.dataPath, "..", "DamageHistogramMod", IconFolder, fileName),
			Path.Combine(Application.dataPath, "..", "OfflineUnlockMod", IconFolder, fileName)
		};
		for (var i = 0; i < candidates.Length; i++)
		{
			try
			{
				var p = Path.GetFullPath(candidates[i]);
				if (File.Exists(p))
					return p;
			}
			catch
			{
			}
		}
		return null;
	}

	private static Texture2D BuildFallbackTexture(string name, bool retaliation)
	{
		var texture = new Texture2D(32, 32, TextureFormat.RGBA32, false);
		var clear = new Color32(255, 255, 255, 0);
		var pixels = new Color32[32 * 32];
		for (var i = 0; i < pixels.Length; i++)
			pixels[i] = clear;
		texture.SetPixels32(pixels);
		if (retaliation)
		{
			DrawLine(texture, 16, 4, 25, 9, 3);
			DrawLine(texture, 25, 9, 22, 21, 3);
			DrawLine(texture, 22, 21, 16, 28, 3);
			DrawLine(texture, 16, 28, 10, 21, 3);
			DrawLine(texture, 10, 21, 7, 9, 3);
			DrawLine(texture, 7, 9, 16, 4, 3);
			DrawLine(texture, 21, 14, 13, 14, 3);
			DrawLine(texture, 13, 14, 16, 11, 3);
			DrawLine(texture, 13, 14, 16, 17, 3);
		}
		else
		{
			DrawLine(texture, 8, 24, 23, 9, 3);
			DrawLine(texture, 22, 8, 27, 6, 3);
			DrawLine(texture, 24, 8, 26, 13, 3);
			DrawLine(texture, 12, 20, 16, 24, 3);
			DrawLine(texture, 7, 25, 4, 28, 3);
		}
		texture.Apply();
		texture.name = name;
		texture.filterMode = FilterMode.Bilinear;
		texture.wrapMode = TextureWrapMode.Clamp;
		return texture;
	}

	private static void DrawLine(Texture2D texture, int x0, int y0, int x1, int y1, int radius)
	{
		var dx = Math.Abs(x1 - x0);
		var dy = Math.Abs(y1 - y0);
		var sx = x0 < x1 ? 1 : -1;
		var sy = y0 < y1 ? 1 : -1;
		var err = dx - dy;
		while (true)
		{
			DrawDot(texture, x0, y0, radius);
			if (x0 == x1 && y0 == y1)
				break;
			var e2 = err * 2;
			if (e2 > -dy)
			{
				err -= dy;
				x0 += sx;
			}
			if (e2 < dx)
			{
				err += dx;
				y0 += sy;
			}
		}
	}

	private static void DrawDot(Texture2D texture, int cx, int cy, int radius)
	{
		var c = new Color32(255, 255, 255, 245);
		for (var y = cy - radius; y <= cy + radius; y++)
		for (var x = cx - radius; x <= cx + radius; x++)
		{
			if (x < 0 || y < 0 || x >= texture.width || y >= texture.height)
				continue;
			var dx = x - cx;
			var dy = y - cy;
			if (dx * dx + dy * dy <= radius * radius)
				texture.SetPixel(x, y, c);
		}
	}
}
