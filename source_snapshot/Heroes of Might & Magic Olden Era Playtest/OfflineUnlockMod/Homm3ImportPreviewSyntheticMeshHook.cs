using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// <c>BhUnitPreviews.hqv(UnitViewConfig)</c> loads <c>UnitViewConfig.mesh</c> through helper <c>cnn.sgk</c>,
/// not through the battle pool or <c>ResManager.Get&lt;GameObject&gt;</c>. Synthetic HoMM3 paths therefore fail
/// before the existing <c>clb</c> preview postfix can replace the model. This hook supplies the bundle battle
/// prefab for those synthetic paths so the normal preview factory can finish.
/// </summary>
internal static class Homm3ImportPreviewSyntheticMeshHook
{
	private static bool _patched;
	private static int _loggedSupply;
	private static int _loggedRecruitmentSkip;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		try
		{
			var boolTargets = new List<MethodInfo>();
			var voidTargets = new List<MethodInfo>();
			var unsupportedTargets = new List<string>();
			var seenMethods = new List<string>();
			var seenTypes = new List<string>();
			foreach (var t in EnumeratePreviewLoaderTypes())
			{
				if (t == null)
					continue;
				seenTypes.Add((t.Assembly.GetName().Name ?? "?") + ":" + (t.FullName ?? t.Name));
				foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
				{
					if (m.Name == "sgk" || LooksLikePreviewMeshLoader(m))
						seenMethods.Add(DescribeMethod(m));
					if (!LooksLikePreviewMeshLoader(m))
						continue;
					if (IsBoolish(m.ReturnType))
						boolTargets.Add(m);
					else if (IsVoidish(m.ReturnType))
						voidTargets.Add(m);
					else
						unsupportedTargets.Add(DescribeMethod(m));
				}
			}

			if (boolTargets.Count == 0 && voidTargets.Count == 0)
			{
				log?.LogWarning(
					"Homm3Import preview synthetic mesh: no supported cnn.sgk preview mesh loader found. "
					+ "cnn types seen="
					+ (seenTypes.Count == 0 ? "(none)" : string.Join("; ", seenTypes))
					+ "; sgk candidates="
					+ (seenMethods.Count == 0 ? "(none)" : string.Join("; ", seenMethods))
					+ "; unsupported="
					+ (unsupportedTargets.Count == 0 ? "(none)" : string.Join("; ", unsupportedTargets)));
				return;
			}

			var boolPrefix = new HarmonyMethod(typeof(Homm3ImportPreviewSyntheticMeshHook), nameof(PrefixSgkBool));
			foreach (var target in boolTargets)
				h.Patch(target, prefix: boolPrefix);

			var voidPrefix = new HarmonyMethod(typeof(Homm3ImportPreviewSyntheticMeshHook), nameof(PrefixSgkVoid));
			foreach (var target in voidTargets)
				h.Patch(target, prefix: voidPrefix);

			_patched = true;
			log?.LogInfo(
				"Homm3Import preview synthetic mesh: Harmony prefix on "
				+ boolTargets.Count
				+ " bool and "
				+ voidTargets.Count
				+ " void cnn.sgk loader method(s).");
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3Import preview synthetic mesh hook failed: " + ex);
		}
	}

	private static IEnumerable<Type> EnumeratePreviewLoaderTypes()
	{
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		for (var ai = 0; ai < assemblies.Length; ai++)
		{
			var asm = assemblies[ai];
			if (asm == null)
				continue;
			var an = asm.GetName().Name ?? string.Empty;
			if (!LooksRelevantAssembly(an))
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
				if (t == null)
					continue;
				if (string.Equals(t.Name, "cnn", StringComparison.Ordinal)
				    || string.Equals(t.FullName, "cnn", StringComparison.Ordinal)
				    || TypeHasPreviewMeshLoader(t))
					yield return t;
			}
		}
	}

	private static bool TypeHasPreviewMeshLoader(Type type)
	{
		if (type == null)
			return false;
		try
		{
			foreach (var m in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
			{
				if (LooksLikePreviewMeshLoader(m))
					return true;
			}
		}
		catch
		{
			return false;
		}
		return false;
	}

	private static bool LooksRelevantAssembly(string name)
	{
		return string.Equals(name, "Hex", StringComparison.Ordinal)
		       || string.Equals(name, "Assembly-CSharp", StringComparison.Ordinal)
		       || string.Equals(name, "Hex.Shared", StringComparison.Ordinal)
		       || string.Equals(name, "Hex.ResManager", StringComparison.Ordinal);
	}

	private static bool LooksLikePreviewMeshLoader(MethodInfo m)
	{
		if (m == null)
			return false;
		var ps = m.GetParameters();
		if (ps.Length != 5)
			return false;
		if (!IsStringish(ps[0].ParameterType))
			return false;
		if (!IsByRefOf(ps[1].ParameterType, typeof(GameObject), "GameObject"))
			return false;
		if (!IsFloatish(ps[2].ParameterType))
			return false;
		if (!IsTypeLike(ps[3].ParameterType, typeof(Transform), "Transform"))
			return false;
		return IsIntish(ps[4].ParameterType);
	}

	private static bool IsByRefOf(Type t, Type exact, string name)
	{
		if (t == null || !t.IsByRef)
			return false;
		return IsTypeLike(t.GetElementType(), exact, name);
	}

	private static bool IsTypeLike(Type t, Type exact, string name)
	{
		if (t == null)
			return false;
		return t == exact || t.Name == name || t.FullName == exact.FullName;
	}

	private static bool IsStringish(Type t) =>
		t == typeof(string) || t?.FullName == "System.String" || t?.Name == "String";

	private static bool IsFloatish(Type t) =>
		t == typeof(float) || t?.FullName == "System.Single" || t?.Name == "Single";

	private static bool IsIntish(Type t) =>
		t == typeof(int) || t?.FullName == "System.Int32" || t?.Name == "Int32";

	private static bool IsBoolish(Type t) =>
		t == typeof(bool) || t?.FullName == "System.Boolean" || t?.Name == "Boolean";

	private static bool IsVoidish(Type t) =>
		t == typeof(void) || t?.FullName == "System.Void" || t?.Name == "Void";

	private static string DescribeMethod(MethodInfo m)
	{
		if (m == null)
			return "?";
		var ps = m.GetParameters();
		var parts = new string[ps.Length];
		for (var i = 0; i < ps.Length; i++)
			parts[i] = DescribeType(ps[i].ParameterType);
		return DescribeType(m.ReturnType)
		       + " "
		       + (m.DeclaringType?.FullName ?? "?")
		       + "."
		       + m.Name
		       + "("
		       + string.Join(", ", parts)
		       + ")";
	}

	private static string DescribeType(Type t)
	{
		if (t == null)
			return "?";
		if (!t.IsByRef)
			return t.FullName ?? t.Name;
		var e = t.GetElementType();
		return (e?.FullName ?? e?.Name ?? "?") + "&";
	}

	private static bool PrefixSgkBool(string a, ref GameObject b, float c, Transform d, int e, ref bool __result)
	{
		if (!TrySupply(a, ref b, c, d, e))
			return true;
		__result = true;
		return false;
	}

	private static bool PrefixSgkVoid(string a, ref GameObject b, float c, Transform d, int e)
	{
		return !TrySupply(a, ref b, c, d, e);
	}

	private static bool TrySupply(string a, ref GameObject b, float c, Transform d, int e)
	{
		var fromHqv = StackContainsHqv();
		if (!TryResolvePreviewSupplyEntry(a, fromHqv, out var entry))
			return false;

		if (ShouldSupplyEmptyRecruitmentPlaceholder(entry, fromHqv, out var stackHint))
		{
			return SupplyEmptyRecruitmentPlaceholder(a, ref b, c, d, e, stackHint);
		}

		if (!Homm3ImportVisuals.TryGetBattleTemplate(entry, Plugin.LogSource, out var template) || !template)
		{
			Plugin.LogSource?.LogWarning("Homm3Import preview synthetic mesh: no battle template for '" + a + "'.");
			return false;
		}

		try
		{
			var instance = UnityEngine.Object.Instantiate(template);
			if (!instance)
				return false;
			instance.name = template.name;
			if (d)
				instance.transform.SetParent(d, false);
			var skinnedLane = Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance);
			if (skinnedLane)
			{
				// This prefix replaces the native loader, whose caller then writes sign * c (the unit's view scale)
				// onto the prefab's first child and zeroes the root position: frame at battle size with that write
				// already applied, feet planted on the wrap (Homm3OwnedSkinnedPreviewFraming).
				Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, entry, null, keepPose: false, c, "preview-synthetic", Plugin.LogSource);
			}
			else if (c > 0f && !float.IsNaN(c) && !float.IsInfinity(c))
				instance.transform.localScale *= c;
			ApplyLayerRecursive(instance.transform, e);
			instance.SetActive(true);
			if (skinnedLane)
				Homm3ImportVisuals.PrepareOwnedSkinnedIdleInstance(instance, entry, Plugin.LogSource);
			b = instance;
			LogSupply(a, instance, c, e);
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import preview synthetic mesh TrySupply failed for '" + a + "': " + ex);
			return false;
		}
	}

	private static bool TryResolvePreviewSupplyEntry(string pathOrSid, bool fromHqv, out Homm3ImportVisuals.Entry entry)
	{
		if (TryResolveSyntheticPreviewEntry(pathOrSid, out entry))
			return true;
		if (!fromHqv)
			return false;
		if (!Homm3ImportUnitPreviewModelHook.TryResolveActiveRecruitmentCustomSid(pathOrSid, out var customSid)
		    && !Homm3ImportUnitPreviewModelHook.TryResolveActiveRecruitmentCustomSid(PreviewPathLeaf(pathOrSid), out customSid))
			return false;
		return Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(customSid, Plugin.LogSource, out entry)
		       && Homm3ImportVisuals.IsOwnedSkinnedBattleEntry(entry);
	}

	private static bool TryResolveSyntheticPreviewEntry(string pathOrSid, out Homm3ImportVisuals.Entry entry)
	{
		entry = null;
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(pathOrSid, Plugin.LogSource, out entry)
		    && Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(entry))
			return true;
		if (string.IsNullOrWhiteSpace(pathOrSid))
			return false;
		var sid = PreviewPathLeaf(pathOrSid);
		return Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(sid, Plugin.LogSource, out entry)
		       && Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(entry);
	}

	private static string PreviewPathLeaf(string pathOrSid)
	{
		if (string.IsNullOrWhiteSpace(pathOrSid))
			return pathOrSid;
		var sid = pathOrSid.Trim().Replace('\\', '/');
		var slash = sid.LastIndexOf('/');
		if (slash >= 0)
			sid = sid[(slash + 1)..];
		if (sid.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			sid = sid[..^7];
		if (sid.EndsWith("_map", StringComparison.OrdinalIgnoreCase))
			sid = sid[..^4];
		return sid;
	}

	private static void ApplyLayerRecursive(Transform t, int layer)
	{
		if (t == null || layer < 0 || layer > 31)
			return;
		t.gameObject.layer = layer;
		for (var i = 0; i < t.childCount; i++)
			ApplyLayerRecursive(t.GetChild(i), layer);
	}

	private static void LogSupply(string path, GameObject instance, float scale, int layer)
	{
		if (_loggedSupply >= 32)
			return;
		_loggedSupply++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import preview synthetic mesh: supplied '"
			+ path
			+ "' with '"
			+ (instance ? instance.name : "?")
			+ "' scaleArg="
			+ scale.ToString("0.###")
			+ " layerArg="
			+ layer
			+ ".");
	}

	private static bool ShouldSupplyEmptyRecruitmentPlaceholder(Homm3ImportVisuals.Entry entry, bool fromHqv, out string stackHint)
	{
		stackHint = null;
		if (!IsClearlyRecruitmentOrUpgradeUiRequest(out stackHint, out var sharedStart, out var hireInit))
			return false;
		// BhUnitPreviews.hqv is the Idle-mesh factory. Init/Start dummies stay empty.
		// Treating hqv as empty just because Init is also on the stack left town hire on dungeon donors.
		if (fromHqv && Homm3ImportVisuals.IsOwnedSkinnedBattleEntry(entry))
			return false;
		if (sharedStart || hireInit)
			return true;
		if (Homm3ImportVisuals.IsOwnedSkinnedBattleEntry(entry))
			return false;
		return true;
	}

	private static bool StackContainsHqv()
	{
		try
		{
			var frames = new StackTrace(false).GetFrames();
			if (frames == null)
				return false;
			for (var i = 0; i < frames.Length; i++)
			{
				var method = frames[i]?.GetMethod();
				if (method == null)
					continue;
				var typeName = method.DeclaringType?.FullName ?? string.Empty;
				if (typeName.IndexOf("BhUnitPreviews", StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				if (LooksLikeIdleMeshFactoryMethod(method.Name))
					return true;
			}
			return false;
		}
		catch
		{
			return false;
		}
	}

	private static bool LooksLikeIdleMeshFactoryMethod(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		if (string.Equals(name, "hqv", StringComparison.OrdinalIgnoreCase))
			return true;
		foreach (var hint in GameSymbols.UnitPreview.SharedPreviewFactory.NameHints)
		{
			if (string.Equals(name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool IsClearlyRecruitmentOrUpgradeUiRequest(out string stackHint, out bool sharedStart, out bool hireInit)
	{
		stackHint = null;
		sharedStart = false;
		hireInit = false;
		try
		{
			var frames = new StackTrace(false).GetFrames();
			if (frames == null)
				return false;

			var sawRecruitment = false;
			for (var i = 0; i < frames.Length; i++)
			{
				var method = frames[i]?.GetMethod();
				if (method == null)
					continue;
				var typeName = method.DeclaringType?.FullName ?? string.Empty;
				var sig = typeName + "." + method.Name;
				if (sig.IndexOf("BhUnitWindowPreview", StringComparison.OrdinalIgnoreCase) >= 0)
				{
					stackHint = sig;
					sharedStart = false;
					hireInit = false;
					return false;
				}
				if (!LooksLikeRecruitmentOrUpgradeUiFrame(sig))
					continue;
				if (stackHint == null)
					stackHint = sig;
				sawRecruitment = true;
				if (typeName.IndexOf("BhUnitPreviews", StringComparison.OrdinalIgnoreCase) >= 0
				    && (method.Name == "Start"
				        || string.Equals(method.Name, "sry", StringComparison.Ordinal)
				        || string.Equals(method.Name, "spp", StringComparison.Ordinal)))
					sharedStart = true;
				if (sig.IndexOf("BhHireUnitItemView", StringComparison.OrdinalIgnoreCase) >= 0
				    && string.Equals(method.Name, "Init", StringComparison.Ordinal))
					hireInit = true;
			}
			return sawRecruitment;
		}
		catch
		{
			return false;
		}
	}

	private static bool LooksLikeRecruitmentOrUpgradeUiFrame(string sig)
	{
		if (string.IsNullOrEmpty(sig))
			return false;
		return sig.IndexOf("BhHireUnit", StringComparison.OrdinalIgnoreCase) >= 0
		       || sig.IndexOf("HireUnitItemView", StringComparison.OrdinalIgnoreCase) >= 0
		       || sig.IndexOf("HireUnitAbility", StringComparison.OrdinalIgnoreCase) >= 0
		       || sig.IndexOf("BhUnitPreviews", StringComparison.OrdinalIgnoreCase) >= 0
		       || (sig.IndexOf("Upgrade", StringComparison.OrdinalIgnoreCase) >= 0
		           && sig.IndexOf(".City.", StringComparison.OrdinalIgnoreCase) >= 0
		           && sig.IndexOf("Unit", StringComparison.OrdinalIgnoreCase) >= 0);
	}

	private static void LogRecruitmentSkip(string path, float scale, Transform parent, int layer, string stackHint)
	{
		if (_loggedRecruitmentSkip >= 32)
			return;
		_loggedRecruitmentSkip++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import preview synthetic mesh: supplied empty recruitment/upgrade UI placeholder for '"
			+ path
			+ "' scaleArg="
			+ scale.ToString("0.###")
			+ " layerArg="
			+ layer
			+ " parent='"
			+ (parent ? parent.name : "(null)")
			+ "' stack='"
			+ (stackHint ?? "?")
			+ "'.");
	}

	private static bool SupplyEmptyRecruitmentPlaceholder(
		string path,
		ref GameObject result,
		float scale,
		Transform parent,
		int layer,
		string stackHint)
	{
		try
		{
			var placeholder = new GameObject("HOMM3_recruitment_preview_placeholder");
			if (parent)
				placeholder.transform.SetParent(parent, false);

			// BhUnitPreviews.hqv assumes the loaded mesh root has at least one child.
			// Keep the city hire/upgrade preview visually empty, but preserve that shape.
			var child = new GameObject("empty_mesh_child");
			child.transform.SetParent(placeholder.transform, false);

			if (scale > 0f && !float.IsNaN(scale) && !float.IsInfinity(scale))
				placeholder.transform.localScale *= scale;
			ApplyLayerRecursive(placeholder.transform, layer);
			placeholder.SetActive(true);
			result = placeholder;
			LogRecruitmentSkip(path, scale, parent, layer, stackHint);
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(
				"Homm3Import preview synthetic mesh: empty recruitment placeholder failed for '"
				+ path
				+ "': "
				+ ex.Message);
			return false;
		}
	}
}
