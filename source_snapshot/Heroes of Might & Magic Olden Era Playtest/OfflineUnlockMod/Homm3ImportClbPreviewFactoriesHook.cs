using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;

#if !OFFICIAL_DEOBF_BUILD
namespace OfflineUnlockMod;

/// <summary>
/// Recruitment / army / hire UIs may call other <see cref="clb"/> factories than
/// <see cref="BhUnitWindowPreview.bebc"/> / <see cref="BhUnitWindowPreview.Show"/>.
/// Reflect matching methods in Hex and postfix the same replace when args carry a unit key.
/// </summary>
internal static class Homm3ImportClbPreviewFactoriesHook
{
	private static readonly HashSet<string> PatchedSignatures = new(StringComparer.Ordinal);

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (h == null)
			return;

		Type clbRt;
		try
		{
			clbRt = typeof(clb);
		}
		catch
		{
			return;
		}

		SeedBhUnitWindowPreviewMethods();
		TryPatchBhUnitPreviewsHqr(h, log);

		const int maxPatches = 48;
		var n = 0;
		try
		{
			foreach (var mi in EnumerateFactories(clbRt))
			{
				var sig = Signature(mi);
				if (PatchedSignatures.Contains(sig))
					continue;
				if (!ParametersLookLikeUnitKey(mi))
					continue;
				if (n >= maxPatches)
					break;

				try
				{
					h.Patch(mi, postfix: new HarmonyMethod(typeof(Homm3ImportClbPreviewFactoriesHook), nameof(PostfixClbFactory)));
					PatchedSignatures.Add(sig);
					n++;
					log?.LogInfo("Homm3Import clb preview factory target: " + sig);
				}
				catch (Exception ex)
				{
					log?.LogWarning("Homm3Import clb preview factory patch failed for " + sig + ": " + ex.Message);
				}
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import clb preview factory enumeration failed: " + ex.Message);
		}
	}

	internal static void TryRegisterBhUnitPreviewsHqrOnly(Harmony h, ManualLogSource log)
	{
		if (h == null)
			return;
		SeedBhUnitWindowPreviewMethods();
		TryPatchBhUnitPreviewsHqr(h, log);
	}

	private static void SeedBhUnitWindowPreviewMethods()
	{
		MethodInfo bebc = null;
		foreach (var methodName in GameSymbols.UnitPreview.WindowFactory.NameHints)
		{
			bebc = AccessTools.Method(typeof(BhUnitWindowPreview), methodName, new[] { typeof(string), typeof(Transform) });
			if (bebc != null)
				break;
		}
		var show = AccessTools.Method(typeof(BhUnitWindowPreview), nameof(BhUnitWindowPreview.Show), new[] { typeof(UnitViewConfig) });
		if (bebc != null)
			PatchedSignatures.Add(Signature(bebc));
		if (show != null)
			PatchedSignatures.Add(Signature(show));
	}

	/// <summary>
	/// <see cref="BhUnitPreviews.hqr"/> returns <see cref="bool"/> and fills <see cref="clb"/> via <c>ref</c> — skipped by
	/// <see cref="EnumerateFactories"/>. Recruitment often uses this path; we only run when <paramref name="__result"/> is <c>true</c>
	/// (success) and never <see cref="UnityEngine.Object.Destroy"/> the vanilla model (see <c>Homm3ImportUnitPreviewModelHook</c>).
	/// </summary>
	private static void TryPatchBhUnitPreviewsHqr(Harmony h, ManualLogSource log)
	{
		MethodInfo target = null;
		try
		{
			foreach (var m in typeof(BhUnitPreviews).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				if (m == null || m.ReturnType != typeof(bool))
					continue;
				var ps = m.GetParameters();
				if (ps.Length != 3)
					continue;
				if (ps[0].ParameterType != typeof(string) || ps[1].ParameterType != typeof(float))
					continue;
				if (!ps[2].ParameterType.IsByRef || ps[2].ParameterType.GetElementType() != typeof(clb))
					continue;
				if (Array.IndexOf(GameSymbols.UnitPreview.SharedPreviewFactory.NameHints, m.Name) >= 0)
				{
					target = m;
					break;
				}
				target ??= m;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: could not reflect BhUnitPreviews shared preview factory: " + ex.Message);
			return;
		}

		if (target == null)
		{
			log?.LogWarning("Homm3Import: BhUnitPreviews bool(string, float, ref clb) preview factory not found.");
			return;
		}

		var sig = Signature(target);
		if (PatchedSignatures.Contains(sig))
			return;
		try
		{
			h.Patch(target, postfix: new HarmonyMethod(typeof(Homm3ImportClbPreviewFactoriesHook), nameof(PostfixBhUnitPreviewsHqr)));
			PatchedSignatures.Add(sig);
			log?.LogInfo("Homm3Import clb preview factory target: " + sig + " (ref clb, success-only)");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: patch BhUnitPreviews shared preview factory failed: " + ex.Message);
		}
	}

	private static void PostfixBhUnitPreviewsHqr(bool __result, string a, float b, ref clb c)
	{
		if (!__result || c == null || string.IsNullOrWhiteSpace(a))
			return;
		Homm3ImportUnitPreviewModelHook.TryApplyFromExternalDiscovery(c, a, "Hex.BhUnitPreviews.hqr");
	}

	private static string Signature(MethodInfo m)
	{
		if (m == null)
			return string.Empty;
		return m.DeclaringType?.FullName + "::" + m.Name + "(" + m.GetParameters().Length + ")";
	}

	private static bool ParametersLookLikeUnitKey(MethodInfo m)
	{
		var ps = m.GetParameters();
		for (var i = 0; i < ps.Length; i++)
		{
			var t = ps[i].ParameterType;
			if (t == typeof(string) || t == typeof(UnitViewConfig))
				return true;
		}
		return false;
	}

	private static IEnumerable<MethodInfo> EnumerateFactories(Type clbRt)
	{
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		for (var ai = 0; ai < assemblies.Length; ai++)
		{
			var asm = assemblies[ai];
			if (asm == null)
				continue;
			if (!string.Equals(asm.GetName().Name ?? string.Empty, "Hex", StringComparison.Ordinal))
				continue;

			Type[] types;
			try
			{
				types = asm.GetTypes();
			}
			catch (ReflectionTypeLoadException e)
			{
				types = e.Types ?? Array.Empty<Type>();
			}
			catch
			{
				continue;
			}

			for (var ya = 0; ya < types.Length; ya++)
			{
				var t = types[ya];
				if (t == null || t == typeof(BhUnitWindowPreview))
					continue;

				var typeName = t.FullName ?? t.Name ?? string.Empty;
				if (!LooksLikeAlternatePreviewDeclaringType(typeName))
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
					if (m == null || !m.ReturnType.Equals(clbRt) || m.ContainsGenericParameters || m.IsSpecialName)
						continue;

					var ps = m.GetParameters();
					if (ps.Length > 14)
						continue;
					if (!LooksFactoryLikeName(m.Name, typeName))
						continue;

					yield return m;
				}
			}
		}
	}

	private static bool LooksLikeAlternatePreviewDeclaringType(string fullName)
	{
		if (fullName.IndexOf("Preview", StringComparison.OrdinalIgnoreCase) < 0)
			return false;
		return fullName.IndexOf("BhUnit", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("BhArmy", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("Army", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("Recruit", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("Hire", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("Mercen", StringComparison.OrdinalIgnoreCase) >= 0
		       || fullName.IndexOf("Garrison", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool LooksFactoryLikeName(string methodName, string typeName)
	{
		if (string.IsNullOrEmpty(methodName))
			return false;
		if (methodName.StartsWith("get_", StringComparison.Ordinal) || methodName.StartsWith("set_", StringComparison.Ordinal))
			return false;

		if (typeName.IndexOf("BhUnitPreviews", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;

		foreach (var s in PreviewFactoryVerbHints)
		{
			if (methodName.IndexOf(s, StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		foreach (var s in PreviewFactoryVerbHints)
		{
			if (typeName.IndexOf(s, StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	private static readonly string[] PreviewFactoryVerbHints =
	{
		"beeg",
		"htf",
		"hqr",
		"hqv",
		"hqq",
		"hqs",
		"Show",
		"Get",
		"Create",
		"Load",
		"Build",
		"Make",
		"Spawn",
		"Factory",
		"Rent",
		"Pick",
		"Lease"
	};

	private static void PostfixClbFactory(MethodBase __originalMethod, object[] __args, ref clb __result)
	{
		if (__result == null)
			return;

		string key = null;
		if (__args != null)
		{
			for (var i = 0; i < __args.Length && key == null; i++)
			{
				switch (__args[i])
				{
					case UnitViewConfig uvc:
						key = PreviewKeyFromViewConfig(uvc);
						break;
					case string s when !string.IsNullOrWhiteSpace(s) && LooksLikeSpawnOrSid(s):
						key = s;
						break;
				}
			}
			if (key == null)
			{
				for (var i = 0; i < __args.Length && key == null; i++)
					if (__args[i] is string s && !string.IsNullOrWhiteSpace(s))
						key = s;
			}
		}

		if (string.IsNullOrWhiteSpace(key))
			return;

		var source = (__originalMethod?.DeclaringType?.FullName ?? "?") + "." + (__originalMethod?.Name ?? "?") + "(clbfactory)";
		Homm3ImportUnitPreviewModelHook.TryApplyFromExternalDiscovery(__result, key, source);
	}

	private static string PreviewKeyFromViewConfig(UnitViewConfig viewConfig)
	{
		if (viewConfig == null)
			return null;
		if (!string.IsNullOrEmpty(viewConfig.mesh))
			return viewConfig.mesh;
		if (!string.IsNullOrEmpty(viewConfig.mapMesh))
			return viewConfig.mapMesh;
		return null;
	}

	private static bool LooksLikeSpawnOrSid(string s)
	{
		if (s.Length < 3)
			return false;
		if (s.IndexOf('/') >= 0 || s.IndexOf('\\') >= 0)
			return true;
		var lower = s.ToLowerInvariant();
		return lower.EndsWith("griffin", StringComparison.Ordinal) || lower.Contains("humans/");
	}
}
#endif
