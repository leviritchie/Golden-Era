using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Audit A5 class guard (2026-11-14). The native renderer cache (Hex.Render.RenderersHandler,
/// obfuscated) is built once per map object by MapObject.GetRenderers and never refreshed.
/// WorldObject.SetSelectionOutline sets sortingLayerID on every cached renderer, so a renderer
/// destroyed after the cache was built throws NullReferenceException inside native code. On
/// hover exit that throw repeats every frame and wedges adventure-map input (hero cannot move).
/// Seen 2026-11-14 after leaving the Inferno town: 4,500+ throws from the hover-exit path.
///
/// This prefix prunes destroyed entries from the cache before any sorting-layer write, and logs
/// the owning object once so the mod code that destroyed the renderer can be found and fixed.
/// The handler type is found by shape (List&lt;Renderer&gt; + List&lt;Material&gt; + GameObject
/// members) so no generated IL2CPP names are referenced here.
/// </summary>
internal static class NativeRendererCacheGuard
{
	private const int MaxLoggedRoots = 32;
	private static bool _patched;
	private static ManualLogSource _log;
	private static Type _handlerType;
	private static PropertyInfo _renderersProperty;
	private static PropertyInfo _gameObjectProperty;
	private static readonly HashSet<string> LoggedRoots = new(StringComparer.Ordinal);

	internal static void Register(Harmony harmony, ManualLogSource log)
	{
		if (_patched || harmony == null)
			return;
		_log = log;
		var handlerType = FindHandlerType(out var renderersProperty, out var gameObjectProperty, out var candidates);
		if (handlerType == null)
		{
			log?.LogWarning("NativeRendererCacheGuard: skipped; renderer-cache type not uniquely found (candidates=" + candidates + ").");
			return;
		}
		_handlerType = handlerType;
		_renderersProperty = renderersProperty;
		_gameObjectProperty = gameObjectProperty;

		var prefix = new HarmonyMethod(typeof(NativeRendererCacheGuard), nameof(PrefixPruneDeadRenderers));
		var patchedNames = new List<string>();
		foreach (var method in handlerType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
		{
			if (method.ReturnType != typeof(void) || method.IsSpecialName)
				continue;
			// Il2CppInterop "possibly dead method" wrappers can share a folded native body with
			// unrelated methods; patching one would run this prefix for other types.
			if (method.Name.Contains("_PDM_", StringComparison.Ordinal))
				continue;
			var parameters = method.GetParameters();
			var sortingLayerShape = parameters.Length >= 1
			                        && parameters[0].ParameterType == typeof(int)
			                        && (parameters.Length == 1
			                            || (parameters.Length == 2 && parameters[1].ParameterType == typeof(string)));
			if (!sortingLayerShape)
				continue;
			harmony.Patch(method, prefix: prefix);
			patchedNames.Add(method.Name);
		}
		_patched = patchedNames.Count > 0;
		log?.LogInfo("NativeRendererCacheGuard: type='" + handlerType.FullName + "' renderers='" + renderersProperty.Name
		             + "' patched=[" + string.Join(", ", patchedNames) + "].");
	}

	private static Type FindHandlerType(out PropertyInfo renderersProperty, out PropertyInfo gameObjectProperty, out int candidates)
	{
		renderersProperty = null;
		gameObjectProperty = null;
		candidates = 0;
		Type match = null;
		Type[] types;
		try
		{
			types = typeof(Hex.Configs.ObjCityConfig).Assembly.GetTypes();
		}
		catch (ReflectionTypeLoadException ex)
		{
			types = ex.Types;
		}
		var rendererListType = typeof(Il2CppSystem.Collections.Generic.List<Renderer>);
		var materialListType = typeof(Il2CppSystem.Collections.Generic.List<Material>);
		foreach (var type in types)
		{
			if (type == null || !type.IsClass)
				continue;
			PropertyInfo renderers = null, gameObject = null;
			var hasMaterials = false;
			PropertyInfo[] properties;
			try
			{
				properties = type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			}
			catch
			{
				continue;
			}
			foreach (var property in properties)
			{
				if (property.GetIndexParameters().Length != 0)
					continue;
				if (property.PropertyType == rendererListType)
					renderers ??= property;
				else if (property.PropertyType == materialListType)
					hasMaterials = true;
				else if (property.PropertyType == typeof(GameObject))
					gameObject ??= property;
			}
			if (renderers == null || !hasMaterials || gameObject == null)
				continue;
			candidates++;
			match = type;
			renderersProperty = renderers;
			gameObjectProperty = gameObject;
		}
		return candidates == 1 ? match : null;
	}

	// Runs inside native outline/sorting calls: never throw.
	private static void PrefixPruneDeadRenderers(object __instance)
	{
		try
		{
			if (__instance == null || _renderersProperty == null || __instance.GetType() != _handlerType)
				return;
			if (_renderersProperty.GetValue(__instance) is not Il2CppSystem.Collections.Generic.List<Renderer> list)
				return;
			var removed = 0;
			for (var i = list.Count - 1; i >= 0; i--)
			{
				if (list[i])
					continue;
				list.RemoveAt(i);
				removed++;
			}
			if (removed > 0)
				LogPrune(__instance, removed, list.Count);
		}
		catch (Exception ex)
		{
			if (LoggedRoots.Add("!exception"))
				_log?.LogWarning("NativeRendererCacheGuard: prune failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void LogPrune(object handler, int removed, int remaining)
	{
		var path = "?";
		try
		{
			if (_gameObjectProperty?.GetValue(handler) is GameObject go && go)
				path = DescribePath(go.transform);
		}
		catch
		{
			// Description is best-effort.
		}
		if (LoggedRoots.Count >= MaxLoggedRoots || !LoggedRoots.Add(path))
			return;
		_log?.LogWarning("NativeRendererCacheGuard: pruned " + removed + " destroyed renderer(s) from native cache of '" + path
		                 + "' (remaining=" + remaining + "). Some mod code destroyed a renderer under this map object; park it instead.");
	}

	private static string DescribePath(Transform t)
	{
		var parts = new List<string>();
		for (var depth = 0; t && depth < 6; depth++, t = t.parent)
			parts.Add(t.name);
		parts.Reverse();
		return string.Join("/", parts);
	}
}
