using System;
using System.Reflection;
using BepInEx.Logging;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Read-only discovery for the current build's unit preview/model loader path.
/// The old <c>Hex.UI.UiModelsSpawner</c> type is absent, and global ResManager patching is too fragile at startup.
/// </summary>
internal static class Homm3ImportPreviewProbe
{
	private static bool _ran;

	internal static void ResetForHarmonyReload()
	{
		_ran = false;
	}

	internal static void TryRun(ManualLogSource log)
	{
		if (_ran || log == null)
			return;
		_ran = true;

		try
		{
			var logged = 0;
			var assemblies = AppDomain.CurrentDomain.GetAssemblies();
			for (var ai = 0; ai < assemblies.Length && logged < 80; ai++)
			{
				var asm = assemblies[ai];
				if (asm == null)
					continue;
				var an = asm.GetName().Name ?? string.Empty;
				if (!LooksRelevantAssembly(an))
					continue;

				var types = SafeGetTypes(asm);
				for (var ya = 0; ya < types.Length && logged < 80; ya++)
				{
					var t = types[ya];
					if (t == null || !LooksRelevantType(t))
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

					for (var mi = 0; mi < methods.Length && logged < 80; mi++)
					{
						var m = methods[mi];
						if (!LooksLikePreviewCandidate(m))
							continue;
						logged++;
						log.LogInfo("Homm3Import preview probe: " + Describe(m));
					}
				}
			}

			if (logged == 0)
				log.LogWarning("Homm3Import preview probe: no candidate GameObject preview/model loader methods found.");
			else
				log.LogInfo("Homm3Import preview probe: logged " + logged + " candidate method(s).");
		}
		catch (Exception ex)
		{
			log.LogWarning("Homm3Import preview probe failed: " + ex.Message);
		}
	}

	private static bool LooksRelevantAssembly(string name)
	{
		return string.Equals(name, "Hex", StringComparison.Ordinal)
		       || string.Equals(name, "Assembly-CSharp", StringComparison.Ordinal)
		       || string.Equals(name, "Hex.Shared", StringComparison.Ordinal)
		       || string.Equals(name, "Hex.ResManager", StringComparison.Ordinal);
	}

	private static bool LooksRelevantType(Type t)
	{
		var full = t.FullName ?? t.Name ?? string.Empty;
		return ContainsAny(full, "Preview", "Model", "Spawner", "Unit", "Army", "Garrison", "City", "View", "Window", "Tooltip", "Card");
	}

	private static bool LooksLikePreviewCandidate(MethodInfo m)
	{
		if (m == null || m.ReturnType != typeof(GameObject))
			return false;
		var mn = m.Name ?? string.Empty;
		var typeName = m.DeclaringType?.FullName ?? string.Empty;
		if (!ContainsAny(mn, "Spawn", "Create", "Get", "Load", "Show", "View", "Model", "Preview", "rtd")
		    && !ContainsAny(typeName, "Preview", "Model", "Spawner", "View", "Window", "Tooltip", "Card"))
			return false;
		var ps = m.GetParameters();
		if (ps.Length == 0)
			return true;
		for (var i = 0; i < ps.Length; i++)
		{
			var p = ps[i];
			if (p == null)
				continue;
			if (IsStringish(p.ParameterType))
				return true;
			var qk = p.Name ?? string.Empty;
			if (ContainsAny(qk, "path", "mesh", "unit", "sid", "res", "prefab"))
				return true;
		}

		return false;
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

	private static string Describe(MethodInfo m)
	{
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
		       + ") ret="
		       + m.ReturnType.Name;
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
