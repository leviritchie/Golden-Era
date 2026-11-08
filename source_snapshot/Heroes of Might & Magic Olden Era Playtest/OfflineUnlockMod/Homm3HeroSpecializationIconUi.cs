using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Shared hero specialization icon resolution/application for Quick Play, summary cards, and hero profile UI.
/// </summary>
internal static class Homm3HeroSpecializationIconUi
{
	private static readonly string[] SpecializationImageFieldNames =
	{
		"specializationIcon",
		"icon",
	};

	private static readonly string[] SpecializationViewFieldNames =
	{
		"specializationView",
	};

	internal static bool TryResolveIconKey(object heroConfig, string heroSid, out string iconKey)
	{
		iconKey = null;
		var specialization = TryGetFirstMemberValue(heroConfig, GameSymbols.CustomGame.HeroSpecializationObjectFields);
		foreach (var specSid in EnumerateHeroSpecializationSidCandidates(specialization, heroConfig, heroSid))
		{
			if (!string.IsNullOrWhiteSpace(specSid)
			    && Homm3HeroSpecializationIconSpriteCache.TryGetIconKeyForSpecSid(specSid.Trim(), out iconKey)
			    && !string.IsNullOrWhiteSpace(iconKey))
				return true;
		}

		var directIconKey = FirstNonEmpty(specialization, GameSymbols.CustomGame.HeroSpecializationIconFields);
		if (!string.IsNullOrWhiteSpace(directIconKey) && directIconKey != "?")
		{
			iconKey = directIconKey.Trim();
			return true;
		}

		if (!GameBuild.IsGolden)
		{
			// Build 25672315: Hero.specialization is a HeroSpecialization (sid + private SpecializationConfig) and
			// icon exists only on Hex.Configs.SpecializationConfig, one hop further.
			var configIconKey = FirstNonEmpty(
				FindSpecializationConfig(specialization) ?? FindSpecializationConfig(heroConfig),
				"icon");
			if (!string.IsNullOrWhiteSpace(configIconKey))
			{
				iconKey = configIconKey;
				return true;
			}
		}
		return false;
	}

	private const string SpecializationConfigTypeName = "Hex.Configs.SpecializationConfig";

	// The SpecializationConfig itself, or the first non-null SpecializationConfig-typed member of obj
	// (interop field properties before native-getter prop_ properties).
	private static object FindSpecializationConfig(object obj)
	{
		if (obj == null || obj is string)
			return null;
		if (string.Equals(obj.GetType().FullName, SpecializationConfigTypeName, StringComparison.Ordinal))
			return obj;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var pass = 0; pass < 2; pass++)
		{
			for (var type = obj.GetType(); type != null; type = type.BaseType)
			{
				PropertyInfo[] props;
				try { props = type.GetProperties(flags | BindingFlags.DeclaredOnly); }
				catch { continue; }
				foreach (var prop in props)
				{
					if (prop == null || !prop.CanRead || prop.GetIndexParameters().Length != 0)
						continue;
					if (!string.Equals(prop.PropertyType.FullName, SpecializationConfigTypeName, StringComparison.Ordinal))
						continue;
					var isNativeGetter = prop.Name.StartsWith("prop_", StringComparison.Ordinal);
					if (isNativeGetter != (pass == 1))
						continue;
					try
					{
						var value = prop.GetValue(obj);
						if (value != null)
							return value;
					}
					catch { }
				}
			}
		}
		return null;
	}

	internal static bool TryApplyForHeroConfig(object heroConfig, string heroSid, object rootView, string surface)
	{
		if (rootView == null)
			return false;
		if (string.IsNullOrWhiteSpace(heroSid))
			heroSid = TryGetHeroSidFromConfig(heroConfig);
		if (!TryResolveIconKey(heroConfig, heroSid, out var iconKey))
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"specialization-key-miss",
				"source='" + (surface ?? "?") + "' hero='" + (heroSid ?? "?") + "' view='" + DescribeView(rootView) + "'",
				limit: 48);
			return false;
		}
		if (!Homm3HeroSpecializationIconSpriteCache.TryResolveSprite(iconKey, out var sprite) || !sprite)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"specialization-sprite-miss",
				"source='" + (surface ?? "?") + "' hero='" + (heroSid ?? "?") + "' key='" + iconKey + "'",
				limit: 48);
			return false;
		}

		var applied = false;
		foreach (var image in EnumerateSpecializationImages(rootView))
		{
			if (image == null)
				continue;
			ApplySpriteToImage(image, sprite);
			Homm3UiCardDiagnostics.Log(
				surface,
				"specialization-icon-applied",
				"source='" + (surface ?? "?") + "' hero='" + (heroSid ?? "?") + "' key='" + iconKey + "' sprite='" + sprite.name + "' image='" + image.name + "'",
				limit: 96);
			applied = true;
		}
		if (!applied)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"specialization-image-miss",
				"source='" + (surface ?? "?") + "' hero='" + (heroSid ?? "?") + "' key='" + iconKey + "' view='" + DescribeView(rootView) + "'",
				limit: 48);
		}
		return applied;
	}

	internal static void TryApplyForHeroConfigTree(object heroConfig, string heroSid, object rootView, string surface)
	{
		if (rootView == null)
			return;
		TryApplyForHeroConfig(heroConfig, heroSid, rootView, surface);
		foreach (var fieldName in SpecializationViewFieldNames)
		{
			var nested = TryGetMemberValue(rootView, fieldName);
			if (nested == null || ReferenceEquals(nested, rootView))
				continue;
			TryApplyForHeroConfig(heroConfig, heroSid, nested, surface + "." + fieldName);
		}
	}

	internal static bool TryApplyForSpecializationView(object view, object heroPayload, string source)
	{
		if (view == null)
			return false;
		var sessionHero = TryGetFirstMemberValue(heroPayload, new[] { "bwdz", "cmvd", "hero", "Hero" });
		var heroConfig = ResolveHeroConfig(heroPayload)
		                 ?? ResolveHeroConfig(sessionHero)
		                 ?? sessionHero
		                 ?? heroPayload;
		var heroSid = TryGetHeroSidFromConfig(heroConfig) ?? TryGetHeroSidFromConfig(heroPayload);
		var config = TryGetFirstMemberValue(view, GameSymbols.HeroProfile.SpecializationConfigFields);
		if (config == null && heroPayload != null)
			config = TryGetFirstMemberValue(heroPayload, new[] { "bwdy", "cmvc", "specialization", "specializationConfig" });
		if (!TryResolveIconKey(config ?? heroConfig, heroSid, out var iconKey))
			iconKey = ResolveIconKeyFromSpecializationView(view, heroSid);
		if (string.IsNullOrWhiteSpace(iconKey))
			return false;
		if (!Homm3HeroSpecializationIconSpriteCache.TryResolveSprite(iconKey, out var sprite) || !sprite)
			return false;

		var applied = false;
		foreach (var image in EnumerateSpecializationImages(view))
		{
			if (image == null)
				continue;
			ApplySpriteToImage(image, sprite);
			Homm3UiCardDiagnostics.Log(
				"inventory-specialization-icon",
				"icon-applied",
				"source='" + (source ?? "?") + "' hero='" + (heroSid ?? "?") + "' key='" + iconKey + "' sprite='" + sprite.name + "' image='" + image.name + "' view='" + DescribeView(view) + "'",
				limit: 96);
			applied = true;
		}
		return applied;
	}

	private static string ResolveIconKeyFromSpecializationView(object view, string heroSid)
	{
		var config = TryGetFirstMemberValue(view, GameSymbols.HeroProfile.SpecializationConfigFields);
		var directIcon = TryGetFirstStringMember(config, new[] { "icon", "cmyj" });
		if (!string.IsNullOrWhiteSpace(directIcon) && directIcon != "?")
			return directIcon.Trim();
		var specSid = TryGetFirstStringMember(config, new[] { "id", "sid" });
		if (!string.IsNullOrWhiteSpace(specSid)
		    && Homm3HeroSpecializationIconSpriteCache.TryGetIconKeyForSpecSid(specSid.Trim(), out var cachedIcon)
		    && !string.IsNullOrWhiteSpace(cachedIcon))
			return cachedIcon.Trim();
		if (!string.IsNullOrWhiteSpace(heroSid)
		    && Homm3HeroSpecializationIconSpriteCache.TryGetIconKeyForSpecSid(heroSid.Trim() + "_specialization", out cachedIcon)
		    && !string.IsNullOrWhiteSpace(cachedIcon))
			return cachedIcon.Trim();
		return null;
	}

	private static IEnumerable<Image> EnumerateSpecializationImages(object view)
	{
		if (view == null)
			yield break;

		var seen = new HashSet<int>();
		foreach (var fieldName in SpecializationImageFieldNames)
		{
			if (TryGetMemberValue(view, fieldName) is Image direct && direct && seen.Add(GetUnityInstanceId(direct)))
				yield return direct;
		}

		if (view is Component component && component)
		{
			var named = FindChildImageByName(component.transform, "specializationIcon");
			if (named && seen.Add(GetUnityInstanceId(named)))
				yield return named;
		}
	}

	private static Image FindChildImageByName(Transform root, string imageName)
	{
		if (!root || string.IsNullOrWhiteSpace(imageName))
			return null;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image && image.gameObject && string.Equals(image.gameObject.name, imageName, StringComparison.OrdinalIgnoreCase))
				return image;
		}
		return null;
	}

	private static IEnumerable<string> EnumerateHeroSpecializationSidCandidates(object specialization, object heroConfig, string heroSid)
	{
		yield return FirstNonEmpty(specialization, GameSymbols.CustomGame.HeroSpecializationSidFields);
		yield return FirstNonEmpty(heroConfig, GameSymbols.CustomGame.HeroSpecializationConfigSidFields);
		var formatted = FormatSimple(specialization);
		if (LooksLikeSpecializationSid(formatted))
			yield return formatted;
		if (!string.IsNullOrWhiteSpace(heroSid) && heroSid != "?")
			yield return heroSid.Trim() + "_specialization";
	}

	private static bool LooksLikeSpecializationSid(string value)
	{
		if (string.IsNullOrWhiteSpace(value) || value == "?")
			return false;
		var trimmed = value.Trim();
		return trimmed.EndsWith("_specialization", StringComparison.Ordinal)
		       && trimmed.IndexOf('.', StringComparison.Ordinal) < 0
		       && trimmed.IndexOf(' ', StringComparison.Ordinal) < 0;
	}

	private static string FormatSimple(object value)
	{
		if (value == null)
			return null;
		var text = value.ToString();
		if (string.IsNullOrWhiteSpace(text))
			return null;
		var open = text.IndexOf('(');
		if (open > 0)
			text = text.Substring(0, open);
		return text.Trim();
	}

	private static object ResolveHeroConfig(object hero)
	{
		if (hero == null)
			return null;
		if (hero.GetType().FullName == "Hex.Configs.HeroConfig")
			return hero;

		var seen = new HashSet<int>();
		return ResolveHeroConfig(hero, seen, 0);
	}

	private static object ResolveHeroConfig(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 4)
			return null;
		if (obj.GetType().FullName == "Hex.Configs.HeroConfig")
			return obj;
		var key = obj.GetHashCode();
		if (!seen.Add(key))
			return null;

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(obj, name);
			var config = ResolveHeroConfig(nested, seen, depth + 1);
			if (config != null)
				return config;
		}
		foreach (var name in GameSymbols.HeroProfile.HeroConfigGetters)
		{
			var nested = TryInvokeNoArg(obj, name);
			var config = ResolveHeroConfig(nested, seen, depth + 1);
			if (config != null)
				return config;
		}
		return null;
	}

	internal static string TryGetHeroSidFromConfig(object heroConfig)
	{
		if (heroConfig == null)
			return null;

		var sid = FirstNonEmpty(heroConfig, GameSymbols.HeroProfile.HeroConfigFields)
		          ?? FirstNonEmpty(heroConfig, GameSymbols.ImportVisuals.SessionHeroConfigFields)
		          ?? FirstNonEmpty(heroConfig, "id", "sid", "heroSid", "configSid", "name", "title", "icon", "portrait");
		if (Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(sid, out var portraitKey))
			return portraitKey;
		if (Homm3CustomFactionRegistry.TryGetHeroSidFromDisplayLabel(sid, out var displayHeroSid))
			return displayHeroSid;

		var config = TryGetMemberValue(heroConfig, "config") ?? TryGetMemberValue(heroConfig, "heroConfig");
		if (config != null && !ReferenceEquals(config, heroConfig))
			return TryGetHeroSidFromConfig(config);

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(heroConfig, name);
			var nestedSid = TryGetHeroSidFromConfig(nested);
			if (!string.IsNullOrWhiteSpace(nestedSid))
				return nestedSid;
		}

		return null;
	}

	private static string FirstNonEmpty(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = TryGetStringMember(obj, name);
			if (!string.IsNullOrWhiteSpace(value) && value != "?")
				return value.Trim();
		}
		return null;
	}

	private static string TryGetFirstStringMember(object obj, IEnumerable<string> names)
	{
		if (obj == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = TryGetStringMember(obj, name);
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	private static object TryGetFirstMemberValue(object obj, IEnumerable<string> names)
	{
		if (obj == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = TryGetMemberValue(obj, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetMemberValue(object obj, string name)
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

			try
			{
				var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj);
			}
			catch { }
		}
		return null;
	}

	private static string TryGetStringMember(object obj, string name)
	{
		return TryGetMemberValue(obj, name) as string;
	}

	private static object TryInvokeNoArg(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null)
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch { return null; }
		}
		return null;
	}

	private static void ApplySpriteToImage(Image image, Sprite sprite)
	{
		if (!image || !sprite)
			return;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = Color.white;
		if (image.gameObject != null)
			image.gameObject.SetActive(true);
	}

	private static int GetUnityInstanceId(UnityEngine.Object obj)
	{
		return obj ? obj.GetInstanceID() : 0;
	}

	private static string DescribeView(object view)
	{
		if (view == null)
			return "(null)";
		return view is Component component && component
			? component.gameObject.name + "/" + (view.GetType().FullName ?? view.GetType().Name)
			: view.GetType().FullName ?? view.GetType().Name;
	}
}
