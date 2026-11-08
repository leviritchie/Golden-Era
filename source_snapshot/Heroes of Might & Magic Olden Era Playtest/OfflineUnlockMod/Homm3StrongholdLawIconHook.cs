using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdLawIconHook
{
	private static bool _patched;
	private static int _loggedSurfaceReplace;
	private static int _loggedRememberedSurface;
	private static int _loggedRefreshReplace;
	private static int _loggedYohFired;
	private static int _loggedNoIconKey;
	private static int _loggedImageDump;
	private static readonly Dictionary<long, string> LawIconKeyByView = new();

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafe(Harmony h, ManualLogSource log)
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
				throw new InvalidOperationException("Harmony was not initialized.");
			return;
		}

		var lawSurfacePatched = TryPatchLawViewSurfaces(h, log);
		var patched = lawSurfacePatched;

		// Audit A8 (2026-09-27): the legacy "ckj" sprite resolver type does not exist on Golden Era.
		// Stronghold law icon keys are served by the guarded central resolver prefix
		// (Homm3CustomUiIconHook.PrefixSpriteResolverCore -> Homm3StrongholdLawIconSpriteCache).
		if (patched == 0)
			log?.LogWarning("Homm3StrongholdLawIcon: no release law-view bind/refresh surfaces registered.");
		else
			log?.LogInfo("Homm3StrongholdLawIcon: " + patched + " law surface patch(es) registered; icons resolve through the central sprite resolver.");
		if (required && lawSurfacePatched == 0)
			throw new InvalidOperationException("no release law-view bind/refresh surfaces registered.");
		_patched = true;
	}

	private static int TryPatchLawViewSurfaces(Harmony h, ManualLogSource log)
	{
		var type = FindRuntimeType("Hex.Session.UI.BhFractionLawView");
		if (type == null)
		{
			log?.LogWarning("Homm3StrongholdLawIcon: surface type not found: Hex.Session.UI.BhFractionLawView");
			return 0;
		}

		var patched = 0;
		foreach (var method in GameMember.FindMethods(type, typeof(void), new Type[] { null, null }, GameSymbols.LawIcon.FractionLawViewBind))
		{
			if (!MatchesMethodSymbolHint(method, GameSymbols.LawIcon.FractionLawViewBind))
				continue;
			if (!IsLawViewBindCandidate(method))
				continue;
			if (PatchLawViewSurface(h, log, method, nameof(PostfixBhFractionLawViewBind)))
				patched++;
			break;
		}

		foreach (var method in GameMember.FindMethods(type, typeof(void), Type.EmptyTypes, GameSymbols.LawIcon.FractionLawViewRefresh))
		{
			if (!MatchesMethodSymbolHint(method, GameSymbols.LawIcon.FractionLawViewRefresh))
				continue;
			if (!IsLawViewRefreshCandidate(method))
				continue;
			if (PatchLawViewSurface(h, log, method, nameof(PostfixBhFractionLawViewRefresh)))
				patched++;
			break;
		}

		return patched;
	}

	private static bool IsLawViewBindCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != 2)
			return false;
		return IsLawSideType(parameters[0].ParameterType)
		       && IsFractionLawRuntimeType(parameters[1].ParameterType);
	}

	private static bool IsLawViewRefreshCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.GetParameters().Length != 0)
			return false;
		if (method.Name.StartsWith("On", StringComparison.Ordinal))
			return false;
		return true;
	}

	private static bool IsLawSideType(Type type)
	{
		var name = type?.Name;
		var fullName = type?.FullName;
		return string.Equals(name, "dtj", StringComparison.Ordinal)
		       || string.Equals(name, "Object1PublicSiObFrObccSiLiObcc1Unique", StringComparison.Ordinal)
		       || string.Equals(fullName, "Object1PublicSiObFrObccSiLiObcc1Unique", StringComparison.Ordinal);
	}

	private static bool IsFractionLawRuntimeType(Type type)
	{
		var name = type?.Name;
		var fullName = type?.FullName;
		return string.Equals(name, "dqp", StringComparison.Ordinal)
		       || string.Equals(name, "ObjectPublicDaccObLicc1QuObSt1Unique", StringComparison.Ordinal)
		       || string.Equals(fullName, "ObjectPublicDaccObLicc1QuObSt1Unique", StringComparison.Ordinal);
	}

	private static bool MatchesMethodSymbolHint(MethodInfo method, GameSymbols.MethodSymbol symbol)
	{
		if (method == null || symbol.NameHints == null)
			return false;
		foreach (var hint in symbol.NameHints)
		{
			if (!string.IsNullOrEmpty(hint) && string.Equals(method.Name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool PatchLawViewSurface(Harmony h, ManualLogSource log, MethodInfo selected, string postfixName)
	{
		try
		{
			var postfix = typeof(Homm3StrongholdLawIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3StrongholdLawIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
				return false;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			log?.LogInfo("Homm3StrongholdLawIcon: surface postfix registered on " + FormatMethod(selected) + ".");
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3StrongholdLawIcon: surface patch failed for " + FormatMethod(selected) + ": " + ex.Message);
			return false;
		}
	}

	private static int PatchByShape(Harmony h, ManualLogSource log, string typeName, string methodName, int parameterCount, string postfixName)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3StrongholdLawIcon: surface type not found: " + typeName);
				return 0;
			}
			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name == methodName && method.GetParameters().Length == parameterCount)
				{
					selected = method;
					break;
				}
			}
			if (selected == null)
			{
				log?.LogWarning("Homm3StrongholdLawIcon: surface method not found: " + typeName + "." + methodName + "/" + parameterCount);
				return 0;
			}
			var postfix = typeof(Homm3StrongholdLawIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3StrongholdLawIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			log?.LogInfo("Homm3StrongholdLawIcon: surface postfix registered on " + FormatMethod(selected) + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3StrongholdLawIcon: surface patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
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
				type = asm.GetType(fullName, throwOnError: false);
				if (type != null)
					return type;
			}
			catch { }
		}
		return null;
	}

	private static void PostfixBhFractionLawViewBind(object __instance, object[] __args)
	{
		var law = __args != null && __args.Length > 1 ? __args[1] : null;
		LogYohFired(__instance, law);
		TryApplyLawSurface(__instance, law, "BhFractionLawView.bind");
	}

	private static void PostfixBhFractionLawViewRefresh(object __instance)
	{
		RefreshRememberedLawSurface(__instance, "BhFractionLawView.refresh");
	}

	private static void TryApplyLawSurface(object view, object law, string source)
	{
		if (view == null || law == null)
			return;
		try
		{
			var iconKey = ResolveLawIconKey(law);
			if (iconKey == null)
			{
				LogNoIconKey(source, view, law);
				return;
			}
			if (!Homm3CustomUiIconHook.TryResolveSprite(iconKey, out var sprite) || !sprite)
			{
				Plugin.LogSource?.LogWarning("Homm3StrongholdLawIcon: iconKey='" + iconKey + "' resolved but PNG sprite load failed.");
				return;
			}
			RememberLawSurface(view, iconKey, source);
			var image = FindIconImage(view);
			if (image == null)
			{
				DumpImageTree(view, source + ".noImage");
				return;
			}
			ApplySpriteToImage(image, sprite);
			DumpImageTree(view, source + ".afterApply");
			LogSurfaceReplace(source, iconKey, sprite, image);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3StrongholdLawIcon: law surface " + source + " failed: " + ex.Message);
		}
	}

	private static void RefreshRememberedLawSurface(object view, string source)
	{
		if (view == null)
			return;
		try
		{
			if (!LawIconKeyByView.TryGetValue(Homm3DirectStateIdentity.ResolveKeyOrZero(view), out var iconKey) || string.IsNullOrWhiteSpace(iconKey))
				return;
			if (!Homm3CustomUiIconHook.TryResolveSprite(iconKey, out var sprite) || !sprite)
				return;
			var image = FindIconImage(view);
			if (image == null)
				return;
			if (image.sprite == sprite && image.overrideSprite == sprite && image.enabled)
				return;
			ApplySpriteToImage(image, sprite);
			LogRefreshReplace(source, iconKey, sprite, image);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3StrongholdLawIcon: remembered law surface " + source + " failed: " + ex.Message);
		}
	}

	private static string ResolveLawIconKey(object obj)
	{
		var seen = new HashSet<int>();
		return ResolveLawIconKey(obj, seen, 0);
	}

	private static string ResolveLawIconKey(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 4)
			return null;
		var key = RuntimeHelpersGetHashCode(obj);
		if (!seen.Add(key))
			return null;

		var type = obj.GetType();
		var directIcon = TryGetStringMember(obj, type, "icon");
		if (IsLawSurfaceCustomIconKey(directIcon))
			return directIcon.Trim();

		foreach (var name in GameSymbols.LawIcon.LawConfigFields)
		{
			var nested = TryGetMemberValue(obj, type, name);
			var nestedKey = ResolveLawIconKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.LawIcon.LawConfigGetters)
		{
			var nested = TryInvokeNoArg(obj, type, name);
			var nestedKey = ResolveLawIconKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		return null;
	}

	private static bool IsLawSurfaceCustomIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var sid = key.Trim();
		return sid.StartsWith("h3_", StringComparison.Ordinal)
			|| Homm3StrongholdLawIconSpriteCache.IsStrongholdLawIconKey(sid);
	}

	private static void LogYohFired(object view, object law)
	{
		if (_loggedYohFired >= 30)
			return;
		_loggedYohFired++;
		Plugin.LogSource?.LogInfo(
			"Homm3StrongholdLawIcon: bind fired view='"
			+ DescribeObject(view)
			+ "' law='"
			+ DescribeObject(law)
			+ "' lawIcon='"
			+ DescribeIconCandidates(law)
			+ "'.");
	}

	private static void LogNoIconKey(string source, object view, object law)
	{
		if (_loggedNoIconKey >= 30)
			return;
		_loggedNoIconKey++;
		Plugin.LogSource?.LogInfo(
			"Homm3StrongholdLawIcon: no custom icon key ["
			+ source
			+ "] view='"
			+ DescribeObject(view)
			+ "' law='"
			+ DescribeObject(law)
			+ "' candidates='"
			+ DescribeIconCandidates(law)
			+ "'.");
	}

	private static string DescribeObject(object obj)
	{
		if (obj == null)
			return "null";
		var component = obj as Component;
		return (obj.GetType().FullName ?? obj.GetType().Name)
			+ "/"
			+ (component != null && component.gameObject != null ? component.gameObject.name : "?");
	}

	private static string DescribeIconCandidates(object obj)
	{
		if (obj == null)
			return "null";
		var parts = new List<string>();
		DescribeIconCandidates(obj, new HashSet<int>(), 0, parts);
		return string.Join("; ", parts);
	}

	private static void DescribeIconCandidates(object obj, HashSet<int> seen, int depth, List<string> parts)
	{
		if (obj == null || depth > 2 || parts.Count >= 18)
			return;
		var key = RuntimeHelpersGetHashCode(obj);
		if (!seen.Add(key))
			return;
		var type = obj.GetType();
		var typeName = type.FullName ?? type.Name;
		foreach (var name in new[] { "sid", "id", "icon", "ccep", "chvf", "cnpl", "cobp", "ccah", "cnlk", "cnxn", "chrm", "cnis", "cnuv", "cbxu", "chpa", "cgsu", "cmys", "ccbx", "cmrv" })
		{
			var v = TryGetMemberValue(obj, type, name);
			if (v == null)
				continue;
			if (v is string s)
			{
				parts.Add(typeName + "." + name + "=" + s);
				continue;
			}
			parts.Add(typeName + "." + name + "->" + (v.GetType().FullName ?? v.GetType().Name));
			DescribeIconCandidates(v, seen, depth + 1, parts);
		}
		foreach (var name in GameSymbols.LawIcon.LawIconDiagnosticGetters)
		{
			var v = TryInvokeNoArg(obj, type, name);
			if (v == null)
				continue;
			parts.Add(typeName + "." + name + "()->" + (v.GetType().FullName ?? v.GetType().Name));
			DescribeIconCandidates(v, seen, depth + 1, parts);
		}
	}

	private static string TryGetStringMember(object obj, Type type, string name)
	{
		var v = TryGetMemberValue(obj, type, name);
		return v as string;
	}

	private static object TryGetMemberValue(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var f = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (f != null)
				return f.GetValue(obj);
		}
		catch { }
		try
		{
			var p = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (p != null)
				return p.GetValue(obj);
		}
		catch { }
		try
		{
			var getter = type.GetMethod("get_" + name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
			if (getter != null)
				return getter.Invoke(obj, Array.Empty<object>());
		}
		catch { }
		return null;
	}

	private static object TryInvokeNoArg(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var m = type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
			return m != null ? m.Invoke(obj, Array.Empty<object>()) : null;
		}
		catch { return null; }
	}

	private static Image FindIconImage(object view)
	{
		if (view == null)
			return null;
		var image = TryGetMemberValue(view, view.GetType(), "icon") as Image;
		if (image != null)
			return image;
		return view is Component c ? c.GetComponentInChildren<Image>(true) : null;
	}

	private static void ApplySpriteToImage(Image image, Sprite sprite)
	{
		if (image == null || !sprite)
			return;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = Color.white;
		if (image.gameObject != null)
			image.gameObject.SetActive(true);
	}

	private static void RememberLawSurface(object view, string iconKey, string source)
	{
		if (view == null || string.IsNullOrWhiteSpace(iconKey))
			return;
		LawIconKeyByView[Homm3DirectStateIdentity.ResolveKeyOrZero(view)] = iconKey.Trim();
		if (_loggedRememberedSurface >= 20)
			return;
		_loggedRememberedSurface++;
		var component = view as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3StrongholdLawIcon: remembered surface ["
			+ source
			+ "] iconKey='"
			+ iconKey
			+ "' type='"
			+ (view.GetType().FullName ?? view.GetType().Name)
			+ "' name='"
			+ (component != null && component.gameObject != null ? component.gameObject.name : "?")
			+ "'.");
	}

	private static void DumpImageTree(object view, string source)
	{
		if (_loggedImageDump >= 8)
			return;
		var root = view as Component;
		if (root == null)
			return;
		_loggedImageDump++;
		try
		{
			var images = root.GetComponentsInChildren<Image>(true);
			var count = 0;
			foreach (var img in images)
			{
				if (img == null || count >= 20)
					continue;
				count++;
				Plugin.LogSource?.LogInfo(
					"Homm3StrongholdLawIcon diag image ["
					+ source
					+ "] name='"
					+ (img.gameObject ? img.gameObject.name : "?")
					+ "' enabled="
					+ img.enabled
					+ " active="
					+ (img.gameObject && img.gameObject.activeInHierarchy)
					+ " sprite='"
					+ (img.sprite ? img.sprite.name : "?")
					+ "' override='"
					+ (img.overrideSprite ? img.overrideSprite.name : "?")
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3StrongholdLawIcon: image dump failed: " + ex.Message);
		}
	}

	private static int RuntimeHelpersGetHashCode(object obj)
	{
		return obj == null ? 0 : System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
	}

	private static void LogSurfaceReplace(string source, string iconKey, Sprite sprite, Image image)
	{
		if (_loggedSurfaceReplace >= 40)
			return;
		_loggedSurfaceReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3StrongholdLawIcon: surface replaced ["
			+ source
			+ "] iconKey='"
			+ iconKey
			+ "' image='"
			+ (image && image.gameObject ? image.gameObject.name : "?")
			+ "' sprite='"
			+ (sprite ? sprite.name : "?")
			+ "' override='"
			+ (image && image.overrideSprite ? image.overrideSprite.name : "?")
			+ "'.");
	}

	private static void LogRefreshReplace(string source, string iconKey, Sprite sprite, Image image)
	{
		if (_loggedRefreshReplace >= 40)
			return;
		_loggedRefreshReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3StrongholdLawIcon: refresh replaced ["
			+ source
			+ "] iconKey='"
			+ iconKey
			+ "' image='"
			+ (image && image.gameObject ? image.gameObject.name : "?")
			+ "' sprite='"
			+ (sprite ? sprite.name : "?")
			+ "' override='"
			+ (image && image.overrideSprite ? image.overrideSprite.name : "?")
			+ "'.");
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "(unknown)";
		try
		{
			var ps = method.GetParameters();
			var args = "";
			for (var i = 0; i < ps.Length; i++)
			{
				if (i > 0)
					args += ", ";
				args += ps[i].ParameterType.Name + " " + ps[i].Name;
			}
			return method.DeclaringType?.FullName + "." + method.Name + "(" + args + ")";
		}
		catch
		{
			return method.Name;
		}
	}
}
