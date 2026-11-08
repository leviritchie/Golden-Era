using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Narrow preview-window hook for lane B. Unlike the failed ResManager experiment, this patches only
/// UI/model methods that already returned a vanilla <see cref="GameObject"/> from a first string path.
/// </summary>
internal static class Homm3ImportPreviewWindowHook
{
	private static bool _patched;
	private static int _loggedReplace;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		try
		{
			var targets = FindTargets(log);
			if (targets.Count == 0)
			{
				log?.LogWarning("Homm3Import preview window: no string-path GameObject preview loaders found.");
				return;
			}

			var postfix = new HarmonyMethod(typeof(Homm3ImportPreviewWindowHook), nameof(PostfixPreviewGameObject));
			var patched = 0;
			for (var i = 0; i < targets.Count; i++)
			{
				try
				{
					h.Patch(targets[i], postfix: postfix);
					patched++;
				}
				catch (Exception ex)
				{
					log?.LogWarning("Homm3Import preview window: could not patch " + Describe(targets[i]) + ": " + ex.Message);
				}
			}

			if (patched == 0)
				return;

			_patched = true;
			log?.LogInfo("Homm3Import: Harmony postfix on " + patched + " preview string-path GameObject loader(s).");
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3Import preview window hook failed: " + ex);
		}
	}

	private static List<MethodInfo> FindTargets(ManualLogSource log)
	{
		var result = new List<MethodInfo>();
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		for (var ai = 0; ai < assemblies.Length; ai++)
		{
			var asm = assemblies[ai];
			if (asm == null)
				continue;
			var an = asm.GetName().Name ?? string.Empty;
			if (!LooksRelevantAssembly(an))
				continue;

			var types = SafeGetTypes(asm);
			for (var ya = 0; ya < types.Length; ya++)
			{
				var t = types[ya];
				if (t == null || !LooksRelevantType(t) || IsExcludedType(t))
					continue;

				MethodInfo[] methods;
				try
				{
					methods = t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
				}
				catch
				{
					continue;
				}

				for (var mi = 0; mi < methods.Length; mi++)
				{
					var m = methods[mi];
					if (!LooksLikeStringPathPreviewLoader(m))
						continue;
					result.Add(m);
					if (result.Count <= 24)
						log?.LogInfo("Homm3Import preview window target: " + Describe(m));
				}
			}
		}

		if (result.Count > 24)
			log?.LogInfo("Homm3Import preview window: " + (result.Count - 24) + " additional target(s) not listed.");
		return result;
	}

	private static bool LooksRelevantAssembly(string name)
	{
		return string.Equals(name, "Hex", StringComparison.Ordinal)
		       || string.Equals(name, "Assembly-CSharp", StringComparison.Ordinal)
		       || string.Equals(name, "Hex.Shared", StringComparison.Ordinal);
	}

	private static bool LooksRelevantType(Type t)
	{
		var full = t.FullName ?? t.Name ?? string.Empty;
		return ContainsAny(full, "Preview", "Model", "Spawner", "Unit", "Army", "Garrison", "City", "View", "Window", "Tooltip", "Card");
	}

	private static bool IsExcludedType(Type t)
	{
		var full = t.FullName ?? string.Empty;
		return string.Equals(full, "Hex.ResManager", StringComparison.Ordinal)
		       || string.Equals(full, "Hex.Configs.UnitViewConfig", StringComparison.Ordinal)
		       || string.Equals(t.Name, "dzk", StringComparison.Ordinal);
	}

	private static bool LooksLikeStringPathPreviewLoader(MethodInfo m)
	{
		if (m == null || m.ReturnType != typeof(GameObject))
			return false;
		if (m.ContainsGenericParameters)
			return false;
		var ps = m.GetParameters();
		if (ps.Length == 0 || !IsStringish(ps[0].ParameterType))
			return false;

		var mn = m.Name ?? string.Empty;
		var typeName = m.DeclaringType?.FullName ?? string.Empty;
		if (!ContainsAny(mn, "Spawn", "Create", "Load", "Show", "View", "Model", "Preview")
		    && !ContainsAny(typeName, "Preview", "Model", "Spawner", "View", "Window", "Tooltip", "Card"))
			return false;

		return true;
	}

	private static void PostfixPreviewGameObject(
		MethodBase __originalMethod,
		object[] __args,
		ref GameObject __result)
	{
		if (__args == null || __args.Length == 0 || !__result)
			return;
		var path = __args[0] as string;
		if (string.IsNullOrEmpty(path))
			return;

		var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(path);
		if (Homm3ImportVisuals.TryResolveHomm3MapEntry(unitsPath, out var gatedEntry)
		    && gatedEntry != null
		    && gatedEntry.SwapAdventureMap
		    && Homm3ImportVisuals.EntryHasGameUnitSidGate(gatedEntry))
			return;
		if (!Homm3ImportVisuals.TryGetTemplateForUnitsPath(unitsPath, Plugin.LogSource, out var template) || !template)
			return;

		try
		{
			var vanilla = __result;
			if (vanilla.scene.IsValid())
			{
				var instance = UnityEngine.Object.Instantiate(template);
				if (!instance)
					return;
				instance.name = template.name;
				var vt = vanilla.transform;
				var it = instance.transform;
				it.SetParent(vt.parent, false);
				instance.SetActive(true);
				if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
				{
					if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(unitsPath, Plugin.LogSource, out var skinnedEntry))
						Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, skinnedEntry, vanilla, keepPose: false, 0f, "preview-window", Plugin.LogSource);
					else
						Plugin.LogSource?.LogError("Homm3Import preview window: owned skinned '" + unitsPath + "' has no homm3_import entry; preview left unframed.");
				}
				else
				{
					it.localPosition = vt.localPosition;
					it.localRotation = vt.localRotation;
					it.localScale = vt.localScale;
					SyncPreviewPresentation(vanilla, instance);
				}
				vanilla.SetActive(false);
				UnityEngine.Object.Destroy(vanilla);
				__result = instance;
				LogReplace(__originalMethod, "instance", path, unitsPath, instance);
				return;
			}

			SyncPreviewPresentation(vanilla, template);
			__result = template;
			LogReplace(__originalMethod, "template", path, unitsPath, template);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import preview window Postfix: " + ex);
		}
	}

	private static void SyncPreviewPresentation(GameObject vanilla, GameObject custom)
	{
		EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(vanilla, custom);
		EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(vanilla, custom);
		EsquireBattleVisualPresentation.SyncMapRenderersSortingDepthFirstFallback(vanilla, custom);
	}

	private static void LogReplace(MethodBase method, string mode, string path, string unitsPath, GameObject replacement)
	{
		if (_loggedReplace >= 40)
			return;
		_loggedReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import preview window: replaced "
			+ mode
			+ " from "
			+ (method?.DeclaringType?.FullName ?? "?")
			+ "."
			+ (method?.Name ?? "?")
			+ " path='"
			+ path
			+ "' unitsPath='"
			+ unitsPath
			+ "' with '"
			+ (replacement ? replacement.name : "?")
			+ "'.");
	}

	private static bool IsStringish(Type t)
	{
		if (t == null)
			return false;
		return t == typeof(string) || t.FullName == "System.String" || t.Name == "String";
	}

	private static Type[] SafeGetTypes(Assembly asm)
	{
		try
		{
			return asm.GetTypes();
		}
		catch (ReflectionTypeLoadException e)
		{
			return e.Types ?? Array.Empty<Type>();
		}
		catch
		{
			return Array.Empty<Type>();
		}
	}

	private static string Describe(MethodBase m)
	{
		if (m == null)
			return "?";
		var ps = m.GetParameters();
		var parts = new string[ps.Length];
		for (var i = 0; i < ps.Length; i++)
		{
			var p = ps[i];
			parts[i] = (p?.ParameterType?.Name ?? "?") + " " + (p?.Name ?? "?");
		}

		return (m.DeclaringType?.FullName ?? "?")
		       + "."
		       + m.Name
		       + "("
		       + string.Join(", ", parts)
		       + ")";
	}

	private static bool ContainsAny(string value, params string[] needles)
	{
		if (string.IsNullOrEmpty(value))
			return false;
		for (var i = 0; i < needles.Length; i++)
			if (value.IndexOf(needles[i], StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		return false;
	}
}
