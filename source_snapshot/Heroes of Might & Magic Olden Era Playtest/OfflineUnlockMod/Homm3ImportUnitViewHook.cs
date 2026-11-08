using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Lane B: <c>UnitViewConfig</c> map-loader postfix for <c>homm3_import.json</c> map paths (mirrors <see cref="EsquirePikemanUnitViewHook"/>).
/// </summary>
internal static class Homm3ImportUnitViewHook
{
	private sealed class MapMeshLoaderState
	{
		internal string OriginalMapMesh;
		internal Homm3ImportVisuals.Entry Entry;
		internal string ResolveRoute;
		internal bool SubstitutedMapShell;
		internal bool DirectMapArrayShellCreated;
	}

	private static bool _patched;

	internal static void ResetHarmonyGuardForHotReload()
	{
		_patched = false;
	}

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
				throw new InvalidOperationException("Harmony was not initialized before required UnitView map-loader registration.");
			return;
		}
		try
		{
			if (required)
				Homm3ImportVisuals.RequireLoadedEntriesForReleaseSafeFeature(log, "UnitView map swap");

			var t = typeof(ObjCityConfig).Assembly.GetType("Hex.Configs.UnitViewConfig", throwOnError: false);
			if (t == null)
			{
				HandleMissing(required, "UnitViewConfig type not found.");
				return;
			}

			var mapMeshLoader = FindMapMeshLoader(t);

			if (mapMeshLoader == null)
			{
				HandleMissing(required, "UnitViewConfig map GameObject loader not found in centralized symbol hints.");
				return;
			}

			var prefix = typeof(Homm3ImportUnitViewHook).GetMethod(nameof(PrefixMapMeshLoader), BindingFlags.Static | BindingFlags.NonPublic);
			var postfix = typeof(Homm3ImportUnitViewHook).GetMethod(nameof(PostfixMapMeshLoader), BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(mapMeshLoader, prefix, out var prefixReason))
			{
				HandleMissing(required, "UnitViewConfig map loader prefix incompatible with " + mapMeshLoader.Name + ": " + prefixReason);
				return;
			}
			if (!GameMember.IsHarmonyPatchCompatible(mapMeshLoader, postfix, out var postfixReason))
			{
				HandleMissing(required, "UnitViewConfig map loader postfix incompatible with " + mapMeshLoader.Name + ": " + postfixReason);
				return;
			}

			h.Patch(
				mapMeshLoader,
				prefix: new HarmonyMethod(typeof(Homm3ImportUnitViewHook), nameof(PrefixMapMeshLoader)),
				postfix: new HarmonyMethod(typeof(Homm3ImportUnitViewHook), nameof(PostfixMapMeshLoader)));
			_patched = true;
			log?.LogInfo(
				"Homm3Import: Harmony postfix on "
				+ mapMeshLoader.DeclaringType?.FullName
				+ "."
				+ mapMeshLoader.Name
				+ "() for "
				+ (required ? "required " : "")
				+ "map swaps.");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogError("Homm3Import UnitView map-loader hook failed: " + ex);
		}
	}

	private static void HandleMissing(bool required, string message)
	{
		if (required)
			throw new InvalidOperationException("required UnitView map-loader surface missing: " + message);
		Plugin.LogSource?.LogWarning("Homm3Import: " + message);
	}

	private static MethodInfo FindMapMeshLoader(Type unitViewConfigType)
	{
		for (var cur = unitViewConfigType; IsUnitViewConfigChainType(cur); cur = cur.BaseType)
		{
			foreach (var hint in GameSymbols.UnitViewConfig.MapMeshLoader.NameHints)
			{
				if (string.IsNullOrWhiteSpace(hint))
					continue;
				foreach (var method in cur.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
				{
					if (!IsMapMeshLoaderShape(method) || method.Name != hint)
						continue;
					return method;
				}
			}

			MethodInfo best = null;
			foreach (var method in cur.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				if (!IsMapMeshLoaderShape(method))
					continue;
				if (best == null || CompareMapMeshLoaderRank(method, best) < 0)
					best = method;
			}
			if (best != null)
				return best;
		}

		return null;
	}

	private static bool IsUnitViewConfigChainType(Type type)
	{
		if (type == null || type == typeof(object))
			return false;
		var fullName = type.FullName ?? string.Empty;
		return !fullName.StartsWith("System.", StringComparison.Ordinal)
		       && !fullName.StartsWith("Il2CppSystem.", StringComparison.Ordinal);
	}

	private static bool IsMapMeshLoaderShape(MethodInfo method)
	{
		if (method == null || method.IsStatic || method.IsSpecialName)
			return false;
		if (method.GetParameters().Length != 0)
			return false;
		if (method.Name.StartsWith("get_", StringComparison.Ordinal)
		    || method.Name.StartsWith("set_", StringComparison.Ordinal))
			return false;
		return GameInteropTypes.TypesMatch(method.ReturnType, typeof(GameObject));
	}

	private static int CompareMapMeshLoaderRank(MethodInfo a, MethodInfo b)
	{
		int Score(MethodInfo method)
		{
			if (method == null)
				return int.MaxValue;
			var score = 0;
			if (!method.IsPublic)
				score += 100;
			if (method.Name.Contains("_PDM_", StringComparison.Ordinal))
				score += 50;
			if (!method.Name.StartsWith("Method_", StringComparison.Ordinal))
				score += 200;
			var match = System.Text.RegularExpressions.Regex.Match(method.Name, @"_(\d+)$");
			if (match.Success && int.TryParse(match.Groups[1].Value, out var ordinal))
				score += ordinal;
			return score;
		}
		return Score(a).CompareTo(Score(b));
	}

	private static bool PrefixMapMeshLoader(UnitViewConfig __instance, ref MapMeshLoaderState __state, ref GameObject __result)
	{
		if (__instance == null)
			return true;
		try
		{
			Homm3MapLoadFlightRecorder.Mark("unitview.prefix.enter");
			if (Homm3MapLoadFlightRecorder.DisableUnitViewMapSwaps)
			{
				Homm3MapLoadFlightRecorder.Mark("unitview.prefix.disabled", Homm3MapLoadFlightRecorder.DisableUnitViewMapSwapsFlag);
				return true;
			}
			var mapMeshRaw = DeobfInteropCompat.GetUnitViewConfigMapMesh(__instance);
			if (string.IsNullOrEmpty(mapMeshRaw))
				return true;
			var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(mapMeshRaw);
			var unitId = DeobfInteropCompat.GetConfigElementId(__instance)
			             ?? DeriveHomm3UnitSidFromImportMapPath(unitsPath);
			var entry = ResolveMapEntryForUnitView(unitsPath, unitId, out var route);
			if (entry == null || !entry.SwapAdventureMap)
				return true;
			if (!RouteAllowsEntry(route, entry, unitId))
				return true;
			__state = new MapMeshLoaderState { OriginalMapMesh = mapMeshRaw, Entry = entry, ResolveRoute = route };
			Homm3MapLoadFlightRecorder.Mark(
				"unitview.prefix.resolved",
				"unitId=" + (unitId ?? "?")
				+ " route=" + (route ?? "?")
				+ " mapMesh=" + mapMeshRaw
				+ " bundle=" + (entry.BundleName ?? "?"));

			if (!Homm3MapLoadFlightRecorder.UnitViewVanillaShellOnly
			    && !Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnly
			    && Homm3ImportVisuals.TryCreateDirectMapArrayShellPrefabForAdventure(entry, Plugin.LogSource, out var directShell)
			    && directShell)
			{
				__state.DirectMapArrayShellCreated = true;
				__result = directShell;
				Homm3MapLoadFlightRecorder.MarkGameObject("unitview.prefix.direct-map-array-shell", directShell, "unitId=" + (unitId ?? "?"), census: true);
				return false;
			}

			if (Homm3ImportVisuals.IsSyntheticHomm3ImportUnitsPath(unitsPath)
			    && !string.IsNullOrEmpty(entry.MapShellNorm))
			{
				if (Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnly)
				{
					Homm3MapLoadFlightRecorder.Mark("unitview.prefix.no-shell-substitution", Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnlyFlag);
				}
				else
				{
					DeobfInteropCompat.SetUnitViewConfigMapMesh(__instance, ToUnitViewConfigPath(entry.MapShellNorm));
					__state.SubstitutedMapShell = true;
					Homm3MapLoadFlightRecorder.Mark("unitview.prefix.substituted-shell", "shell=" + entry.MapShellNorm);
				}
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import UnitViewHook PrefixMapMeshLoader: " + ex);
		}
		return true;
	}

	private static void PostfixMapMeshLoader(UnitViewConfig __instance, MapMeshLoaderState __state, ref GameObject __result)
	{
		if (__instance == null)
			return;
		try
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.enter", __result);
			if (Homm3MapLoadFlightRecorder.DisableUnitViewMapSwaps)
			{
				Homm3MapLoadFlightRecorder.Mark("unitview.postfix.disabled", Homm3MapLoadFlightRecorder.DisableUnitViewMapSwapsFlag);
				return;
			}
			var mapMeshRaw = __state?.OriginalMapMesh ?? DeobfInteropCompat.GetUnitViewConfigMapMesh(__instance);
			if (__state != null && __state.SubstitutedMapShell)
				DeobfInteropCompat.SetUnitViewConfigMapMesh(__instance, __state.OriginalMapMesh);
			if (__state != null && __state.DirectMapArrayShellCreated)
			{
				Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.direct-map-array-shell", __result, "unitId=" + (DeriveHomm3UnitSidFromImportMapPath(EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(mapMeshRaw)) ?? "?"), census: true);
				return;
			}
			if (string.IsNullOrEmpty(mapMeshRaw))
				return;
			var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(mapMeshRaw);
			var unitId = DeobfInteropCompat.GetConfigElementId(__instance)
			             ?? DeriveHomm3UnitSidFromImportMapPath(unitsPath);
			var entry = __state?.Entry;
			var route = __state?.ResolveRoute;
			if (entry == null)
				entry = ResolveMapEntryForUnitView(unitsPath, unitId, out route);
			if (entry == null)
				return;
			if (!entry.SwapAdventureMap)
				return;
			if (!RouteAllowsEntry(route, entry, unitId))
				return;
			Homm3MapLoadFlightRecorder.MarkGameObject(
				"unitview.postfix.resolved",
				__result,
				"unitId=" + (unitId ?? "?")
				+ " route=" + (route ?? "?")
				+ " mapMesh=" + mapMeshRaw
				+ " bundle=" + (entry.BundleName ?? "?"));
			if (Homm3MapLoadFlightRecorder.UnitViewVanillaShellOnly)
			{
				Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.vanilla-shell-only", __result, Homm3MapLoadFlightRecorder.UnitViewVanillaShellOnlyFlag, census: true);
				return;
			}
			if (Homm3ImportVisuals.LooksLikeHomm3NativeShellMapPrefab(__result))
			{
				Homm3ImportVisuals.TryGetMapTemplate(entry, Plugin.LogSource, out var existingTemplate);
				if (Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnly)
				{
					if (existingTemplate)
					{
						__result = existingTemplate;
						Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.homm3-visual-only.existing-template", __result, Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnlyFlag, census: true);
					}
					return;
				}
				Homm3ImportVisuals.RefreshNativeShellMapPrefabForAdventure(__result, existingTemplate, entry, Plugin.LogSource);
				return;
			}

			if (!Homm3ImportVisuals.TryGetMapTemplate(entry, Plugin.LogSource, out var template) || template == null)
				return;
			if (Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnly)
			{
				__result = template;
				Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.homm3-visual-only.template", __result, Homm3MapLoadFlightRecorder.UnitViewHomm3VisualOnlyFlag, census: true);
				return;
			}

			var vanilla = __result;
			if (!vanilla && Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(entry))
				Homm3ImportVisuals.TryGetMapShellTemplate(entry, Plugin.LogSource, out vanilla);
			Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.create-native-shell.start", vanilla, "unitId=" + (unitId ?? "?"), census: true);
			__result = Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure(vanilla, template, entry, Plugin.LogSource);
			Homm3MapLoadFlightRecorder.MarkGameObject("unitview.postfix.create-native-shell.end", __result, "unitId=" + (unitId ?? "?"), census: true);
			Plugin.LogSource?.LogInfo("Homm3Import UnitViewHook: swapped unitId='" + (unitId ?? "?") + "' map mesh '" + unitsPath + "' route='" + (route ?? "?") + "' using native shell.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import UnitViewHook PostfixMapMeshLoader: " + ex);
		}
	}

	private static string ToUnitViewConfigPath(string unitsPath)
	{
		if (string.IsNullOrWhiteSpace(unitsPath))
			return unitsPath;
		var p = unitsPath.Trim().Replace('\\', '/');
		const string prefix = "units/";
		if (p.StartsWith(prefix, StringComparison.Ordinal))
			p = p.Substring(prefix.Length);
		return p;
	}

	private static Homm3ImportVisuals.Entry ResolveMapEntryForUnitView(string unitsPath, string unitSid, out string route)
	{
		route = null;
		if (!string.IsNullOrEmpty(unitsPath) && Homm3ImportVisuals.TryResolveHomm3MapEntry(unitsPath, out var entry) && entry != null)
		{
			route = "map-path";
			return entry;
		}
		if (!string.IsNullOrWhiteSpace(unitSid)
		    && unitSid.Trim().StartsWith("h3_", StringComparison.Ordinal)
		    && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(unitSid, Plugin.LogSource, out entry)
		    && entry != null)
		{
			route = "unit-sid";
			return entry;
		}
		return null;
	}

	private static bool RouteAllowsEntry(string route, Homm3ImportVisuals.Entry entry, string unitSid)
	{
		if (entry == null)
			return false;
		if (string.Equals(route, "map-path", StringComparison.Ordinal))
			return true;
		return Homm3ImportVisuals.EntryAllowsGameUnitSid(entry, unitSid);
	}

	private static string DeriveHomm3UnitSidFromImportMapPath(string unitsPath)
	{
		if (string.IsNullOrWhiteSpace(unitsPath))
			return null;
		const string marker = "homm3_import/";
		var normalized = unitsPath.Trim().Replace('\\', '/');
		var markerIndex = normalized.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
		if (markerIndex < 0)
			return null;
		var tail = normalized.Substring(markerIndex + marker.Length);
		var slashIndex = tail.LastIndexOf('/');
		if (slashIndex < 0 || slashIndex >= tail.Length - 1)
			return null;
		var file = tail.Substring(slashIndex + 1);
		if (file.EndsWith("_map", StringComparison.Ordinal))
			file = file.Substring(0, file.Length - 4);
		return file.StartsWith("h3_", StringComparison.Ordinal) ? file : null;
	}

}
