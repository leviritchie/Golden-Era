using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Dialogs.View;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Supplies imported portraits at the exact native dialog-avatar bind.
/// ScDialogSlide loads avatar paths through Unity Resources, so cko catalog injection
/// cannot affect this surface. The slide prefix resolves custom settings once, and the
/// BhAvatar prefix substitutes the corresponding Sprite before the native Image bind.
/// </summary>
internal static class Homm3DialogAvatarPortraitHook
{
	private static bool _patched;
	private static Sprite[] _pendingSprites = Array.Empty<Sprite>();
	private static string[] _pendingKeys = Array.Empty<string>();
	private static int _pendingIndex;
	private static int _loggedBind;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_patched || harmony == null)
			return;

		var slideMethod = FindExactSlideAvatarBind();
		var avatarMethod = FindExactAvatarImageBind();
		if (slideMethod == null || avatarMethod == null)
		{
			throw new MissingMethodException(
				"Homm3DialogAvatarPortraitHook: exact dialog bind drifted; slide="
				+ (slideMethod == null ? "missing" : slideMethod.Name)
				+ ", avatar="
				+ (avatarMethod == null ? "missing" : avatarMethod.Name)
				+ ".");
		}

		var slidePrefix = AccessTools.Method(
			typeof(Homm3DialogAvatarPortraitHook),
			nameof(PrefixSlideAvatarBind));
		var avatarPrefix = AccessTools.Method(
			typeof(Homm3DialogAvatarPortraitHook),
			nameof(PrefixAvatarImageBind));
		var avatarPostfix = AccessTools.Method(
			typeof(Homm3DialogAvatarPortraitHook),
			nameof(PostfixAvatarImageBind));

		if (!GameMember.IsHarmonyPatchCompatible(slideMethod, slidePrefix, out var slideReason))
			throw new InvalidOperationException(
				"Homm3DialogAvatarPortraitHook: slide prefix incompatible: " + slideReason);
		if (!GameMember.IsHarmonyPatchCompatible(avatarMethod, avatarPrefix, out var avatarPrefixReason))
			throw new InvalidOperationException(
				"Homm3DialogAvatarPortraitHook: avatar prefix incompatible: " + avatarPrefixReason);
		if (!GameMember.IsHarmonyPatchCompatible(avatarMethod, avatarPostfix, out var avatarPostfixReason))
			throw new InvalidOperationException(
				"Homm3DialogAvatarPortraitHook: avatar postfix incompatible: " + avatarPostfixReason);

		harmony.Patch(slideMethod, prefix: new HarmonyMethod(slidePrefix));
		harmony.Patch(
			avatarMethod,
			prefix: new HarmonyMethod(avatarPrefix),
			postfix: new HarmonyMethod(avatarPostfix));

		_patched = true;
		log?.LogInfo(
			"Homm3DialogAvatarPortraitHook: exact native path patched: "
			+ slideMethod.DeclaringType?.FullName
			+ "."
			+ slideMethod.Name
			+ " -> "
			+ avatarMethod.DeclaringType?.FullName
			+ "."
			+ avatarMethod.Name
			+ ".");
	}

	private static MethodInfo FindExactSlideAvatarBind()
	{
		foreach (var method in typeof(ScDialogSlide).GetMethods(
			         BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method.Name != GameSymbols.DialogAvatar.SlideAvatarBindMethod)
				continue;
			var parameters = method.GetParameters();
			if (method.ReturnType == typeof(void)
			    && parameters.Length == 1
			    && parameters[0].ParameterType == typeof(DialogSlideConfig))
				return method;
		}
		return null;
	}

	private static MethodInfo FindExactAvatarImageBind()
	{
		foreach (var method in typeof(BhAvatar).GetMethods(
			         BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method.Name != GameSymbols.DialogAvatar.AvatarImageBindMethod)
				continue;
			var parameters = method.GetParameters();
			if (method.ReturnType == typeof(void)
			    && parameters.Length == 3
			    && parameters[0].ParameterType == typeof(Sprite)
			    && parameters[1].ParameterType == typeof(Vector2))
				return method;
		}
		return null;
	}

	private static void PrefixSlideAvatarBind(
		[HarmonyArgument(0)] DialogSlideConfig config)
	{
		_pendingSprites = Array.Empty<Sprite>();
		_pendingKeys = Array.Empty<string>();
		_pendingIndex = 0;

		var settings = config?.avatars;
		if (settings == null || settings.Length == 0)
			return;

		var sprites = new Sprite[settings.Length];
		var keys = new string[settings.Length];
		var hasCustom = false;
		for (var i = 0; i < settings.Length; i++)
		{
			var setting = settings[i];
			var key = setting?.icon;
			keys[i] = key;
			if (!Homm3DialogPortraitCatalog.IsCustomDialogPortraitKey(key))
				continue;
			if (!Homm3DialogPortraitCatalog.TryResolveCustomDialogPortraitSprite(key, out var sprite)
			    || !sprite)
			{
				throw new InvalidOperationException(
					"Homm3DialogAvatarPortraitHook: custom dialog sprite unresolved for '" + key + "'.");
			}
			sprites[i] = sprite;
			hasCustom = true;
		}

		if (!hasCustom)
			return;

		_pendingSprites = sprites;
		_pendingKeys = keys;
		Plugin.LogSource?.LogInfo(
			"Homm3DialogAvatarPortraitHook: prepared "
			+ settings.Length
			+ " avatar bind(s), custom="
			+ CountCustom(sprites)
			+ ".");
	}

	private static void PrefixAvatarImageBind(
		[HarmonyArgument(0)] ref Sprite sprite)
	{
		if (_pendingIndex < 0 || _pendingIndex >= _pendingSprites.Length)
			return;

		var replacement = _pendingSprites[_pendingIndex];
		if (replacement)
			sprite = replacement;
	}

	private static void PostfixAvatarImageBind(
		BhAvatar __instance,
		[HarmonyArgument(0)] Sprite sprite)
	{
		var index = _pendingIndex++;
		if (index < 0 || index >= _pendingSprites.Length)
			return;

		var expected = _pendingSprites[index];
		if (!expected)
			return;

		// Native rfu sets this same Image. Re-assign to fail closed against argument
		// marshalling drift while retaining the native sizing/animation behavior.
		if (__instance?.icon)
			__instance.icon.sprite = expected;

		if (_loggedBind++ < 24)
		{
			Plugin.LogSource?.LogInfo(
				"Homm3DialogAvatarPortraitHook: bound key='"
				+ (_pendingKeys[index] ?? "")
				+ "' requested='"
				+ (sprite ? sprite.name : "null")
				+ "' image='"
				+ (__instance?.icon && __instance.icon.sprite ? __instance.icon.sprite.name : "null")
				+ "'.");
		}
	}

	private static int CountCustom(Sprite[] sprites)
	{
		var count = 0;
		foreach (var sprite in sprites)
		{
			if (sprite)
				count++;
		}
		return count;
	}
}
