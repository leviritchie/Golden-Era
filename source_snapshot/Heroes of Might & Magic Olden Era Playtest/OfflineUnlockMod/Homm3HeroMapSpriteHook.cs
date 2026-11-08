using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Logic;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

internal static class Homm3HeroMapSpriteHook
{
	private const string VisualRootName = "homm3_hero_map_visual";
	// Audit A5 (2026-09-27): native map views (ets) cache the renderers under their root in a bep
	// List<Renderer> and set sortingLayerID on each when the selection outline toggles (every
	// frame after a new day). Destroying a mod quad that the cache captured made that loop throw
	// NullReferenceException inside native code. Mod visuals under a native hero root are
	// therefore never destroyed: they are deactivated, renamed to the parked name, unregistered
	// from the animator, and reused by the next apply. Contract:
	// tools/validate_native_hook_safety_contract.py.
	private const string ParkedVisualRootName = "homm3_hero_map_visual_parked";
	private const string EnableFlagName = "homm3_hero_map_sprite_experimental.flag";
	private const string DiagnosticFlagName = "homm3_hero_map_sprite_diagnostics.flag";
	private const string OfficialDeobfRetestFlagName = "homm3_hero_map_sprite_official_deobf_retest.flag";
	private const float FrameMs = 120f;
	private const float BillboardHeight = 1.75f;
	/// <summary>
	/// HoMM3 boat frames sit waterline-centered in the DEF; lift the adventure-map
	/// boat billboard by this fraction of <see cref="BillboardHeight"/> so the hull
	/// rides on the water instead of halfway submerged.
	/// </summary>
	private const float BoatBillboardLiftRatio = 0.25f;
	private const int WalkFramesPerFacing = 8;
	private static bool _patched;
	private static bool _animatorRegistered;
	private static bool _animatorHostAttached;
	private static Mesh _quadMesh;
	private static int _diagRemaining = 64;
	private static int _sessionDiagRemaining = 48;
	private static int _mappingDiagRemaining = 24;
	private static int _staleVisualDiagRemaining = 8;
	private static int _spriteSetRefreshDiagRemaining = 8;
	private static bool _diagnosticsOnly;
	private static readonly Dictionary<string, Homm3HeroMapSpriteSet> SpriteSetsByKey = new(StringComparer.Ordinal);
	private static Dictionary<string, string> HeroClassTypesByPortraitKey;
	private static readonly Dictionary<int, string> AppliedSpriteKeysByRootId = new();
	private static readonly Dictionary<int, GameObject> AppliedVisualsByRootId = new();
	private static readonly Dictionary<int, List<RendererState>> HiddenRendererStatesByRootId = new();
	private static readonly HashSet<int> ProcessedDrawerIds = new();
	private static readonly HashSet<int> ProcessedSessionRootIds = new();
	private static bool _allowSessionVisualShapeFallback;

	private struct RendererState
	{
		internal Renderer Renderer;
		internal bool Enabled;
		internal bool ForceRenderingOff;
		internal ShadowCastingMode ShadowCastingMode;
	}

	private struct HeroDrawerTypeCandidate
	{
		internal Type Type;
		internal int Score;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, true);
	}

	private static void Register(Harmony harmony, ManualLogSource log, bool releaseSafeReplacement)
	{
		if (_patched || harmony == null)
			return;
		_allowSessionVisualShapeFallback = !releaseSafeReplacement;
		var enabled = releaseSafeReplacement || Homm3DiagnosticFlags.IsEnabled(EnableFlagName);
		_diagnosticsOnly = !enabled && Homm3DiagnosticFlags.IsEnabled(DiagnosticFlagName);
		if (!enabled && !_diagnosticsOnly)
		{
			log?.LogInfo("Homm3HeroMapSprite: skipped; create " + EnableFlagName + " to enable replacement or " + DiagnosticFlagName + " for constructor diagnostics only.");
			return;
		}
#if OFFICIAL_DEOBF_BUILD
		if (!releaseSafeReplacement && !Homm3DiagnosticFlags.IsEnabled(OfficialDeobfRetestFlagName))
		{
			log?.LogWarning(
				"Homm3HeroMapSprite: official deobf registration skipped despite "
				+ (enabled ? EnableFlagName : DiagnosticFlagName)
				+ "; create "
				+ OfficialDeobfRetestFlagName
				+ " only after a fresh etc/session-visual trace proves this hook is safe.");
			return;
		}
#endif
		try
		{
			var patched = 0;
			var drawerType = FindHeroDrawerType();
			var drawerCtor = FindHeroDrawerConstructor(drawerType);
			if (drawerCtor != null)
			{
				harmony.Patch(drawerCtor, postfix: new HarmonyMethod(typeof(Homm3HeroMapSpriteHook), nameof(PostfixHeroDrawerCtor)));
				patched++;
				log?.LogInfo("Homm3HeroMapSprite: patched " + drawerType.FullName + " hero drawer constructor for custom HoMM3 hero map sprites; mode=" + (_diagnosticsOnly ? "diagnostics" : "replacement") + ".");
				foreach (var method in FindHeroDrawerRefreshMethods(drawerType))
				{
					harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3HeroMapSpriteHook), nameof(PostfixHeroDrawerRefresh)));
					patched++;
					log?.LogInfo("Homm3HeroMapSprite: patched " + method.DeclaringType?.FullName + "." + method.Name + " for hero drawer refresh replacement.");
				}
			}
			else
			{
				log?.LogWarning("Homm3HeroMapSprite: hero drawer constructor not found; candidates=" + DescribeConstructors(drawerType) + ".");
			}

			var sessionHeroType = FindHeroSessionType();
			foreach (var method in FindHeroSessionInitMethods(sessionHeroType))
			{
				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3HeroMapSpriteHook), nameof(PostfixHeroSessionInit)));
				patched++;
				log?.LogInfo("Homm3HeroMapSprite: patched " + method.DeclaringType?.FullName + "." + method.Name + " for adventure-map hero visual diagnostics.");
			}
			var visualSetter = FindHeroSessionVisualSetter(sessionHeroType);
			if (visualSetter != null)
			{
				harmony.Patch(visualSetter, postfix: new HarmonyMethod(typeof(Homm3HeroMapSpriteHook), nameof(PostfixHeroVisualAttached)));
				patched++;
				log?.LogInfo("Homm3HeroMapSprite: patched " + visualSetter.DeclaringType?.FullName + "." + visualSetter.Name + " for adventure-map hero visual attachment diagnostics.");
			}
			else if (sessionHeroType != null)
			{
				log?.LogWarning("Homm3HeroMapSprite: adventure-map hero visual setter not found on " + sessionHeroType.FullName + ".");
			}
			var visualGetter = FindHeroSessionVisualGetter(sessionHeroType);
			if (visualGetter != null)
			{
				harmony.Patch(visualGetter, postfix: new HarmonyMethod(typeof(Homm3HeroMapSpriteHook), nameof(PostfixHeroVisualGetter)));
				patched++;
				log?.LogInfo("Homm3HeroMapSprite: patched " + visualGetter.DeclaringType?.FullName + "." + visualGetter.Name + " for adventure-map hero visual getter diagnostics.");
			}

			_patched = true;
			log?.LogInfo("Homm3HeroMapSprite: registered " + patched + " custom HoMM3 hero map sprite patch(es).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3HeroMapSprite: registration failed: " + ex);
		}
	}

	private static Type FindHeroDrawerType()
	{
		foreach (var name in GameSymbols.HeroMap.DrawerTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.HeroMap.DrawerTypeId + "." + name, name);
			if (FindHeroDrawerConstructor(type) != null)
				return type;
		}
		return FindUniqueHeroDrawerTypeByShape();
	}

	private static Type FindUniqueHeroDrawerTypeByShape()
	{
		var candidates = new List<HeroDrawerTypeCandidate>();
		foreach (var type in GameMember.EnumerateHexTypes())
		{
			if (type == null || type.IsInterface || type.IsAbstract || type.ContainsGenericParameters)
				continue;
			if (FindHeroDrawerConstructor(type) == null)
				continue;
			candidates.Add(new HeroDrawerTypeCandidate
			{
				Type = type,
				Score = ScoreHeroDrawerType(type)
			});
		}

		if (candidates.Count == 0)
			return null;
		candidates.Sort(CompareHeroDrawerTypeCandidates);
		if (candidates.Count == 1 || candidates[0].Score > candidates[1].Score)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero drawer type name hints are stale; exact constructor fallback resolved " + DescribeHeroDrawerTypeCandidate(candidates[0]) + ".");
			return candidates[0].Type;
		}
		Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero drawer exact constructor shape is ambiguous; candidates=" + DescribeHeroDrawerTypeCandidates(candidates) + ".");
		return null;
	}

	private static int CompareHeroDrawerTypeCandidates(HeroDrawerTypeCandidate left, HeroDrawerTypeCandidate right)
	{
		var score = right.Score.CompareTo(left.Score);
		if (score != 0)
			return score;
		return string.CompareOrdinal(TypeLabel(left.Type), TypeLabel(right.Type));
	}

	private static int ScoreHeroDrawerType(Type type)
	{
		if (type == null)
			return 0;
		var score = 0;
		if (TypeMatchesAnyName(type, GameSymbols.HeroMap.DrawerTypeHints))
			score += 8;
		if (HasAnyInstanceMember(type, GameSymbols.HeroMap.HeroConfigFields))
			score += 3;
		else if (HasAnyInstanceMemberOfType(type, typeof(HeroConfig)))
			score += 2;
		if (HasAnyInstanceMember(type, GameSymbols.HeroMap.RootGameObjectProperties))
			score += 3;
		else if (HasParameterlessGameObjectMethod(type))
			score += 1;
		if (HasAnyInstanceMember(type, GameSymbols.HeroMap.DrawerHeroFields))
			score += 1;
		else if (HasAnyInstanceMemberOfType(type, typeof(Hero)))
			score += 1;
		if (HasAnyInstanceMember(type, GameSymbols.HeroMap.DrawerSessionHeroFields))
			score += 1;
		if (HasHeroDrawerRefreshShape(type))
			score += 2;
		return score;
	}

	private static bool TypeMatchesAnyName(Type type, string[] names)
	{
		if (type == null || names == null)
			return false;
		var obfuscatedName = GameMember.ReadObfuscatedName(type);
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (IsRuntimeTypeName(type, name) || string.Equals(obfuscatedName, name, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool HasAnyInstanceMemberOfType(Type type, Type expectedType)
	{
		if (type == null || expectedType == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var current = type; current != null; current = current.BaseType)
		{
			FieldInfo[] fields;
			try { fields = current.GetFields(flags | BindingFlags.DeclaredOnly); }
			catch { fields = Array.Empty<FieldInfo>(); }
			for (var i = 0; i < fields.Length; i++)
				if (!fields[i].IsStatic && GameMember.TypesEquivalent(expectedType, fields[i].FieldType))
					return true;

			PropertyInfo[] properties;
			try { properties = current.GetProperties(flags | BindingFlags.DeclaredOnly); }
			catch { properties = Array.Empty<PropertyInfo>(); }
			for (var i = 0; i < properties.Length; i++)
			{
				var property = properties[i];
				if (property.GetIndexParameters().Length == 0 && GameMember.TypesEquivalent(expectedType, property.PropertyType))
					return true;
			}
		}
		return false;
	}

	private static bool HasParameterlessGameObjectMethod(Type type)
	{
		if (type == null)
			return false;
		MethodInfo[] methods;
		try { methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic); }
		catch { return false; }
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			if (method.GetParameters().Length == 0 && GameMember.TypesEquivalent(typeof(GameObject), method.ReturnType))
				return true;
		}
		return false;
	}

	private static bool HasHeroDrawerRefreshShape(Type type)
	{
		foreach (var method in GetDeclaredInstanceMethods(type))
		{
			if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 1 && IsRuntimeTypeName(ps[0].ParameterType, "EHeroDrawerRefresh"))
				return true;
		}
		return false;
	}

	private static string DescribeHeroDrawerTypeCandidates(List<HeroDrawerTypeCandidate> candidates)
	{
		if (candidates == null || candidates.Count == 0)
			return "(none)";
		var parts = new List<string>();
		var count = Math.Min(candidates.Count, 8);
		for (var i = 0; i < count; i++)
			parts.Add(DescribeHeroDrawerTypeCandidate(candidates[i]));
		if (candidates.Count > count)
			parts.Add("...");
		return string.Join(",", parts);
	}

	private static string DescribeHeroDrawerTypeCandidate(HeroDrawerTypeCandidate candidate)
	{
		var obfuscatedName = GameMember.ReadObfuscatedName(candidate.Type);
		return TypeLabel(candidate.Type)
		       + ":score="
		       + candidate.Score
		       + (string.IsNullOrWhiteSpace(obfuscatedName) ? "" : ":obf=" + obfuscatedName);
	}

	private static string TypeLabel(Type type)
	{
		return type?.FullName ?? type?.Name ?? "?";
	}

	private static Type FindHeroSessionType()
	{
		foreach (var name in GameSymbols.HeroMap.SessionHeroTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.HeroMap.SessionHeroTypeId + "." + name, name);
			if (IsHeroSessionType(type))
				return type;
		}
		return null;
	}

	private static bool IsHeroSessionType(Type type)
	{
		if (type == null)
			return false;
		if (FindHeroSessionInitMethods(type).Length == 0)
			return false;
		return FindHeroSessionVisualSetter(type) != null
		       || FindHeroSessionVisualGetter(type) != null
		       || HasHeroSessionFieldSurface(type);
	}

	private static bool HasHeroSessionFieldSurface(Type type)
	{
		return HasAnyInstanceMember(type, GameSymbols.HeroMap.SessionHeroLogicFields)
		       && HasAnyInstanceMember(type, GameSymbols.HeroMap.SessionHeroVisualFields);
	}

	private static bool HasAnyInstanceMember(Type type, string[] names)
	{
		if (type == null || names == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var current = type; current != null; current = current.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					if (current.GetField(name, flags) != null)
						return true;
				}
				catch
				{
				}
				try
				{
					if (current.GetProperty(name, flags) != null)
						return true;
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static MethodInfo[] FindHeroSessionInitMethods(Type sessionHeroType)
	{
		if (sessionHeroType == null)
			return Array.Empty<MethodInfo>();
		var methods = GameMember.FindMethodsByNames(
			sessionHeroType,
			new[] { typeof(Hero), null },
			GameSymbols.HeroMap.SessionHeroInit);
		var result = new List<MethodInfo>();
		var seen = new HashSet<int>();
		foreach (var method in methods)
			if (method != null && seen.Add(method.MetadataToken))
				result.Add(method);
		return result.ToArray();
	}

	private static MethodInfo FindHeroSessionVisualSetter(Type sessionHeroType)
	{
		if (sessionHeroType == null)
			return null;
		foreach (var method in GameMember.FindMethodsByNames(
			         sessionHeroType,
			         new Type[] { null },
			         GameSymbols.HeroMap.SessionHeroVisualSetter))
		{
			var ps = method.GetParameters();
			if (ps.Length == 1 && IsAnyRuntimeTypeName(ps[0].ParameterType, GameSymbols.HeroMap.SessionHeroVisualTypeHints))
				return method;
		}
		return _allowSessionVisualShapeFallback ? FindUniqueHeroSessionVisualSetterByShape(sessionHeroType) : null;
	}

	private static MethodInfo FindHeroSessionVisualGetter(Type sessionHeroType)
	{
		if (sessionHeroType == null)
			return null;
		foreach (var method in GameMember.FindMethodsByNames(sessionHeroType, Type.EmptyTypes, GameSymbols.HeroMap.SessionHeroVisualGetter))
		{
			if (method.ReturnType != typeof(void) && IsAnyRuntimeTypeName(method.ReturnType, GameSymbols.HeroMap.SessionHeroVisualTypeHints))
				return method;
		}
		return _allowSessionVisualShapeFallback ? FindUniqueHeroSessionVisualGetterByShape(sessionHeroType) : null;
	}

	private static MethodInfo FindUniqueHeroSessionVisualSetterByShape(Type sessionHeroType)
	{
		var matches = new List<MethodInfo>();
		foreach (var method in GetDeclaredInstanceMethods(sessionHeroType))
		{
			if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 1 && IsAnyRuntimeTypeName(ps[0].ParameterType, GameSymbols.HeroMap.SessionHeroVisualTypeHints))
				matches.Add(method);
		}
		return SelectUniqueHeroSessionMethod(sessionHeroType, matches, GameSymbols.HeroMap.SessionHeroVisualSetter, "visual-setter");
	}

	private static MethodInfo FindUniqueHeroSessionVisualGetterByShape(Type sessionHeroType)
	{
		var matches = new List<MethodInfo>();
		foreach (var method in GetDeclaredInstanceMethods(sessionHeroType))
		{
			if (method == null || method.IsSpecialName || method.GetParameters().Length != 0)
				continue;
			if (method.ReturnType != typeof(void) && IsAnyRuntimeTypeName(method.ReturnType, GameSymbols.HeroMap.SessionHeroVisualTypeHints))
				matches.Add(method);
		}
		return SelectUniqueHeroSessionMethod(sessionHeroType, matches, GameSymbols.HeroMap.SessionHeroVisualGetter, "visual-getter");
	}

	private static MethodInfo SelectUniqueHeroSessionMethod(Type sessionHeroType, List<MethodInfo> matches, GameSymbols.MethodSymbol symbol, string role)
	{
		if (matches == null || matches.Count == 0)
			return null;
		foreach (var hint in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			foreach (var method in matches)
			{
				if (string.Equals(method.Name, hint, StringComparison.Ordinal)
				    || string.Equals(GameMember.ReadObfuscatedName(method), hint, StringComparison.Ordinal))
					return method;
			}
		}
		if (matches.Count == 1)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero session " + role + " stale hints on " + sessionHeroType.FullName + "; shape fallback resolved " + matches[0].Name + ".");
			return matches[0];
		}
		Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero session " + role + " ambiguous on " + sessionHeroType.FullName + "; candidates=" + string.Join(",", matches.ConvertAll(m => m.Name)) + ".");
		return null;
	}

	private static MethodInfo[] GetDeclaredInstanceMethods(Type type)
	{
		if (type == null)
			return Array.Empty<MethodInfo>();
		try
		{
			return type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
		}
		catch
		{
			return Array.Empty<MethodInfo>();
		}
	}

	private static ConstructorInfo FindHeroDrawerConstructor(Type drawerType)
	{
		if (drawerType == null)
			return null;
		ConstructorInfo[] constructors;
		try { constructors = drawerType.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic); }
		catch { return null; }
		foreach (var ctor in constructors)
		{
			var ps = ctor.GetParameters();
			if (ps.Length != 7)
				continue;
			if (!IsType(ps[0].ParameterType, typeof(Hero), "Hero")
			    || !IsType(ps[1].ParameterType, typeof(Vector3), "Vector3")
			    || !IsType(ps[2].ParameterType, typeof(Quaternion), "Quaternion")
			    || !IsType(ps[3].ParameterType, typeof(HeroConfig), "HeroConfig")
			    || !IsType(ps[4].ParameterType, typeof(MountConfig), "MountConfig")
			    || !IsType(ps[5].ParameterType, typeof(Transform), "Transform")
			    || !IsType(ps[6].ParameterType, typeof(float), "Single"))
				continue;
			return ctor;
		}
		return null;
	}

	private static MethodInfo FindHeroRootMethod(Type drawerType)
	{
		return GameMember.FindFirstMethod(drawerType, typeof(GameObject), Type.EmptyTypes, GameSymbols.HeroMap.RootGameObjectGetter);
	}

	private static string DescribeConstructors(Type type)
	{
		if (type == null)
			return "(null)";
		try
		{
			var parts = new List<string>();
			foreach (var ctor in type.GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				var ps = ctor.GetParameters();
				var names = new List<string>(ps.Length);
				foreach (var p in ps)
					names.Add((p.ParameterType?.FullName ?? p.ParameterType?.Name ?? "?") + " " + p.Name);
				parts.Add(".ctor(" + string.Join(", ", names) + ")");
			}
			return parts.Count == 0 ? "(none)" : string.Join(" | ", parts);
		}
		catch (Exception ex)
		{
			return "(failed: " + ex.Message + ")";
		}
	}

	private static string DescribeGameObjectMethods(Type type)
	{
		if (type == null)
			return "(null)";
		try
		{
			var parts = new List<string>();
			foreach (var m in type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
				if (m.GetParameters().Length == 0 && (m.ReturnType?.Name == "GameObject" || m.ReturnType?.FullName == "UnityEngine.GameObject"))
					parts.Add(m.Name + " returns " + (m.ReturnType?.FullName ?? m.ReturnType?.Name ?? "?"));
			return parts.Count == 0 ? "(none)" : string.Join(", ", parts);
		}
		catch (Exception ex)
		{
			return "(failed: " + ex.Message + ")";
		}
	}

	private static bool HasAnyGameObjectProperty(Type type, string[] names)
	{
		if (type == null || names == null)
			return false;
		foreach (var name in names)
		{
			try
			{
				var p = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (p != null && p.PropertyType == typeof(GameObject))
					return true;
			}
			catch
			{
			}
		}
		return false;
	}

	private static GameObject TryGetNamedGameObjectProperty(object source, string[] names)
	{
		if (source == null || names == null)
			return null;
		var type = source.GetType();
		foreach (var name in names)
		{
			try
			{
				var p = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				var value = p?.GetValue(source) as GameObject;
				if (value)
					return value;
			}
			catch
			{
			}
		}
		return null;
	}

	private static bool IsType(Type actual, Type expected, string expectedName)
	{
		if (actual == null)
			return false;
		if (actual == expected)
			return true;
		return string.Equals(actual.Name, expectedName, StringComparison.Ordinal)
		       || string.Equals(actual.FullName, expectedName, StringComparison.Ordinal)
		       || (actual.FullName != null && actual.FullName.EndsWith("." + expectedName, StringComparison.Ordinal));
	}

	private static bool IsRuntimeTypeName(Type actual, string expectedName)
	{
		return actual != null
		       && (string.Equals(actual.Name, expectedName, StringComparison.Ordinal)
		           || string.Equals(actual.FullName, expectedName, StringComparison.Ordinal)
		           || (actual.FullName != null && actual.FullName.EndsWith("." + expectedName, StringComparison.Ordinal)));
	}

	private static bool IsAnyRuntimeTypeName(Type actual, string[] expectedNames)
	{
		if (actual == null || expectedNames == null)
			return false;
		for (var i = 0; i < expectedNames.Length; i++)
			if (IsRuntimeTypeName(actual, expectedNames[i]))
				return true;
		return false;
	}

	private static void PostfixHeroDrawerCtor(object __instance, object[] __args)
	{
		try
		{
			var d = __args != null && __args.Length > 3 ? __args[3] as HeroConfig : null;
			if (__instance == null || d == null)
			{
				LogHeroDiag("ctor-skip reason='missing-instance-or-config' instanceType='" + (__instance?.GetType().FullName ?? "?") + "' args=" + (__args?.Length ?? 0) + ".");
				return;
			}
			var drawerId = __instance.GetHashCode();
			var root = TryGetHeroDrawerRoot(__instance);
			var customHero = IsHomm3CustomHero(d);
			if (!customHero)
			{
				RemoveAttachedVisual(root, true);
				LogHeroDiag("ctor-skip reason='native-hero' " + DescribeHeroConfig(d) + ".");
				return;
			}
			var existingVisual = root ? root.transform.Find(VisualRootName) : null;
			var spriteKey = ResolveSpriteKey(d);
			if (ProcessedDrawerIds.Contains(drawerId) && IsAppliedSpriteCurrent(root, spriteKey))
			{
				LogHeroDiag("ctor-skip reason='already-processed' drawerId=" + drawerId + " " + DescribeHeroConfig(d) + ".");
				return;
			}
			var donor = root ? FindBestDonorRenderer(root) : null;
			LogHeroDiag(
				"ctor-hit mode='"
				+ (_diagnosticsOnly ? "diagnostics" : "replacement")
				+ "' drawerType='"
				+ __instance.GetType().FullName
				+ "' drawerId="
				+ drawerId
				+ " "
				+ DescribeHeroConfig(d)
				+ " spriteKey='"
				+ (spriteKey ?? "?")
				+ "' root='"
				+ DescribeGameObject(root)
				+ "' existingVisual="
				+ (existingVisual != null ? "true" : "false")
				+ " donor='"
				+ DescribeRenderer(donor)
				+ "'.");
			if (!root)
				return;
			if (string.IsNullOrWhiteSpace(spriteKey))
			{
				RemoveAttachedVisual(root, true);
				return;
			}
			if (existingVisual != null && IsAppliedSpriteCurrent(root, spriteKey))
				return;
			if (!TryLoadSpriteSet(spriteKey, Plugin.LogSource, out var spriteSet) || spriteSet == null)
			{
				RemoveAttachedVisual(root, true);
				LogHeroDiag("ctor-skip reason='missing-frames' spriteKey='" + (spriteKey ?? "?") + "' " + DescribeHeroConfig(d) + ".");
				return;
			}
			LogHeroDiag("frames-ready spriteKey='" + spriteKey + "' walkDirections=" + (spriteSet.WalkByFacing?.Length ?? 0) + ".");
			if (_diagnosticsOnly)
			{
				ProcessedDrawerIds.Add(drawerId);
				return;
			}
			if (ApplySprite(root, GetHeroConfigId(d), spriteKey, spriteSet, Plugin.LogSource))
				ProcessedDrawerIds.Add(drawerId);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero drawer postfix failed: " + ex.Message);
		}
	}

	private static void PostfixHeroDrawerRefresh(object __instance, MethodBase __originalMethod)
	{
		try
		{
			if (__instance == null)
				return;
			var config = TryGetHeroConfig(__instance);
			var root = TryGetHeroDrawerRootDirect(__instance);
			var hero = TryGetDrawerHero(__instance);
			var sessionHero = TryGetDrawerSessionHero(__instance);
			var sessionLogicHero = TryGetSessionHero(sessionHero);
			if (Homm3HomecomingWaterTraversalBridge.TryApplyHeroWaterVisualOverride(root, "drawer-refresh:" + (__originalMethod?.Name ?? "?"), hero, sessionHero, sessionLogicHero))
				return;
			var customKey = ResolveCustomHeroKey(config)
			                ?? ResolveCustomHeroSidFromObject(hero)
			                ?? ResolveCustomHeroSidFromObject(sessionLogicHero)
			                ?? ResolveCustomHeroSidFromObject(sessionHero);
			if (!IsHomm3CustomHero(config) && string.IsNullOrWhiteSpace(customKey))
			{
				RemoveAttachedVisual(root, true);
				LogHeroDiag("drawer-refresh-skip method='" + (__originalMethod?.Name ?? "?") + "' reason='native-or-missing-identity' instanceType='" + (__instance.GetType().FullName ?? "?") + "' " + DescribeHeroConfig(config) + " customKey='" + (customKey ?? "?") + "' root='" + DescribeGameObject(root) + "'.");
				return;
			}
			var spriteKey = ResolveSpriteKey(config);
			if (string.IsNullOrWhiteSpace(spriteKey))
				spriteKey = ResolveSpriteKeyFromHeroSid(customKey);
			LogHeroDiag(
				"drawer-refresh method='"
				+ (__originalMethod?.Name ?? "?")
				+ "' "
				+ DescribeHeroConfig(config)
				+ " customKey='"
				+ (customKey ?? "?")
				+ "'"
				+ " root='"
				+ DescribeGameObject(root)
				+ "' spriteKey='"
				+ (spriteKey ?? "?")
				+ "'.");
			TryApplySessionSprite(root, config, customKey, spriteKey, "drawer-refresh:" + (__originalMethod?.Name ?? "?"));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero drawer refresh postfix failed: " + ex.Message);
		}
	}

	private static void PostfixHeroSessionInit(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			Homm3AiDriverLogicHeroRegistry.TryRecordSessionHero(__instance, "session-hero-init:" + (__originalMethod?.Name ?? "?"));
			var hero = __args != null && __args.Length > 0 ? __args[0] : null;
			var config = TryGetHeroConfig(hero) ?? TryGetHeroConfig(__instance);
			var customKey = ResolveCustomHeroKey(config) ?? ResolveCustomHeroSidFromObject(hero) ?? ResolveCustomHeroSidFromObject(__instance);
			var visual = TryGetHeroVisual(__instance);
			var root = TryGetHeroVisualRoot(visual);
			if (Homm3HomecomingWaterTraversalBridge.TryApplyHeroWaterVisualOverride(root, "session-hero-init", hero, __instance, visual))
				return;
			if (!IsHomm3CustomHero(config) && string.IsNullOrWhiteSpace(customKey))
			{
				RemoveAttachedVisual(root, true);
				return;
			}
			var spriteKey = ResolveSpriteKey(config);
			if (string.IsNullOrWhiteSpace(spriteKey))
				spriteKey = ResolveSpriteKeyFromHeroSid(customKey);
			LogHeroSessionDiag(
				"session-hero-init method='"
				+ (__originalMethod?.Name ?? "?")
				+ "' "
				+ DescribeHeroConfig(config)
				+ " customKey='"
				+ (customKey ?? "?")
				+ "' visualType='"
				+ DescribeType(visual)
				+ "' visualRoot='"
				+ DescribeGameObject(root)
				+ "'.");
			TryApplySessionSprite(root, config, customKey, spriteKey, "session-hero-init");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: session hero init diagnostic failed: " + ex.Message);
		}
	}

	private static void PostfixHeroVisualAttached(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var visual = __args != null && __args.Length > 0 ? __args[0] : null;
			var hero = TryGetSessionHero(__instance);
			var config = TryGetHeroConfig(hero) ?? TryGetHeroConfig(__instance) ?? TryGetHeroConfig(visual);
			var customKey = ResolveCustomHeroKey(config) ?? ResolveCustomHeroSidFromObject(hero) ?? ResolveCustomHeroSidFromObject(__instance) ?? ResolveCustomHeroSidFromObject(visual);
			var root = TryGetHeroVisualRoot(visual);
			if (Homm3HomecomingWaterTraversalBridge.TryApplyHeroWaterVisualOverride(root, "hero-visual-attached", hero, __instance, visual))
				return;
			if (!IsHomm3CustomHero(config) && string.IsNullOrWhiteSpace(customKey))
			{
				RemoveAttachedVisual(root, true);
				return;
			}
			var spriteKey = ResolveSpriteKey(config);
			if (string.IsNullOrWhiteSpace(spriteKey))
				spriteKey = ResolveSpriteKeyFromHeroSid(customKey);
			LogHeroSessionDiag(
				"hero-visual-attached method='"
				+ (__originalMethod?.Name ?? "?")
				+ "' "
				+ DescribeHeroConfig(config)
				+ " customKey='"
				+ (customKey ?? "?")
				+ "' visualType='"
				+ DescribeType(visual)
				+ "' visualRoot='"
				+ DescribeGameObject(root)
				+ "' nativeRenderers="
				+ CountRenderers(root)
				+ " donor='"
				+ DescribeRenderer(FindBestDonorRenderer(root))
				+ "'.");
			TryApplySessionSprite(root, config, customKey, spriteKey, "hero-visual-attached");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero visual attachment diagnostic failed: " + ex.Message);
		}
	}

	private static void PostfixHeroVisualGetter(object __instance, object __result, MethodBase __originalMethod)
	{
		try
		{
			var visual = __result;
			var hero = TryGetSessionHero(__instance);
			var config = TryGetHeroConfig(hero) ?? TryGetHeroConfig(__instance) ?? TryGetHeroConfig(visual);
			var customKey = ResolveCustomHeroKey(config) ?? ResolveCustomHeroSidFromObject(hero) ?? ResolveCustomHeroSidFromObject(__instance);
			var root = TryGetHeroVisualRoot(visual);
			if (Homm3HomecomingWaterTraversalBridge.TryApplyHeroWaterVisualOverride(root, "hero-visual-getter", hero, __instance, visual))
				return;
			if (!IsHomm3CustomHero(config) && string.IsNullOrWhiteSpace(customKey))
			{
				RemoveAttachedVisual(root, true);
				return;
			}
			var spriteKey = ResolveSpriteKey(config);
			if (string.IsNullOrWhiteSpace(spriteKey))
				spriteKey = ResolveSpriteKeyFromHeroSid(customKey);
			LogHeroSessionDiag(
				"hero-visual-getter method='"
				+ (__originalMethod?.Name ?? "?")
				+ "' "
				+ DescribeHeroConfig(config)
				+ " customKey='"
				+ (customKey ?? "?")
				+ "' visualType='"
				+ DescribeType(visual)
				+ "' visualRoot='"
				+ DescribeGameObject(root)
				+ "'.");
			TryApplySessionSprite(root, config, customKey, spriteKey, "hero-visual-getter");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: hero visual getter diagnostic failed: " + ex.Message);
		}
	}

	private static HeroConfig TryGetHeroConfig(object source)
	{
		if (source == null)
			return null;
		if (source is HeroConfig direct)
			return direct;
		var type = source.GetType();
		foreach (var name in GameSymbols.HeroMap.HeroConfigFields)
		{
			var value = TryGetDirectHeroConfigMember(source, type, name);
			if (value != null)
				return value;
		}
		foreach (var name in GameSymbols.HeroProfile.HeroConfigFields)
		{
			var value = TryGetDirectHeroConfigMember(source, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static MethodInfo[] FindHeroDrawerRefreshMethods(Type drawerType)
	{
		if (drawerType == null)
			return Array.Empty<MethodInfo>();
		var methods = GameMember.FindMethodsByNames(
			drawerType,
			null,
			GameSymbols.HeroMap.DrawerRefresh);
		var result = new List<MethodInfo>();
		var seen = new HashSet<int>();
		foreach (var method in methods)
		{
			if (method == null || method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != 1 || !IsRuntimeTypeName(ps[0].ParameterType, "EHeroDrawerRefresh"))
				continue;
			if (seen.Add(method.MetadataToken))
				result.Add(method);
		}
		return result.ToArray();
	}

	private static HeroConfig TryGetDirectHeroConfigMember(object source, Type type, string name)
	{
		if (source == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			return TryGetDirectObjectMember(source, type, name) as HeroConfig;
		}
		catch
		{
			return null;
		}
	}

	private static object TryGetSessionHero(object sessionHero)
	{
		if (sessionHero == null)
			return null;
		var type = sessionHero.GetType();
		foreach (var name in GameSymbols.HeroMap.SessionHeroLogicFields)
		{
			var value = TryGetDirectFieldOrBackingObjectMember(sessionHero, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetDrawerHero(object drawer)
	{
		if (drawer == null)
			return null;
		var type = drawer.GetType();
		foreach (var name in GameSymbols.HeroMap.DrawerHeroFields)
		{
			var value = TryGetDirectObjectMember(drawer, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetDrawerSessionHero(object drawer)
	{
		if (drawer == null)
			return null;
		var type = drawer.GetType();
		foreach (var name in GameSymbols.HeroMap.DrawerSessionHeroFields)
		{
			var value = TryGetDirectObjectMember(drawer, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetHeroVisual(object sessionHero)
	{
		if (sessionHero == null)
			return null;
		var type = sessionHero.GetType();
		foreach (var name in GameSymbols.HeroMap.SessionHeroVisualFields)
		{
			var value = TryGetDirectFieldOrBackingObjectMember(sessionHero, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	internal static bool TryApplyExternalSpriteOverrideFromHeroState(string ownerId, string spriteKey, string spriteRoot, ManualLogSource log, string logPrefix, params object[] heroStateCandidates)
	{
		var root = TryResolveHeroVisualRootFromStateCandidates(heroStateCandidates);
		if (!root)
			return false;
		return TryApplyExternalSpriteOverride(root, ownerId, spriteKey, spriteRoot, log, logPrefix);
	}

	internal static bool TryRestoreDefaultSpriteOverrideFromHeroState(string source, params object[] heroStateCandidates)
	{
		var root = TryResolveHeroVisualRootFromStateCandidates(heroStateCandidates);
		if (!root)
			return false;

		var config = TryResolveHeroConfigFromStateCandidates(heroStateCandidates);
		var customKey = ResolveCustomHeroKey(config);
		foreach (var candidate in heroStateCandidates ?? Array.Empty<object>())
		{
			if (string.IsNullOrWhiteSpace(customKey))
				customKey = ResolveCustomHeroSidFromObject(candidate);
			if (string.IsNullOrWhiteSpace(customKey))
				customKey = ResolveCustomHeroSidFromObject(TryGetSessionHero(candidate));
		}

		if (!IsHomm3CustomHero(config) && string.IsNullOrWhiteSpace(customKey))
		{
			RemoveAttachedVisual(root, true);
			LogHeroSessionDiag("external-restore source='" + (source ?? "?") + "' reason='native-or-missing-identity' root='" + DescribeGameObject(root) + "'.");
			return true;
		}

		var defaultSpriteKey = ResolveSpriteKey(config);
		if (string.IsNullOrWhiteSpace(defaultSpriteKey))
			defaultSpriteKey = ResolveSpriteKeyFromHeroSid(customKey);
		return TryApplySessionSprite(root, config, customKey, defaultSpriteKey, source ?? "external-restore");
	}

	private static GameObject TryResolveHeroVisualRootFromStateCandidates(object[] heroStateCandidates)
	{
		foreach (var candidate in heroStateCandidates ?? Array.Empty<object>())
		{
			var root = TryGetHeroVisualRoot(candidate);
			if (root)
				return root;

			var visual = TryGetHeroVisual(candidate);
			root = TryGetHeroVisualRoot(visual);
			if (root)
				return root;

			var sessionLogicHero = TryGetSessionHero(candidate);
			visual = TryGetHeroVisual(sessionLogicHero);
			root = TryGetHeroVisualRoot(visual);
			if (root)
				return root;
		}
		return null;
	}

	private static HeroConfig TryResolveHeroConfigFromStateCandidates(object[] heroStateCandidates)
	{
		foreach (var candidate in heroStateCandidates ?? Array.Empty<object>())
		{
			var config = TryGetHeroConfig(candidate);
			if (config != null)
				return config;
			config = TryGetHeroConfig(TryGetSessionHero(candidate));
			if (config != null)
				return config;
			config = TryGetHeroConfig(TryGetHeroVisual(candidate));
			if (config != null)
				return config;
		}
		return null;
	}

	private static bool TryApplySessionSprite(GameObject root, HeroConfig config, string customKey, string spriteKey, string source)
	{
		if (_diagnosticsOnly)
			return false;
		if (!root)
		{
			LogHeroSessionDiag("replacement-skip source='" + source + "' reason='missing-visual-root' customKey='" + (customKey ?? "?") + "'.");
			return false;
		}
		if (string.IsNullOrWhiteSpace(spriteKey))
		{
			RemoveAttachedVisual(root, true);
			LogHeroSessionDiag("replacement-skip source='" + source + "' reason='missing-sprite-mapping' " + DescribeHeroConfig(config) + " customKey='" + (customKey ?? "?") + "'.");
			return false;
		}
		if (IsAppliedSpriteCurrent(root, spriteKey))
		{
			LogHeroSessionDiag("replacement-skip source='" + source + "' reason='already-attached' root='" + root.name + "'.");
			return true;
		}
		var rootId = root.GetInstanceID();
		if (ProcessedSessionRootIds.Contains(rootId) && IsAppliedSpriteCurrent(root, spriteKey))
		{
			LogHeroSessionDiag("replacement-skip source='" + source + "' reason='already-processed' root='" + root.name + "' rootId=" + rootId + ".");
			return true;
		}
		if (!TryLoadSpriteSet(spriteKey, Plugin.LogSource, out var spriteSet) || spriteSet == null)
		{
			RemoveAttachedVisual(root, true);
			LogHeroSessionDiag("replacement-skip source='" + source + "' reason='missing-frames' spriteKey='" + spriteKey + "' " + DescribeHeroConfig(config) + " customKey='" + (customKey ?? "?") + "'.");
			ProcessedSessionRootIds.Add(rootId);
			return false;
		}
		if (!ApplySprite(root, GetHeroConfigId(config) ?? customKey, spriteKey, spriteSet, Plugin.LogSource))
		{
			LogHeroSessionDiag("replacement-skip source='" + source + "' reason='apply-failed' spriteKey='" + spriteKey + "' " + DescribeHeroConfig(config) + " customKey='" + (customKey ?? "?") + "'.");
			return false;
		}
		ProcessedSessionRootIds.Add(rootId);
		LogHeroSessionDiag(
			"replacement-applied source='"
			+ source
			+ "' "
			+ DescribeHeroConfig(config)
			+ " customKey='"
			+ (customKey ?? "?")
			+ "' spriteKey='"
			+ spriteKey
			+ "' walkDirections="
			+ (spriteSet.WalkByFacing?.Length ?? 0)
			+ " root='"
			+ root.name
			+ "'.");
		return true;
	}

	private static string ResolveCustomHeroKey(object source)
	{
		return source is HeroConfig config ? ResolveCustomHeroKey(config) : null;
	}

	private static string ResolveCustomHeroKey(HeroConfig config)
	{
		if (config == null)
			return null;
		var id = GetHeroConfigId(config);
		if (Homm3CustomFactionRegistry.IsCustomHeroSid(id))
			return id.Trim();
		if (Homm3CustomFactionRegistry.IsCustomHeroSid(config.icon))
			return config.icon.Trim();
		return null;
	}

	private static string ResolveCustomHeroSidFromObject(object source)
	{
		if (source == null)
			return null;
		foreach (var name in GameSymbols.HeroMap.HeroSidFields)
		{
			var sid = TryGetDirectStringField(source, name);
			if (!string.IsNullOrWhiteSpace(sid) && Homm3CustomFactionRegistry.IsCustomHeroSid(sid))
				return sid.Trim();
		}
		return null;
	}

	private static bool IsHomm3CustomHero(HeroConfig config)
	{
		return config != null
		       && (Homm3CustomFactionRegistry.IsCustomFactionSid(config.fraction)
		           || Homm3CustomFactionRegistry.IsCustomHeroSid(GetHeroConfigId(config))
		           || Homm3CustomFactionRegistry.IsCustomHeroSid(config.icon));
	}

	private static string ResolveSpriteKey(HeroConfig config)
	{
		if (config == null)
			return null;
		var faction = config.fraction?.Trim();
		if (string.IsNullOrWhiteSpace(faction))
			return null;
		string classType;
		if (string.Equals(config.classType, "magic", StringComparison.Ordinal))
			classType = "magic";
		else if (string.Equals(config.classType, "might", StringComparison.Ordinal))
			classType = "might";
		else
		{
			LogSpriteMappingSkip(config, faction + "_?");
			return null;
		}
		var key = faction + "_" + classType;
		if (Directory.Exists(GetSpriteRoot(key)))
			return key;
		LogSpriteMappingSkip(config, key);
		return null;
	}

	private static string ResolveSpriteKeyFromHeroSid(string heroSid)
	{
		if (string.IsNullOrWhiteSpace(heroSid))
			return null;
		var normalized = Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(heroSid.Trim(), out var portraitKey)
			? portraitKey
			: heroSid.Trim();
		var marker = "_hero_";
		var markerIndex = normalized.IndexOf(marker, StringComparison.Ordinal);
		if (markerIndex <= 0)
			return null;
		var faction = normalized.Substring(0, markerIndex);
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(faction))
			return null;
		var classType = TryGetHeroClassTypeFromPortraitManifest(normalized);
		if (!string.Equals(classType, "might", StringComparison.Ordinal) && !string.Equals(classType, "magic", StringComparison.Ordinal))
		{
			LogHeroSessionDiag("replacement-skip reason='missing-manifest-class' heroSid='" + heroSid + "' portraitKey='" + normalized + "'.");
			return null;
		}
		var key = faction + "_" + classType;
		if (Directory.Exists(GetSpriteRoot(key)))
			return key;
		LogHeroSessionDiag("replacement-skip reason='missing-sprite-folder' heroSid='" + heroSid + "' spriteKey='" + key + "'.");
		return null;
	}

	private static string TryGetHeroClassTypeFromPortraitManifest(string portraitKey)
	{
		if (string.IsNullOrWhiteSpace(portraitKey))
			return null;
		var map = LoadHeroClassTypesByPortraitKey();
		return map.TryGetValue(portraitKey.Trim(), out var classType) ? classType : null;
	}

	private static Dictionary<string, string> LoadHeroClassTypesByPortraitKey()
	{
		if (HeroClassTypesByPortraitKey != null)
			return HeroClassTypesByPortraitKey;
		var result = new Dictionary<string, string>(StringComparer.Ordinal);
		var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
		var path = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "homm3_hero_portraits", "manifest.json");
		try
		{
			if (!File.Exists(path))
				return HeroClassTypesByPortraitKey = result;
			var entries = JObject.Parse(File.ReadAllText(path))["entries"] as JObject;
			if (entries == null)
				return HeroClassTypesByPortraitKey = result;
			var entriesMap = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, JObject>>(
				entries.ToString(Newtonsoft.Json.Formatting.None));
			if (entriesMap == null)
				return HeroClassTypesByPortraitKey = result;
			foreach (var pair in entriesMap)
			{
				var classType = pair.Value?["classType"]?.ToString()?.Trim();
				if (string.Equals(classType, "might", StringComparison.Ordinal) || string.Equals(classType, "magic", StringComparison.Ordinal))
					result[pair.Key] = classType;
				var alias = pair.Value?["sourceAliasOf"]?.ToString()?.Trim();
				if (!string.IsNullOrWhiteSpace(alias))
					aliases[pair.Key] = alias;
			}
			foreach (var pair in aliases)
				if (!result.ContainsKey(pair.Key) && result.TryGetValue(pair.Value, out var classType))
					result[pair.Key] = classType;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: failed to load hero portrait manifest class metadata: " + ex.Message);
		}
		HeroClassTypesByPortraitKey = result;
		return HeroClassTypesByPortraitKey;
	}

	private static string DescribeHeroConfig(HeroConfig config)
	{
		if (config == null)
			return "heroConfig='null'";
		return "heroSid='"
		       + (GetHeroConfigId(config) ?? "?")
		       + "' icon='"
		       + (config.icon ?? "?")
		       + "' faction='"
		       + (config.fraction ?? "?")
		       + "' classType='"
		       + (config.classType ?? "?")
		       + "'";
	}

	private static string GetHeroConfigId(HeroConfig config)
	{
		return config == null ? null : DeobfInteropCompat.GetHeroConfigId(config);
	}

	private static string DescribeType(object obj)
	{
		if (obj == null)
			return "(none)";
		try
		{
			return obj.GetType().FullName ?? obj.GetType().Name ?? "?";
		}
		catch
		{
			return "?";
		}
	}

	private static object TryGetMemberValue(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var f = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (f != null)
					return f.GetValue(obj);
			}
			catch
			{
			}
			try
			{
				var p = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (p != null && p.GetIndexParameters().Length == 0)
					return p.GetValue(obj);
			}
			catch
			{
			}
			try
			{
				var getter = current.GetMethod("get_" + name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
				if (getter != null)
					return getter.Invoke(obj, Array.Empty<object>());
			}
			catch
			{
			}
		}
		return null;
	}

	private static string TryGetDirectStringField(object source, string name)
	{
		if (source == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var value = TryGetDirectObjectMember(source, source.GetType(), name) as string;
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		catch
		{
		}
		return null;
	}

	private static object TryGetDirectObjectMember(object source, Type type, string name)
	{
		if (source == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			for (var current = type; current != null; current = current.BaseType)
			{
				var field = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				var value = field?.GetValue(source);
				if (value != null)
					return value;
				var property = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					value = property.GetValue(source);
					if (value != null)
						return value;
				}
			}
		}
		catch
		{
		}
		return null;
	}

	private static object TryGetDirectFieldOrBackingObjectMember(object source, Type type, string name)
	{
		if (source == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (source is Il2CppObjectBase il2Cpp && il2Cpp.Pointer == IntPtr.Zero)
			return null;
		try
		{
			for (var current = type; current != null; current = current.BaseType)
			{
				var field = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (field == null)
					continue;
				// Field reads only — property getters have AccessViolation'd via Il2CppObjectPool
				// when Harmony postfixes run against partially-initialized session objects.
				var value = field.GetValue(source);
				if (value != null)
					return value;
			}
		}
		catch
		{
		}
		return null;
	}

	private static object TryInvokeNoArg(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var m = current.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
				if (m != null)
					return m.Invoke(obj, Array.Empty<object>());
			}
			catch
			{
				return null;
			}
		}
		return null;
	}

	private static string DescribeGameObject(GameObject go)
	{
		if (!go)
			return "(none)";
		return (go.name ?? "?")
		       + "' active="
		       + go.activeInHierarchy
		       + " layer="
		       + go.layer
		       + " renderers="
		       + CountRenderers(go);
	}

	private static int CountRenderers(GameObject go)
	{
		try
		{
			return go ? go.GetComponentsInChildren<Renderer>(true)?.Length ?? 0 : 0;
		}
		catch
		{
			return -1;
		}
	}

	private static string DescribeRenderer(Renderer renderer)
	{
		if (!renderer)
			return "(none)";
		var mat = renderer.sharedMaterial;
		var shader = mat ? mat.shader : null;
		return (renderer.name ?? "?")
		       + "' type="
		       + renderer.GetType().Name
		       + " enabled="
		       + renderer.enabled
		       + " forceOff="
		       + renderer.forceRenderingOff
		       + " shadow="
		       + renderer.shadowCastingMode
		       + " material='"
		       + (mat ? mat.name : "(none)")
		       + "' shader='"
		       + (shader ? shader.name : "(none)")
		       + "'";
	}

	private static GameObject TryGetHeroDrawerRoot(object drawer)
	{
		var direct = TryGetDirectGameObject(drawer);
		if (direct)
			return direct;
		var type = drawer.GetType();
		foreach (var m in GameMember.FindMethods(type, typeof(GameObject), Type.EmptyTypes, GameSymbols.HeroMap.RootGameObjectGetter))
		{
			try
			{
				var go = m?.Invoke(drawer, Array.Empty<object>()) as GameObject;
				if (go)
					return go;
			}
			catch
			{
			}
		}
		return TryGetNamedGameObjectProperty(drawer, GameSymbols.HeroMap.RootGameObjectProperties);
	}

	private static GameObject TryGetHeroDrawerRootDirect(object drawer)
	{
		var direct = TryGetDirectGameObject(drawer);
		if (direct)
			return direct;
		return TryGetNamedGameObjectField(drawer, GameSymbols.HeroMap.RootGameObjectProperties)
		       ?? TryGetNamedBackingGameObjectProperty(drawer, GameSymbols.HeroMap.RootGameObjectProperties);
	}

	private static GameObject TryGetHeroVisualRoot(object visual)
	{
		var direct = TryGetDirectGameObject(visual);
		if (direct)
			return direct;
		return TryGetNamedGameObjectField(visual, GameSymbols.HeroMap.RootGameObjectProperties)
		       ?? TryGetNamedBackingGameObjectProperty(visual, GameSymbols.HeroMap.RootGameObjectProperties);
	}

	private static GameObject TryGetDirectGameObject(object source)
	{
		if (source == null)
			return null;
		if (source is GameObject go)
			return go;
		if (source is Component component)
			return component ? component.gameObject : null;
		return null;
	}

	private static GameObject TryGetNamedGameObjectField(object source, string[] names)
	{
		if (source == null || names == null)
			return null;
		var type = source.GetType();
		for (var current = type; current != null; current = current.BaseType)
		{
			foreach (var name in names)
			{
				try
				{
					var f = current.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
					var value = f?.GetValue(source) as GameObject;
					if (value)
						return value;
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static GameObject TryGetNamedBackingGameObjectProperty(object source, string[] names)
	{
		if (source == null || names == null)
			return null;
		var type = source.GetType();
		for (var current = type; current != null; current = current.BaseType)
		{
			foreach (var name in names)
			{
				if (!IsBackingMemberName(name))
					continue;
				try
				{
					var p = current.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
					var value = p != null && p.GetIndexParameters().Length == 0 ? p.GetValue(source) as GameObject : null;
					if (value)
						return value;
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static bool IsBackingMemberName(string name)
	{
		return !string.IsNullOrWhiteSpace(name)
		       && name.IndexOf("BackingField", StringComparison.Ordinal) >= 0;
	}

	private static void LogHeroDiag(string message)
	{
		if (_diagRemaining <= 0)
			return;
		_diagRemaining--;
		Plugin.LogSource?.LogInfo("Homm3HeroMapSprite: " + message);
	}

	private static void LogHeroSessionDiag(string message)
	{
		if (_sessionDiagRemaining <= 0)
			return;
		_sessionDiagRemaining--;
		Plugin.LogSource?.LogInfo("Homm3HeroMapSprite: " + message);
	}

	private static void LogSpriteMappingSkip(HeroConfig config, string key)
	{
		if (_mappingDiagRemaining <= 0)
			return;
		_mappingDiagRemaining--;
		Plugin.LogSource?.LogWarning("Homm3HeroMapSprite: missing adventure-map hero sprite folder key='" + (key ?? "?") + "' " + DescribeHeroConfig(config) + ".");
	}

	private static bool ApplySprite(GameObject root, string heroSid, string spriteKey, Homm3HeroMapSpriteSet spriteSet, ManualLogSource log)
	{
		if (spriteSet == null)
			return false;
		var rootId = root ? root.GetInstanceID() : 0;
		var firstFrame = spriteSet.IdleFrame(2);
		if (!firstFrame)
			return false;
		RemoveAttachedVisual(root, true);
		var donor = FindBestDonorRenderer(root);
		var donorMaterial = donor ? donor.sharedMaterial : null;
		var material = donorMaterial
			? EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(donorMaterial, firstFrame, "HOMM3_hero_map_hexlit_" + spriteKey)
			: CreateFallbackMaterial(firstFrame, spriteKey);
		if (!material)
			return false;

		GameObject visualRoot = null;
		try
		{
			EnsureAnimatorHost(log);
			HideExistingRenderers(root);
			visualRoot = AcquireVisualRoot(root, out var quadGo, out var mf, out var nd);
			var verticalCenter = BillboardHeight * 0.5f;
			if (string.Equals(spriteKey, Homm3HomecomingWaterTraversalBridge.BoatSpriteKey, StringComparison.Ordinal))
				verticalCenter += BillboardHeight * BoatBillboardLiftRatio;
			visualRoot.transform.localPosition = Vector3.up * verticalCenter;
			visualRoot.transform.localRotation = Quaternion.identity;
			visualRoot.transform.localScale = Vector3.one;
			visualRoot.layer = root.layer;

			quadGo.transform.localPosition = Vector3.zero;
			quadGo.transform.localRotation = Quaternion.identity;
			var width = firstFrame && firstFrame.height > 0 ? BillboardHeight * firstFrame.width / firstFrame.height : BillboardHeight;
			quadGo.transform.localScale = new Vector3(width, BillboardHeight, 1f);
			quadGo.layer = root.layer;

			mf.sharedMesh = GetOrCreateQuadMesh();
			nd.sharedMaterial = material;
			if (donor)
				EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donor, visualRoot);
			nd.shadowCastingMode = ShadowCastingMode.On;
			nd.receiveShadows = false;
			nd.allowOcclusionWhenDynamic = false;

			Homm3HeroMapBillboardAnimatorRegistry.Register(nd, quadGo.transform, root.transform, material, spriteSet, FrameMs);
			if (!quadGo.GetComponent<Homm3HeroMapBillboardAnimator>())
				quadGo.AddComponent<Homm3HeroMapBillboardAnimator>();
			if (rootId != 0)
			{
					AppliedSpriteKeysByRootId[rootId] = spriteKey;
					AppliedVisualsByRootId[rootId] = visualRoot;
			}
		}
		catch (Exception ex)
		{
			if (visualRoot)
				ParkAttachedVisual(visualRoot);
			RestoreExistingRenderers(root);
			log?.LogWarning("Homm3HeroMapSprite: failed to attach billboard for spriteKey='" + (spriteKey ?? "?") + "': " + ex.Message);
			return false;
		}

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			log?.LogInfo(
				"Homm3HeroMapSprite: applied heroSid='"
				+ (heroSid ?? "?")
				+ "' spriteKey='"
				+ spriteKey
				+ "' walkDirections="
				+ (spriteSet.WalkByFacing?.Length ?? 0)
				+ " root='"
				+ (root.name ?? "?")
				+ "' donor='"
				+ (donor ? donor.name : "(none)")
				+ "' material='"
				+ (material.name ?? "?")
				+ "'.");
		}
		return true;
	}

	internal static bool TryApplyExternalSpriteOverride(GameObject root, string ownerId, string spriteKey, string spriteRoot, ManualLogSource log, string logPrefix)
	{
		if (!root || string.IsNullOrWhiteSpace(spriteKey) || string.IsNullOrWhiteSpace(spriteRoot))
			return false;
		if (IsAppliedSpriteCurrent(root, spriteKey))
			return true;
		if (!TryLoadSpriteSetFromRoot(spriteKey, spriteRoot, log, out var spriteSet) || spriteSet == null)
		{
			RemoveAttachedVisual(root, true);
			log?.LogWarning((logPrefix ?? "Homm3HeroMapSprite") + " failed closed: missing or incomplete external sprite set key='" + spriteKey + "' root='" + spriteRoot + "'.");
			return false;
		}
		return ApplySprite(root, ownerId, spriteKey, spriteSet, log);
	}

	internal static void RemoveExternalSpriteOverride(GameObject root)
	{
		RemoveAttachedVisual(root, true);
	}

	private static bool TryLoadSpriteSet(string spriteKey, ManualLogSource log, out Homm3HeroMapSpriteSet spriteSet)
	{
		return TryLoadSpriteSetFromRoot(spriteKey, GetSpriteRoot(spriteKey), log, out spriteSet);
	}

	private static bool TryLoadSpriteSetFromRoot(string spriteKey, string root, ManualLogSource log, out Homm3HeroMapSpriteSet spriteSet)
	{
		spriteSet = null;
		if (string.IsNullOrWhiteSpace(spriteKey))
			return false;
		if (SpriteSetsByKey.TryGetValue(spriteKey, out var cached) && cached != null)
		{
			if (IsSpriteSetAlive(cached))
			{
				spriteSet = cached;
				return true;
			}
			SpriteSetsByKey.Remove(spriteKey);
			if (_spriteSetRefreshDiagRemaining > 0)
			{
				_spriteSetRefreshDiagRemaining--;
				log?.LogInfo("Homm3HeroMapSprite: reloading cached sprite set '" + spriteKey + "' after map reload invalidated a Unity texture.");
			}
		}
		if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root))
			return false;
		if (!Homm3HeroMapSpriteFrameIndex.TryCreate(root, out var frameIndex, out var indexError))
		{
			log?.LogWarning("Homm3HeroMapSprite: failed to index sprite frames under '" + root + "': " + indexError + ".");
			return false;
		}

		var set = new Homm3HeroMapSpriteSet
		{
			Key = spriteKey,
			IdleByFacing = new Texture2D[5],
			WalkByFacing = new Texture2D[5][]
		};
		for (var facing = 0; facing < 5; facing++)
		{
			set.IdleByFacing[facing] = LoadSingleFrame(frameIndex, root, facing, 0, spriteKey, log);
			set.WalkByFacing[facing] = LoadFrameGroup(frameIndex, root, facing + 5, WalkFramesPerFacing, spriteKey, log);
		}
		for (var facing = 0; facing < 5; facing++)
		{
			if (!set.IdleFrame(facing) || set.WalkFrameCount(facing) != WalkFramesPerFacing)
			{
				log?.LogWarning("Homm3HeroMapSprite: incomplete hero map sprite set under " + root + " for facing " + facing + ".");
				DestroySpriteSetTextures(set);
				return false;
			}
		}
		SpriteSetsByKey[spriteKey] = set;
		spriteSet = set;
		return true;
	}

	private static void DestroySpriteSetTextures(Homm3HeroMapSpriteSet set)
	{
		if (set == null)
			return;
		if (set.IdleByFacing != null)
		{
			for (var i = 0; i < set.IdleByFacing.Length; i++)
			{
				if (set.IdleByFacing[i])
					UnityEngine.Object.Destroy(set.IdleByFacing[i]);
				set.IdleByFacing[i] = null;
			}
		}
		if (set.WalkByFacing == null)
			return;
		for (var facing = 0; facing < set.WalkByFacing.Length; facing++)
		{
			var frames = set.WalkByFacing[facing];
			if (frames == null)
				continue;
			for (var frame = 0; frame < frames.Length; frame++)
			{
				if (frames[frame])
					UnityEngine.Object.Destroy(frames[frame]);
				frames[frame] = null;
			}
			set.WalkByFacing[facing] = null;
		}
	}

	private static Texture2D LoadSingleFrame(Homm3HeroMapSpriteFrameIndex frameIndex, string root, int group, int frame, string spriteKey, ManualLogSource log)
	{
		if (frameIndex != null && frameIndex.TryGetFrame(group, frame, out var path))
			return LoadFrame(path, spriteKey, log);
		log?.LogWarning("Homm3HeroMapSprite: missing canonical frame " + group.ToString("00") + "_" + frame.ToString("00") + " under " + root + " for spriteKey='" + spriteKey + "'.");
		return null;
	}

	private static Texture2D[] LoadFrameGroup(Homm3HeroMapSpriteFrameIndex frameIndex, string root, int group, int expectedFrames, string spriteKey, ManualLogSource log)
	{
		var loaded = new List<Texture2D>(expectedFrames);
		for (var frame = 0; frame < expectedFrames; frame++)
		{
			var tex = LoadSingleFrame(frameIndex, root, group, frame, spriteKey, log);
			if (!tex)
			{
				DestroyTextures(loaded);
				return Array.Empty<Texture2D>();
			}
			loaded.Add(tex);
		}
		return loaded.ToArray();
	}

	private static void DestroyTextures(List<Texture2D> textures)
	{
		if (textures == null)
			return;
		for (var i = 0; i < textures.Count; i++)
		{
			if (textures[i])
				UnityEngine.Object.Destroy(textures[i]);
			textures[i] = null;
		}
		textures.Clear();
	}

	private static Texture2D LoadFrame(string path, string spriteKey, ManualLogSource log)
	{
		try
		{
			var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			if (!TryLoadTextureImage(tex, File.ReadAllBytes(path)))
			{
				UnityEngine.Object.Destroy(tex);
				return null;
			}
			tex.name = "HOMM3_hero_map_" + spriteKey + "_" + Path.GetFileNameWithoutExtension(path);
			tex.filterMode = FilterMode.Point;
			tex.wrapMode = TextureWrapMode.Clamp;
			return tex;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3HeroMapSprite: frame load failed for '" + path + "': " + ex.Message);
			return null;
		}
	}

	private static bool IsAppliedSpriteCurrent(GameObject root, string spriteKey)
	{
		if (!root || string.IsNullOrWhiteSpace(spriteKey))
			return false;
		var rootId = root.GetInstanceID();
		if (!AppliedVisualsByRootId.TryGetValue(rootId, out var visual) || !visual)
			return false;
		if (!IsAttachedVisualAlive(visual, spriteKey))
		{
			if (_staleVisualDiagRemaining > 0)
			{
				_staleVisualDiagRemaining--;
				Plugin.LogSource?.LogInfo("Homm3HeroMapSprite: pruning stale attached visual for root='" + (root.name ?? "?") + "' spriteKey='" + spriteKey + "' after map reload invalidated a Unity object.");
			}
			RemoveAttachedVisual(root, true);
			return false;
		}
		return AppliedSpriteKeysByRootId.TryGetValue(rootId, out var applied)
		       && string.Equals(applied, spriteKey, StringComparison.Ordinal);
	}

	private static bool IsCachedSpriteSetCurrent(string spriteKey)
	{
		if (string.IsNullOrWhiteSpace(spriteKey))
			return false;
		if (!SpriteSetsByKey.TryGetValue(spriteKey, out var cached) || cached == null)
			return true;
		if (IsSpriteSetAlive(cached))
			return true;
		SpriteSetsByKey.Remove(spriteKey);
		return false;
	}

	private static bool IsSpriteSetAlive(Homm3HeroMapSpriteSet set) => set != null && set.IsAlive(WalkFramesPerFacing);

	private static bool IsAttachedVisualAlive(GameObject visual, string spriteKey)
	{
		if (!visual || !visual.activeInHierarchy)
			return false;
		var quad = visual.transform.Find("quad");
		if (!quad || !quad.gameObject.activeInHierarchy)
			return false;
		var renderer = quad.GetComponent<Renderer>();
		if (!renderer || !renderer.enabled || renderer.forceRenderingOff)
			return false;
		var material = renderer.sharedMaterial;
		if (!material)
			return false;
		return material.mainTexture
		       && Homm3HeroMapBillboardAnimatorRegistry.IsRendererUsingLiveSpriteSet(renderer, spriteKey, WalkFramesPerFacing);
	}

	private static void RemoveAttachedVisual(GameObject root, bool restoreNativeRenderers)
	{
		if (!root)
			return;
		var rootId = root.GetInstanceID();
		for (var i = root.transform.childCount - 1; i >= 0; i--)
		{
			var child = root.transform.GetChild(i);
			if (!child || !string.Equals(child.name, VisualRootName, StringComparison.Ordinal))
				continue;
			ParkAttachedVisual(child.gameObject);
		}
		AppliedVisualsByRootId.Remove(rootId);
		AppliedSpriteKeysByRootId.Remove(rootId);
		if (restoreNativeRenderers)
			RestoreExistingRenderers(root);
	}

	private static void ParkAttachedVisual(GameObject visualRoot)
	{
		if (!visualRoot)
			return;
		foreach (var renderer in visualRoot.GetComponentsInChildren<Renderer>(true))
		{
			if (renderer)
				Homm3HeroMapBillboardAnimatorRegistry.UnregisterRenderer(renderer.GetInstanceID());
		}
		visualRoot.SetActive(false);
		visualRoot.name = ParkedVisualRootName;
	}

	/// <summary>Reuses a parked mod visual (never destroyed, see ParkedVisualRootName) or creates one.</summary>
	private static GameObject AcquireVisualRoot(GameObject root, out GameObject quadGo, out MeshFilter meshFilter, out MeshRenderer meshRenderer)
	{
		quadGo = null;
		meshFilter = null;
		meshRenderer = null;
		for (var i = 0; i < root.transform.childCount; i++)
		{
			var child = root.transform.GetChild(i);
			if (!child || !string.Equals(child.name, ParkedVisualRootName, StringComparison.Ordinal))
				continue;
			var quad = child.Find("quad");
			var mf = quad ? quad.GetComponent<MeshFilter>() : null;
			var mr = quad ? quad.GetComponent<MeshRenderer>() : null;
			if (!mf || !mr)
				continue;
			child.name = VisualRootName;
			child.gameObject.SetActive(true);
			quadGo = quad.gameObject;
			meshFilter = mf;
			meshRenderer = mr;
			return child.gameObject;
		}

		var visualRoot = new GameObject(VisualRootName);
		visualRoot.transform.SetParent(root.transform, false);
		quadGo = new GameObject("quad");
		quadGo.transform.SetParent(visualRoot.transform, false);
		meshFilter = quadGo.AddComponent<MeshFilter>();
		meshRenderer = quadGo.AddComponent<MeshRenderer>();
		return visualRoot;
	}

	private static bool IsUnderModVisualRoot(Transform t)
	{
		return IsUnderNamedRoot(t, VisualRootName) || IsUnderNamedRoot(t, ParkedVisualRootName);
	}

	private static string GetSpriteRoot(string spriteKey)
	{
		return string.IsNullOrWhiteSpace(spriteKey)
			? null
			: Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "homm3_hero_map_sprites", spriteKey);
	}

	private static void EnsureAnimatorHost(ManualLogSource log)
	{
		if (!_animatorRegistered)
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3HeroMapBillboardAnimator>();
			}
			catch
			{
				// Another hero map visual may already have registered the shared animator type.
			}
			_animatorRegistered = true;
		}
		if (_animatorHostAttached)
			return;
		var host = new GameObject("Homm3HeroMapSpriteAnimator");
		host.hideFlags = HideFlags.HideAndDontSave;
		host.AddComponent<Homm3HeroMapBillboardAnimator>();
		UnityEngine.Object.DontDestroyOnLoad(host);
		_animatorHostAttached = true;
		log?.LogInfo("Homm3HeroMapSprite: attached shared map texture animator host.");
	}

	private static Renderer FindBestDonorRenderer(GameObject root)
	{
		if (!root)
			return null;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderModVisualRoot(r.transform))
				continue;
			if (!r || !r.sharedMaterial || !r.sharedMaterial.shader)
				continue;
			if (string.Equals(r.sharedMaterial.shader.name, "Hex/Lit", StringComparison.Ordinal))
				return r;
		}
		var all = root.GetComponentsInChildren<Renderer>(true);
		if (all == null)
			return null;
		for (var i = 0; i < all.Length; i++)
		{
			if (all[i] && !IsUnderModVisualRoot(all[i].transform))
				return all[i];
		}
		return null;
	}

	private static void HideExistingRenderers(GameObject root)
	{
		if (!root)
			return;
		var rootId = root.GetInstanceID();
		HiddenRendererStatesByRootId[rootId] = CaptureRendererStates(root);
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderModVisualRoot(r.transform))
				continue;
			r.enabled = false;
			r.forceRenderingOff = true;
			r.shadowCastingMode = ShadowCastingMode.Off;
		}
	}

	private static List<RendererState> CaptureRendererStates(GameObject root)
	{
		var states = new List<RendererState>();
		if (!root)
			return states;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || IsUnderModVisualRoot(r.transform))
				continue;
			states.Add(new RendererState
			{
				Renderer = r,
				Enabled = r.enabled,
				ForceRenderingOff = r.forceRenderingOff,
				ShadowCastingMode = r.shadowCastingMode
			});
		}
		return states;
	}

	private static void RestoreExistingRenderers(GameObject root)
	{
		if (!root)
			return;
		var rootId = root.GetInstanceID();
		if (!HiddenRendererStatesByRootId.TryGetValue(rootId, out var states) || states == null)
			return;
		for (var i = 0; i < states.Count; i++)
		{
			var state = states[i];
			if (!state.Renderer)
				continue;
			state.Renderer.enabled = state.Enabled;
			state.Renderer.forceRenderingOff = state.ForceRenderingOff;
			state.Renderer.shadowCastingMode = state.ShadowCastingMode;
		}
		HiddenRendererStatesByRootId.Remove(rootId);
	}

	private static bool IsUnderNamedRoot(Transform t, string rootName)
	{
		for (var cur = t; cur != null; cur = cur.parent)
			if (string.Equals(cur.name, rootName, StringComparison.Ordinal))
				return true;
		return false;
	}

	private static Material CreateFallbackMaterial(Texture texture, string spriteClass)
	{
		var shader = Shader.Find("Hex/Lit") ?? Shader.Find("Unlit/Transparent") ?? Shader.Find("Sprites/Default");
		if (!shader)
			return null;
		return new Material(shader)
		{
			name = "HOMM3_hero_map_hexlit_" + spriteClass + "_fallback",
			mainTexture = texture
		};
	}

	private static bool TryLoadTextureImage(Texture2D texture, byte[] bytes)
	{
		if (!texture || bytes == null || bytes.Length == 0)
			return false;
		var il2cppBytes = new Il2CppStructArray<byte>(bytes);
		return ImageConversion.LoadImage(texture, il2cppBytes);
	}

	private static Mesh GetOrCreateQuadMesh()
	{
		if (_quadMesh)
			return _quadMesh;
		_quadMesh = new Mesh { name = "HOMM3_hero_map_quad" };
		_quadMesh.vertices = new[]
		{
			new Vector3(-0.5f, -0.5f, 0f),
			new Vector3(0.5f, -0.5f, 0f),
			new Vector3(-0.5f, 0.5f, 0f),
			new Vector3(0.5f, 0.5f, 0f)
		};
		_quadMesh.uv = new[] { new Vector2(0f, 0f), new Vector2(1f, 0f), new Vector2(0f, 1f), new Vector2(1f, 1f) };
		_quadMesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
		_quadMesh.RecalculateNormals();
		_quadMesh.RecalculateBounds();
		return _quadMesh;
	}
}
