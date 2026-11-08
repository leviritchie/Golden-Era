using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Static UI portrait swap for unit tooltip/preview cards. Sprites come from
/// <see cref="Homm3ImportPortraitSpriteCache"/> (static PNG → bundle template texture → vanilla Dungeon donor).
/// </summary>
internal static class Homm3ImportTooltipPortraitHook
{
	private static bool _patched;
	private static int _loggedReplace;
	private static int _loggedUnitImageTree;
	private static readonly Dictionary<long, string> LastCustomUnitSidByTooltip = new();

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: true);
	}

	private static void Register(Harmony h, ManualLogSource log, bool required)
	{
		if (_patched)
			return;
		if (h == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required Homm3Import tooltip portrait registration.");
			return;
		}

		try
		{
			var tooltipType = FindRuntimeType(GameSymbols.TooltipPortrait.TooltipUnitTypeHints);
			if (tooltipType == null)
			{
				if (required)
					throw new InvalidOperationException("required Homm3Import tooltip portrait type missing: " + string.Join(", ", GameSymbols.TooltipPortrait.TooltipUnitTypeHints));
				log?.LogWarning("Homm3Import tooltip portrait: BhTooltipUnit type not found.");
				_patched = true;
				return;
			}

			var patched = 0;
			var seen = new HashSet<int>();
			foreach (var method in tooltipType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				if (!IsTooltipSidSurface(method))
					continue;
				if (!seen.Add(method.MetadataToken))
					continue;
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportTooltipPortraitHook), nameof(PostfixSidSurface)));
				patched++;
				log?.LogInfo("Homm3Import tooltip portrait: patched " + FormatMethod(method) + ".");
			}

			if (required && patched < GameSymbols.TooltipPortrait.ExpectedSidSurfaceCount)
				throw new InvalidOperationException(
					"required Homm3Import tooltip portrait SID surface(s) missing: expected "
					+ GameSymbols.TooltipPortrait.ExpectedSidSurfaceCount
					+ " tooltip portrait SID surface(s), patched "
					+ patched);
			else if (!required && patched == 0)
				log?.LogWarning("Homm3Import tooltip portrait: no known BhTooltipUnit portrait method(s) patched.");

			_patched = true;
			log?.LogInfo("Homm3Import: Harmony postfix on " + patched + (required ? " required" : "") + " BhTooltipUnit portrait method(s) for HOMM3 static previews.");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogError("Homm3Import tooltip portrait hook failed: " + ex);
		}
	}

	private static void PostfixSidSurface(object __instance, object[] __args)
	{
		var sid = __args != null && __args.Length > 0 ? __args[0] as string : null;
		LogUiCardDiagnostic(
			"BhTooltipUnit.sid-surface",
			"unit-portrait-binder-hit",
			"sid='" + (sid ?? "?") + "' tooltip='" + FormatObject(__instance) + "' image='" + FormatImage(TryGetImageField(__instance, GameSymbols.TooltipPortrait.PortraitImageFields)) + "'");
		TryApply(__instance, sid, "BhTooltipUnit.sid-surface");
	}

	internal static bool TryApplyRememberedPortrait(object tooltip)
	{
		return TryApplyRememberedPortrait(tooltip, "remembered-tooltip");
	}

	internal static bool TryApplyRememberedPortrait(object tooltip, string source)
	{
		if (tooltip == null)
			return false;
		return LastCustomUnitSidByTooltip.TryGetValue(Homm3DirectStateIdentity.ResolveKeyOrZero(tooltip), out var sid)
			&& TryApply(tooltip, sid, source);
	}

	internal static bool TryApplyPortraitForSid(object tooltip, string sid)
	{
		return TryApplyPortraitForSid(tooltip, sid, "explicit-sid");
	}

	internal static bool TryApplyPortraitForSid(object tooltip, string sid, string source)
	{
		return TryApply(tooltip, sid, source);
	}

	private static bool TryApply(object tooltip, string sid, string source)
	{
		if (tooltip == null)
			return false;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(tooltip);
		var portrait = TryGetImageField(tooltip, GameSymbols.TooltipPortrait.PortraitImageFields);
		if (portrait != null)
			portrait = ResolveVisiblePortraitImage(portrait) ?? portrait;
		if (portrait == null && tooltip is Component component)
			portrait = FindPortraitImage(component);
		if (portrait == null)
		{
			LogUiCardDiagnostic(source, "unit-portrait-no-image", "sid='" + (sid ?? "?") + "' tooltip='" + FormatObject(tooltip) + "'");
			return false;
		}

		var normalizedSid = NormalizeCustomUnitSid(sid);
		if (normalizedSid == null)
		{
			LogUiCardDiagnostic(source, "unit-portrait-clear", "sid='" + (sid ?? "?") + "' image='" + portrait.name + "'");
			LastCustomUnitSidByTooltip.Remove(key);
			ClearHomm3PortraitOverride(portrait);
			return false;
		}

		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(normalizedSid, out var sprite) || sprite == null)
		{
			LogUiCardDiagnostic(source, "unit-portrait-missing-sprite", "sid='" + normalizedSid + "' image='" + portrait.name + "'");
			LastCustomUnitSidByTooltip.Remove(key);
			ClearHomm3PortraitOverride(portrait);
			return false;
		}

		portrait.sprite = sprite;
		portrait.overrideSprite = sprite;
		portrait.preserveAspect = true;
		portrait.enabled = true;
		portrait.color = Color.white;
		if (portrait.gameObject)
			portrait.gameObject.SetActive(true);
		LastCustomUnitSidByTooltip[key] = normalizedSid;
		LogUiCardDiagnostic(source, "unit-portrait-replaced", "sid='" + normalizedSid + "' sprite='" + (sprite ? sprite.name : "?") + "' image='" + portrait.name + "'");
		LogTooltipUnitImageTree(tooltip, portrait, normalizedSid, source);
		LogReplace(normalizedSid, sprite);
		return true;
	}

	private static string NormalizeCustomUnitSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var trimmed = sid.Trim();
		return Homm3CustomFactionRegistry.IsCustomUnitSid(trimmed) || trimmed.StartsWith("h3_", StringComparison.Ordinal)
			? trimmed
			: null;
	}

	private static void ClearHomm3PortraitOverride(Image image)
	{
		if (image == null)
			return;
		if (Homm3ImportPortraitSpriteCache.IsHomm3PortraitSprite(image.overrideSprite))
			image.overrideSprite = null;
		if (Homm3ImportPortraitSpriteCache.IsHomm3PortraitSprite(image.sprite))
			image.sprite = null;
	}

	private static Image FindPortraitImage(Component root)
	{
		if (!root)
			return null;
		var images = CollectImages(root.transform);
		Image fallback = null;
		Image best = null;
		var bestScore = int.MinValue;
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image)
				continue;
			var name = image.gameObject ? image.gameObject.name : image.name;
			var score = ScoreVisiblePortraitImage(image, name);
			if (score > bestScore)
			{
				best = image;
				bestScore = score;
			}
			fallback ??= image;
		}
		if (bestScore > int.MinValue)
			return best;
		return fallback;
	}

	private static Image ResolveVisiblePortraitImage(Image serializedPortrait)
	{
		if (!serializedPortrait)
			return null;
		var name = serializedPortrait.gameObject ? serializedPortrait.gameObject.name : serializedPortrait.name;
		if (LooksLikeVisiblePortraitImage(serializedPortrait, name))
			return serializedPortrait;
		if (string.IsNullOrEmpty(name) || name.IndexOf("mask", StringComparison.OrdinalIgnoreCase) < 0)
			return serializedPortrait;
		var images = CollectImages(serializedPortrait.transform);
		Image fallback = null;
		Image best = null;
		var bestScore = int.MinValue;
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image || image == serializedPortrait)
				continue;
			var childName = image.gameObject ? image.gameObject.name : image.name;
			var score = ScoreVisiblePortraitImage(image, childName);
			if (score > bestScore)
			{
				best = image;
				bestScore = score;
			}
			fallback ??= image;
		}
		if (bestScore > int.MinValue)
			return best;
		return fallback;
	}

	private static bool LooksLikeVisiblePortraitImage(Image image, string name)
	{
		if (!image)
			return false;
		if (string.IsNullOrEmpty(name))
			return false;
		return name.IndexOf("portrait", StringComparison.OrdinalIgnoreCase) >= 0
		       && name.IndexOf("mask", StringComparison.OrdinalIgnoreCase) < 0;
	}

	private static int ScoreVisiblePortraitImage(Image image, string name)
	{
		if (!LooksLikeVisiblePortraitImage(image, name))
			return int.MinValue;
		var score = 0;
		if (image.gameObject && image.gameObject.activeSelf)
			score += 100;
		if (image.enabled)
			score += 25;
		if (image.color.a > 0.01f)
			score += 10;
		if (string.Equals(name, "PORTRAIT", StringComparison.OrdinalIgnoreCase))
			score += 20;
		if (name.IndexOf("(1)", StringComparison.OrdinalIgnoreCase) >= 0)
			score -= 20;
		var spriteName = image.overrideSprite ? image.overrideSprite.name : image.sprite ? image.sprite.name : null;
		if (!string.IsNullOrEmpty(spriteName) && spriteName.IndexOf("unit_mask", StringComparison.OrdinalIgnoreCase) >= 0)
			score -= 80;
		return score;
	}

	private static Image[] CollectImages(Transform root)
	{
		var result = new List<Image>();
		CollectImages(root, result);
		return result.ToArray();
	}

	private static void CollectImages(Transform root, List<Image> result)
	{
		if (!root)
			return;
		var image = root.GetComponent(Il2CppType.Of<Image>())?.TryCast<Image>();
		if (image)
			result.Add(image);
		for (var i = 0; i < root.childCount; i++)
			CollectImages(root.GetChild(i), result);
	}

	private static Image TryGetImageField(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetFieldValue(obj, names[i]);
			if (value is Image image)
				return image;
		}
		return null;
	}

	private static object TryGetFieldValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { }
		}
		return null;
	}

	private static void LogTooltipUnitImageTree(object tooltip, Image selectedPortrait, string sid, string source)
	{
		var surface = ClassifyUiCardSurface(source);
		if (surface != "autobattle-preview-unit-portraits" && surface != "battle-results-unit-portraits")
			return;
		if (_loggedUnitImageTree >= 12)
			return;
		if (tooltip is not Component component || !component)
			return;
		_loggedUnitImageTree++;
		var selectedPath = selectedPortrait ? GetTransformPath(selectedPortrait.transform, component.transform) : "(none)";
		Homm3UiCardDiagnostics.Log(
			surface,
			"unit-portrait-image-tree",
			"source='" + (source ?? "?")
			+ "' sid='" + (sid ?? "?")
			+ "' tooltip='" + FormatObject(tooltip)
			+ "' selected='" + selectedPath
			+ "' portraitField='" + FormatImageForTree(TryGetImageField(tooltip, GameSymbols.TooltipPortrait.PortraitImageFields), component.transform)
			+ "' ownedObjects=[" + DescribeOwnedObjects(tooltip, component.transform)
			+ "] images=[" + DescribeImages(component.transform, selectedPortrait) + "]");
	}

	private static string DescribeOwnedObjects(object owner, Transform root)
	{
		var fields = GameSymbols.TooltipPortrait.DiagnosticOwnedObjectFields;
		var parts = new List<string>();
		for (var i = 0; i < fields.Length; i++)
			parts.Add(fields[i] + "=" + FormatGameObjectField(owner, fields[i], root));
		return string.Join(" | ", parts);
	}

	private static string DescribeImages(Transform root, Image selectedPortrait)
	{
		var images = CollectImages(root);
		var parts = new List<string>();
		for (var i = 0; i < images.Length && i < 18; i++)
			parts.Add(FormatImageForTree(images[i], root, images[i] == selectedPortrait));
		if (images.Length > 18)
			parts.Add("...+" + (images.Length - 18));
		return string.Join(" | ", parts);
	}

	private static string FormatGameObjectField(object owner, string fieldName, Transform root)
	{
		var value = TryGetFieldValue(owner, fieldName);
		if (value is not GameObject go || !go)
			return "(none)";
		return GetTransformPath(go.transform, root)
		       + ":activeSelf=" + SafeBool(() => go.activeSelf)
		       + ":activeInHierarchy=" + SafeBool(() => go.activeInHierarchy)
		       + ":sibling=" + SafeInt(() => go.transform.GetSiblingIndex());
	}

	private static string FormatImageForTree(Image image, Transform root, bool selected = false)
	{
		if (!image)
			return "(none)";
		var go = image.gameObject;
		var rect = image.rectTransform ? image.rectTransform.rect : default;
		var mask = go ? go.GetComponent(Il2CppType.Of<Mask>())?.TryCast<Mask>() : null;
		var rectMask = go ? go.GetComponent(Il2CppType.Of<RectMask2D>())?.TryCast<RectMask2D>() : null;
		return (selected ? "*" : "")
		       + GetTransformPath(image.transform, root)
		       + ":sprite=" + (image.sprite ? image.sprite.name : "?")
		       + ":override=" + (image.overrideSprite ? image.overrideSprite.name : "?")
		       + ":enabled=" + SafeBool(() => image.enabled)
		       + ":activeSelf=" + SafeBool(() => go && go.activeSelf)
		       + ":activeInHierarchy=" + SafeBool(() => go && go.activeInHierarchy)
		       + ":sibling=" + SafeInt(() => image.transform.GetSiblingIndex())
		       + ":alpha=" + FormatFloat(image.color.a)
		       + ":raycast=" + SafeBool(() => image.raycastTarget)
		       + ":mask=" + (mask ? "1" : "0")
		       + ":rectMask=" + (rectMask ? "1" : "0")
		       + ":rect=" + FormatFloat(rect.width) + "x" + FormatFloat(rect.height);
	}

	private static string GetTransformPath(Transform transform, Transform root)
	{
		if (!transform)
			return "(none)";
		var parts = new List<string>();
		for (var current = transform; current; current = current.parent)
		{
			parts.Add(current.name ?? "?");
			if (root && current == root)
				break;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static string SafeBool(Func<bool> get)
	{
		try { return get() ? "1" : "0"; }
		catch { return "?"; }
	}

	private static string SafeInt(Func<int> get)
	{
		try { return get().ToString(); }
		catch { return "?"; }
	}

	private static string FormatFloat(float value)
	{
		return value.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
	}

	private static Type FindRuntimeType(string[] typeHints)
	{
		if (typeHints == null)
			return null;
		for (var i = 0; i < typeHints.Length; i++)
		{
			var fullName = typeHints[i];
			if (string.IsNullOrWhiteSpace(fullName))
				continue;
			var type = ModActions.GetHexType(fullName);
			if (type != null)
				return type;
			foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
			{
				try
				{
					type = asm.GetType(fullName, false);
					if (type != null)
						return type;
				}
				catch { }
			}
		}
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "(null)" : (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static void LogReplace(string sid, Sprite sprite)
	{
		if (_loggedReplace >= 40)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		_loggedReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import tooltip portrait: replaced portrait for sid='"
			+ sid
			+ "' with sprite='"
			+ (sprite ? sprite.name : "?")
			+ "'.");
	}

	private static void LogUiCardDiagnostic(string source, string evt, string detail)
	{
		Homm3UiCardDiagnostics.Log(ClassifyUiCardSurface(source), evt, "source='" + (source ?? "?") + "' " + detail);
	}

	private static string ClassifyUiCardSurface(string source)
	{
		if (source == null)
			return "unit-tooltip-portrait";
		if (source.IndexOf("auto", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("preview", StringComparison.OrdinalIgnoreCase) >= 0)
			return "autobattle-preview-unit-portraits";
		if (source.IndexOf("result", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("BhSimulatedBattle", StringComparison.OrdinalIgnoreCase) >= 0)
			return "battle-results-unit-portraits";
		return "unit-tooltip-portrait";
	}

	private static bool IsTooltipSidSurface(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length == 0 || parameters[0].ParameterType != typeof(string))
			return false;
		if (parameters.Length == 1)
			return true;
		if (parameters.Length != 3)
			return false;
		if (parameters[1].ParameterType == typeof(int) && parameters[2].ParameterType == typeof(bool))
			return true;
		return parameters[1].ParameterType == typeof(string) && parameters[2].ParameterType == typeof(string);
	}

	private static string FormatObject(object obj)
	{
		if (obj == null)
			return "(null)";
		if (obj is Component component)
			return component.name + "/" + obj.GetType().Name;
		return obj.GetType().Name;
	}

	private static string FormatImage(Image image)
	{
		if (!image)
			return "(none)";
		var sprite = image.sprite ? image.sprite.name : "?";
		var overrideSprite = image.overrideSprite ? image.overrideSprite.name : "?";
		return (image.name ?? "?") + ":sprite=" + sprite + ":override=" + overrideSprite;
	}
}
