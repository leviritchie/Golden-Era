using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using TMPro;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Fixes the Stronghold hero class label and small class icon on hero inventory/stats profile panels.
/// The generated data is correct, but this profile surface can bind through faction/class fallback keys
/// that are absent from the vanilla sprite/loc registries.
/// </summary>
internal static class Homm3HeroClassProfileHook
{
	private static bool _patched;
	private static int _loggedApply;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		var patched = 0;
		foreach (var methodName in GameSymbols.HeroProfile.DataViewInit.NameHints)
			patched += PatchByName(h, log, "Hex.Session.UI.HeroProfile.BhHeroDataView", methodName, nameof(PostfixHeroDataViewBind));
		foreach (var methodName in GameSymbols.HeroProfile.DataViewRefresh.NameHints)
			patched += PatchByName(h, log, "Hex.Session.UI.HeroProfile.BhHeroDataView", methodName, nameof(PostfixHeroDataViewRefresh));
		// Audit A8 (2026-09-27): the window lives at Hex.Session.HeroProfile.BhHeroProfileWindow on
		// Golden Era; the hard-coded Hex.Session.UI name logged "type not found" every start. Resolve
		// through GameSymbols. The shown-method hints are still unpinned there (audit B7), so a miss
		// is a visible warning rather than a Debug line.
		var profileWindowTypeName = ResolveFirstRuntimeTypeName(GameSymbols.HeroProfile.ProfileWindowTypeHints);
		var profileWindowPatched = 0;
		if (profileWindowTypeName == null)
			log?.LogWarning("Homm3HeroClassProfile: hero profile window type not found: " + string.Join("/", GameSymbols.HeroProfile.ProfileWindowTypeHints));
		else
		{
			foreach (var methodName in GameSymbols.HeroProfile.ProfileWindowShown.NameHints)
				profileWindowPatched += PatchByName(h, log, profileWindowTypeName, methodName, nameof(PostfixHeroProfileWindowShown));
			if (profileWindowPatched == 0)
				log?.LogWarning("Homm3HeroClassProfile: no " + profileWindowTypeName + " shown method named "
					+ string.Join("/", GameSymbols.HeroProfile.ProfileWindowShown.NameHints) + " on this build; profile-window refresh not patched.");
		}
		patched += profileWindowPatched;
		patched += PatchByName(h, log, "Hex.UI.HeroView.BhSubClassView", "Method_Public_Void_Hero_0", nameof(PostfixSubClassViewBind));
		foreach (var methodName in GameSymbols.ImportVisuals.SummaryCardHeroBind.NameHints)
			patched += PatchByName(h, log, "Hex.Pick.BhSummaryCard", methodName, nameof(PostfixHeroConfigArg0Bind));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhHeroAdditionalInfo", "Show", nameof(PostfixHeroConfigArg0Bind));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhHeroAdditionalInfo", "Init", nameof(PostfixHeroConfigArg0Bind));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhHeroAdditionalInfo", "qpf", nameof(PostfixHeroConfigArg0Bind));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhHeroAdditionalInfo", "qpg", nameof(PostfixHeroConfigArg0Bind));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhHeroAdditionalInfo", "qph", nameof(PostfixHeroConfigArg0Bind));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhLobbyPopupHeroElement", "Init", nameof(PostfixLobbyHeroElementBind));

		if (patched == 0)
			log?.LogWarning("Homm3HeroClassProfile: no hero data view patches registered.");
		else
			log?.LogInfo("Homm3HeroClassProfile: " + patched + " hero class profile patch(es) registered.");

		_patched = true;
	}

	private static int PatchByName(Harmony h, ManualLogSource log, string typeName, string methodName, string postfixName)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3HeroClassProfile: type not found: " + typeName);
				return 0;
			}

			var method = type.GetMethod(methodName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
			if (method == null)
			{
				log?.LogDebug("Homm3HeroClassProfile: method not found: " + typeName + "." + methodName);
				return 0;
			}

			var postfix = typeof(Homm3HeroClassProfileHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
			{
				log?.LogWarning("Homm3HeroClassProfile: refusing incompatible postfix for " + (method.DeclaringType?.FullName ?? typeName) + "." + method.Name + ": " + reason);
				return 0;
			}
			h.Patch(method, postfix: new HarmonyMethod(postfix));
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3HeroClassProfile: patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static string ResolveFirstRuntimeTypeName(string[] typeNames)
	{
		foreach (var typeName in typeNames)
		{
			if (!string.IsNullOrWhiteSpace(typeName) && FindRuntimeType(typeName) != null)
				return typeName;
		}
		return null;
	}

	private static Type FindRuntimeType(string fullName)
	{
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
		return null;
	}

	private static void PostfixHeroDataViewBind(object __instance, object[] __args)
	{
		var hero = __args != null && __args.Length > 0 ? __args[0] : null;
		Apply(__instance, hero, "Init");
	}

	private static void PostfixHeroDataViewRefresh(object __instance)
	{
		var hero = TryGetFirstMemberValue(__instance, GameSymbols.HeroProfile.HeroStateFields);
		Apply(__instance, hero, "refresh");
	}

	private static void PostfixHeroProfileWindowShown(object __instance, MethodBase __originalMethod)
	{
		var hero = TryGetFirstMemberValue(__instance, GameSymbols.HeroProfile.HeroStateFields);
		var source = __originalMethod != null ? __originalMethod.Name : "profile-window";
		Apply(__instance, hero, source);
		Apply(TryGetMemberValue(__instance, "heroDataView"), hero, source + ".heroDataView");
		Apply(TryGetMemberValue(__instance, "portraitView"), hero, source + ".portraitView");
	}

	private static void PostfixSubClassViewBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var hero = __args != null && __args.Length > 0 ? __args[0] : null;
		Apply(__instance, hero, __originalMethod != null ? __originalMethod.Name : "sub-class-view");
	}

	private static void PostfixHeroConfigArg0Bind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var hero = __args != null && __args.Length > 0 ? __args[0] : null;
		Apply(__instance, hero, __originalMethod != null ? __originalMethod.Name : "hero-config");
		var heroSid = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(hero);
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			hero,
			heroSid,
			__instance,
			"inventory-screen-hero-specialization");
	}

	private static void PostfixLobbyHeroElementBind(object __instance, MethodBase __originalMethod)
	{
		var hero = TryGetMemberValue(__instance, "bwve")
			?? TryGetMemberValue(__instance, "heroConfig")
			?? TryGetMemberValue(__instance, "config");
		Apply(__instance, hero, __originalMethod != null ? __originalMethod.Name : "lobby-hero-element");
	}

	private static void Apply(object view, object hero, string source)
	{
		LogBinderHit(view, hero, source);
		if (view == null || hero == null)
			return;

		try
		{
			var heroKey = ResolveStrongholdHeroKey(hero);
			if (heroKey == null)
				return;

			var config = ResolveHeroConfig(hero) as HeroConfig;
			var classType = ResolveClassType(config ?? hero);
			if (string.IsNullOrWhiteSpace(classType))
				classType = InferClassTypeFromHeroKey(heroKey);
			if (string.IsNullOrWhiteSpace(classType))
				return;

			var isMagic = string.Equals(classType.Trim(), "magic", StringComparison.OrdinalIgnoreCase);
			var label = !string.IsNullOrWhiteSpace(config?.className)
				? ToReadableClassName(config.className)
				: (isMagic ? "Magic" : "Might");
			var classIconKey = ResolveClassIconKey(heroKey, classType, config);
			if (string.IsNullOrWhiteSpace(classIconKey))
				return;

			var className = TryGetMemberValue(view, "className") as TextMeshProUGUI;
			if (className != null && className.text != label)
				className.text = label;

			var classTypeIcon = TryGetMemberValue(view, "classTypeIcon") as Image;
			var classIcon = TryGetMemberValue(view, "classIcon") as Image;
			var subClassIcon = TryResolveSubClassIconImage(view);
			if (Homm3CustomUiIconHook.TryResolveSprite(classIconKey, out var sprite) && sprite)
			{
				ApplySprite(classTypeIcon, sprite);
				ApplySprite(classIcon, sprite);
				ApplySprite(subClassIcon, sprite);
			}

			LogApply(source, heroKey, label, classIconKey);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroClassProfile: " + source + " failed: " + ex.Message);
		}
	}

	private static Image TryResolveSubClassIconImage(object view)
	{
		if (view == null)
			return null;
		var direct = TryGetMemberValue(view, "field_Private_Image_0") as Image;
		if (direct != null)
			return direct;
		var subClassView = TryGetMemberValue(view, "subClassView");
		return TryGetMemberValue(subClassView, "field_Private_Image_0") as Image;
	}

	private static string ResolveClassIconKey(string heroKey, string classType, HeroConfig config)
	{
		if (!string.IsNullOrWhiteSpace(config?.classIcon))
			return config.classIcon.Trim();
		var factionSid = TryGetFactionSidFromHeroKey(heroKey);
		if (string.IsNullOrWhiteSpace(factionSid) || string.IsNullOrWhiteSpace(classType))
			return null;
		var normalizedClassType = classType.Trim();
		if (string.Equals(normalizedClassType, "magic", StringComparison.OrdinalIgnoreCase))
			normalizedClassType = "magic";
		else if (string.Equals(normalizedClassType, "might", StringComparison.OrdinalIgnoreCase))
			normalizedClassType = "might";
		else
			return null;
		return "sub_class_" + factionSid + "_" + normalizedClassType + "_1_icon";
	}

	private static string TryGetFactionSidFromHeroKey(string heroKey)
	{
		if (string.IsNullOrWhiteSpace(heroKey))
			return null;
		var trimmed = heroKey.Trim();
		var marker = trimmed.IndexOf("_hero_", StringComparison.Ordinal);
		return marker > 0 ? trimmed.Substring(0, marker) : null;
	}

	private static void ApplySprite(Image image, UnityEngine.Sprite sprite)
	{
		if (image == null || !sprite)
			return;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = UnityEngine.Color.white;
		if (image.gameObject != null)
			image.gameObject.SetActive(true);
	}

	private static string ResolveStrongholdHeroKey(object hero)
	{
		var seen = new HashSet<int>();
		return ResolveStrongholdHeroKey(hero, seen, 0);
	}

	private static string ResolveStrongholdHeroKey(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 4)
			return null;
		var key = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
		if (!seen.Add(key))
			return null;

		foreach (var name in GameSymbols.HeroProfile.HeroConfigFields)
		{
			var s = TryGetStringMember(obj, name);
			if (IsHomm3HeroKey(s))
				return s.Trim();
		}

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(obj, name);
			var nestedKey = ResolveStrongholdHeroKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.HeroProfile.HeroConfigGetters)
		{
			var nested = TryInvokeNoArg(obj, name);
			var nestedKey = ResolveStrongholdHeroKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		return null;
	}

	private static bool IsStrongholdHeroKey(string s)
	{
		return IsHomm3HeroKey(s);
	}

	private static bool IsHomm3HeroKey(string s)
	{
		return Homm3CustomFactionRegistry.IsCustomHeroSid(s);
	}

	private static string ResolveClassType(object hero)
	{
		var seen = new HashSet<int>();
		return ResolveClassType(hero, seen, 0);
	}

	private static string ResolveClassType(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 4)
			return null;
		var key = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
		if (!seen.Add(key))
			return null;

		var direct = TryGetStringMember(obj, "classType");
		if (!string.IsNullOrWhiteSpace(direct))
			return direct.Trim();

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(obj, name);
			var classType = ResolveClassType(nested, seen, depth + 1);
			if (!string.IsNullOrWhiteSpace(classType))
				return classType;
		}

		return null;
	}

	private static object ResolveHeroConfig(object hero)
	{
		var seen = new HashSet<int>();
		return ResolveHeroConfig(hero, seen, 0);
	}

	private static object ResolveHeroConfig(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 4)
			return null;
		if (obj is HeroConfig)
			return obj;
		var key = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
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

	private static string ToReadableClassName(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return value;
		var trimmed = value.Trim();
		var last = trimmed.LastIndexOf('_');
		if (last >= 0 && last < trimmed.Length - 1)
			trimmed = trimmed.Substring(last + 1);
		return char.ToUpperInvariant(trimmed[0]) + trimmed.Substring(1).Replace('_', ' ');
	}

	private static string InferClassTypeFromHeroKey(string heroKey)
	{
		if (string.IsNullOrWhiteSpace(heroKey))
			return null;
		var parts = heroKey.Trim().Split('_');
		if (!int.TryParse(parts[parts.Length - 1], out var idx))
			return null;
		return idx >= 10 ? "magic" : "might";
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

	private static void LogApply(string source, string heroKey, string label, string donorIcon)
	{
		Homm3UiCardDiagnostics.Log(
			"inventory-screen-hero-specialization",
			"hero-specialization-applied",
			"source='" + (source ?? "?") + "' hero='" + heroKey + "' label='" + label + "' icon='" + donorIcon + "'");
		if (_loggedApply >= 12)
			return;
		_loggedApply++;
		Plugin.LogSource?.LogInfo(
			"Homm3HeroClassProfile: applied source='"
			+ source
			+ "' hero='"
			+ heroKey
			+ "' label='"
			+ label
			+ "' icon='"
			+ donorIcon
			+ "'.");
	}

	private static void LogBinderHit(object view, object hero, string source)
	{
		try
		{
			var heroKey = ResolveStrongholdHeroKey(hero);
			var config = ResolveHeroConfig(hero) as HeroConfig;
			var classType = ResolveClassType(config ?? hero);
			var classTypeIcon = TryGetMemberValue(view, "classTypeIcon") as Image;
			var classIcon = TryGetMemberValue(view, "classIcon") as Image;
			var className = TryGetMemberValue(view, "className") as TextMeshProUGUI;
			Homm3UiCardDiagnostics.Log(
				"inventory-screen-hero-specialization",
				"hero-specialization-binder-hit",
				"source='" + (source ?? "?")
				+ "' view='" + FormatObject(view)
				+ "' payload='" + FormatObject(hero)
				+ "' hero='" + (heroKey ?? "?")
				+ "' classType='" + (classType ?? "?")
				+ "' classNameText='" + (className != null ? className.text : "?")
				+ "' classTypeIcon='" + FormatImage(classTypeIcon)
				+ "' classIcon='" + FormatImage(classIcon) + "'",
				limit: 60);
		}
		catch (Exception ex)
		{
			Homm3UiCardDiagnostics.Log(
				"inventory-screen-hero-specialization",
				"hero-specialization-binder-hit-failed",
				"source='" + (source ?? "?") + "' error='" + ex.GetType().Name + ": " + ex.Message + "'",
				limit: 20);
		}
	}

	private static string FormatObject(object obj)
	{
		return obj == null ? "(null)" : obj.GetType().FullName ?? obj.GetType().Name;
	}

	private static string FormatImage(Image image)
	{
		if (image == null)
			return "(none)";
		var sprite = image.sprite ? image.sprite.name : "?";
		var overrideSprite = image.overrideSprite ? image.overrideSprite.name : "?";
		return image.name + ":sprite=" + sprite + ":override=" + overrideSprite;
	}
}
