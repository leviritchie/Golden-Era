using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class CustomUnitViewRouting
{
	/// <summary>Hex game logic (<c>Hex.dll</c> interop) — all config/session types resolve here.</summary>
	internal static readonly Assembly GameAssembly = typeof(UnitViewConfig).Assembly;

	private sealed class Route
	{
		internal string UnitSid;
		internal string ExportFolderName;
		internal string MeshKey;
		internal string RuntimeMesh;
		internal string MapMeshKey;
		internal string RuntimeMapMesh;
	}

	private static readonly Route[] Routes =
	{
		new()
		{
			UnitSid = "esquire",
			ExportFolderName = "crewmate",
			MeshKey = "Custom/esquire_prototype",
			RuntimeMesh = "Neutral/1Prefabs/halfling",
			MapMeshKey = "Custom/esquire_prototype_map",
			RuntimeMapMesh = "Neutral/1Prefabs/halfling_map"
		}
	};

	private static readonly Dictionary<string, string> MeshRoutes = Routes
		.ToDictionary(route => route.MeshKey, route => route.RuntimeMesh, StringComparer.Ordinal);

	private static readonly Dictionary<string, string> MapMeshRoutes = Routes
		.ToDictionary(route => route.MapMeshKey, route => route.RuntimeMapMesh, StringComparer.Ordinal);

	private static readonly HashSet<string> LoggedRoutes = new(StringComparer.Ordinal);
	private static bool _loggedInitialization;
	private static PropertyInfo _unitViewConfigProperty;
	private static bool _donorMeshAppliedToDb;
	private static bool _warnedDbUnitViewsListUnavailable;

	internal static void ApplyRoutes()
	{
		BhUnitPreviewsMeshRewritePatch.TryInstall(Plugin.HarmonyInstance, logIfUnavailable: true);
		ResManagerGetGameObjectUnitsPathPatch.TryInstall(Plugin.HarmonyInstance);
		UiModelsSpawnerSpawnMeshRewritePatch.TryInstall(Plugin.HarmonyInstance, logIfUnavailable: true);
		TempleSwordsmanBillboardPrototype.ResetBattleContext();
		// Do not call EnsureBattlePatchesInstalled() here: reflection often picks the wrong FieldObjectDrawer subtype
		// (multiple Init(UnitViewConfig,…) types), sets _battlePatchesInstalled, then battle Unit.Listen skips the real UnitDrawer.
		// Billboard patches install from BattleUnitListenBillboardBootstrapPatch with listener.GetType() instead.
		BattleUnitListenBillboardBootstrapPatch.TryInstall(Plugin.HarmonyInstance);
		ReflectionIterationProbe.TryWrite(Path.GetDirectoryName(typeof(Plugin).Assembly.Location));
		ApplyDonorMeshKeysToDatabaseOnce();

		if (_loggedInitialization)
		{
			return;
		}

		_loggedInitialization = true;
		Plugin.LogSource?.LogInfo(
			$"Custom unit view routing initialized with {MeshRoutes.Count} battle mesh route(s) and {MapMeshRoutes.Count} map mesh route(s).");
	}

	/// <summary>
	/// Mutate loaded unit view configs so mesh/mapMesh never reference missing <c>units/Custom/...</c> assets during
	/// adventure-map / UI load. Avoids installing Harmony on ResManager during map session (prevents loader/UI hangs).
	/// Layout is fixed in game code: <c>Hex.Configs.DB.me.unitViews.list</c> where <c>unitViews</c> is
	/// <c>ConfigsArrayLoader&lt;UnitViewConfig,string&gt;</c> with <c>public List&lt;T&gt; list</c> (see il2cpp dump /
	/// <c>demo_hex_all.txt</c> around ConfigsArrayLoader / DB). Il2CppInterop may not expose <c>DB</c> as a compilable
	/// type from <c>Hex.dll</c>, so we resolve <c>Hex.Configs.DB</c> via <see cref="UnitViewConfig"/>'s assembly.
	/// Safe to call multiple times (runs once successfully).
	/// </summary>
	internal static void ApplyDonorMeshKeysToDatabaseOnce()
	{
		if (_donorMeshAppliedToDb)
		{
			return;
		}

		try
		{
			var rawList = TryGetHexConfigsDbUnitViewsListObject();
			if (rawList == null)
			{
				if (!_warnedDbUnitViewsListUnavailable)
				{
					_warnedDbUnitViewsListUnavailable = true;
					Plugin.LogSource?.LogWarning(
						"Custom unit views: could not resolve DB.me.unitViews.list via reflection — " +
						"UiModelsSpawner donor rewrite must carry combat preview loads (see UiModelsSpawner.Spawn patch).");
				}

				return;
			}

			var mutated = 0;
			foreach (var cfg in EnumerateUnitViewConfigs(rawList))
			{
				if (cfg == null)
				{
					continue;
				}

				if (!string.IsNullOrEmpty(cfg.mesh) &&
				    MeshRoutes.TryGetValue(cfg.mesh, out var battleDonor) &&
				    !string.Equals(cfg.mesh, battleDonor, StringComparison.Ordinal))
				{
					LogRoute("db-mesh-donor", cfg.mesh, battleDonor);
					cfg.mesh = battleDonor;
					mutated++;
				}

				if (!string.IsNullOrEmpty(cfg.mapMesh) &&
				    MapMeshRoutes.TryGetValue(cfg.mapMesh, out var mapDonor) &&
				    !string.Equals(cfg.mapMesh, mapDonor, StringComparison.Ordinal))
				{
					LogRoute("db-mapmesh-donor", cfg.mapMesh, mapDonor);
					cfg.mapMesh = mapDonor;
					mutated++;
				}
			}

			if (mutated == 0)
			{
				return;
			}

			_donorMeshAppliedToDb = true;
			Plugin.LogSource?.LogInfo(
				"Custom unit views: donor mesh/mapMesh applied in DB (adventure map avoids ResManager Harmony hook).");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"ApplyDonorMeshKeysToDatabaseOnce failed: {ex.Message}");
		}
	}

	/// <summary>
	/// Returns <c>DB.me.unitViews.list</c>. Game source: <c>namespace Hex.Configs</c> — <c>public class DB</c> with
	/// <c>public static DB me</c> and <c>ConfigsArrayLoader&lt;UnitViewConfig,string&gt; unitViews</c>; loader has
	/// <c>public List&lt;T&gt; list</c>. Il2CppInterop often omits <c>DB</c> from compile-time surface — resolve
	/// <c>Hex.Configs.DB</c> only from <see cref="UnitViewConfig"/>'s assembly (no <c>Hex.DB</c> alternate).
	/// </summary>
	private static object TryGetHexConfigsDbUnitViewsListObject()
	{
		var dbType = GameAssembly.GetType("Hex.Configs.DB", throwOnError: false);
		if (dbType == null)
		{
			return null;
		}

		object dbInstance = dbType.GetProperty("me", BindingFlags.Public | BindingFlags.Static)?.GetValue(null, null);
		if (dbInstance == null &&
		    dbType.GetMethod("Instance", BindingFlags.Public | BindingFlags.Static, null, Type.EmptyTypes, null) is
			    MethodInfo instanceMethod)
		{
			dbInstance = instanceMethod.Invoke(null, null);
		}

		if (dbInstance == null)
		{
			return null;
		}

		var loader = AccessTools.Property(dbType, "unitViews")?.GetValue(dbInstance, null)
			?? AccessTools.Field(dbType, "unitViews")?.GetValue(dbInstance);
		if (loader == null)
		{
			var instType = dbInstance.GetType();
			loader = AccessTools.Property(instType, "unitViews")?.GetValue(dbInstance, null)
				?? AccessTools.Field(instType, "unitViews")?.GetValue(dbInstance);
		}

		if (loader == null)
		{
			return null;
		}

		var loaderType = loader.GetType();
		const BindingFlags ip = BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic;
		var listProp = loaderType.GetProperty("list", ip)
			?? loaderType.GetProperty("List", ip);
		return listProp?.GetValue(loader, null);
	}

	private static IEnumerable<UnitViewConfig> EnumerateUnitViewConfigs(object rawListOrArray)
	{
		if (rawListOrArray == null)
		{
			yield break;
		}

		if (rawListOrArray is IList ilist)
		{
			for (var i = 0; i < ilist.Count; i++)
			{
				if (ilist[i] is UnitViewConfig cfg)
				{
					yield return cfg;
				}
			}

			yield break;
		}

		if (rawListOrArray is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item is UnitViewConfig cfg)
				{
					yield return cfg;
				}
			}

			yield break;
		}

		var type = rawListOrArray.GetType();
		var lengthProp = type.GetProperty("Length", BindingFlags.Public | BindingFlags.Instance)
			?? type.GetProperty("Count", BindingFlags.Public | BindingFlags.Instance);
		var lengthObj = lengthProp?.GetValue(rawListOrArray);
		if (lengthObj is not int len || len <= 0)
		{
			yield break;
		}

		var indexer = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance, null, typeof(object),
			new[] { typeof(int) }, null);
		if (indexer == null)
		{
			yield break;
		}

		for (var i = 0; i < len; i++)
		{
			var item = indexer.GetValue(rawListOrArray, new object[] { i });
			if (item is UnitViewConfig cfg)
			{
				yield return cfg;
			}
		}
	}

	internal static bool TryResolveBattleMesh(string meshKey, out string resolvedMesh)
	{
		if (TempleSwordsmanBillboardPrototype.IsRuntimePrefabRouteInstalled() &&
			TryGetBattlePrefabRequest("units/" + meshKey, out _, out _, out _))
		{
			resolvedMesh = meshKey;
			LogRoute("battle-mesh", meshKey, meshKey);
			return false;
		}

		if (!string.IsNullOrEmpty(meshKey) && MeshRoutes.TryGetValue(meshKey, out resolvedMesh))
		{
			if (!TempleSwordsmanBillboardPrototype.IsRuntimePrefabRouteInstalled())
			{
				Plugin.LogSource?.LogError(
					"Custom unit battle mesh requires the ResManager prefab hook, but it is not installed. " +
					$"Rewriting '{meshKey}' -> '{resolvedMesh}' so battle can load. Fix the hook; this fallback is logged explicitly.");
			}

			LogRoute("battle-mesh", meshKey, resolvedMesh);
			return true;
		}

		resolvedMesh = meshKey;
		return false;
	}

	internal static bool TryResolveBattlePath(string path, out string resolvedPath)
	{
		const string prefix = "units/";
		if (!string.IsNullOrEmpty(path) &&
			path.StartsWith(prefix, StringComparison.Ordinal) &&
			TryResolveBattleMesh(path.Substring(prefix.Length), out var resolvedMesh))
		{
			resolvedPath = prefix + resolvedMesh;
			return true;
		}

		resolvedPath = path;
		return false;
	}

	internal static bool TryResolveMapMesh(string mapMeshKey, out string resolvedMapMesh)
	{
		if (!string.IsNullOrEmpty(mapMeshKey) &&
			MapMeshRoutes.TryGetValue(mapMeshKey, out resolvedMapMesh) &&
			!string.IsNullOrEmpty(resolvedMapMesh))
		{
			LogRoute("map-mesh", mapMeshKey, resolvedMapMesh);
			return true;
		}

		resolvedMapMesh = mapMeshKey;
		return false;
	}

	private static void LogRoute(string channel, string from, string to)
	{
		var key = $"{channel}:{from}->{to}";
		if (LoggedRoutes.Add(key))
		{
			Plugin.LogSource?.LogInfo($"Resolved custom {channel} '{from}' -> '{to}'.");
		}
	}

	/// <summary>
	/// Resolve a type by short name within <see cref="GameAssembly"/> only (e.g. <c>UiModelsSpawner</c>).
	/// Avoids scanning Unity / BepInEx assemblies where unrelated types can share the same short name.
	/// </summary>
	internal static Type TryFindLoadedTypeByShortName(string typeName)
	{
		if (string.IsNullOrEmpty(typeName))
		{
			return null;
		}

		var hinted = AccessTools.TypeByName(typeName);
		if (hinted != null && hinted.Assembly == GameAssembly)
		{
			return hinted;
		}

		Type[] types;
		try
		{
			types = GameAssembly.GetTypes();
		}
		catch (ReflectionTypeLoadException ex)
		{
			types = ex.Types;
		}
		catch
		{
			return null;
		}

		if (types == null)
		{
			return null;
		}

		foreach (var t in types)
		{
			if (t != null && string.Equals(t.Name, typeName, StringComparison.Ordinal))
			{
				return t;
			}
		}

		return null;
	}

	private static bool ParameterLooksLikeInteropString(Type paramType)
	{
		if (paramType == null)
		{
			return false;
		}

		if (paramType == typeof(string))
		{
			return true;
		}

		var fn = paramType.FullName ?? paramType.Name;
		return fn is "System.String" or "Il2CppSystem.String" ||
		       (fn.Contains("String", StringComparison.Ordinal) &&
		        (fn.Contains("Il2Cpp", StringComparison.Ordinal) || fn.StartsWith("System.", StringComparison.Ordinal)));
	}

	/// <summary>
	/// Interop exposes <c>Get&lt;T&gt;(Il2CppSystem.String)</c> or similar — not always <see cref="string"/>.
	/// </summary>
	internal static MethodInfo TryResolveResManagerGetGameObjectMethod(Type resManagerType)
	{
		if (resManagerType == null)
		{
			return null;
		}

		const BindingFlags bf = BindingFlags.Public | BindingFlags.Static | BindingFlags.FlattenHierarchy;
		foreach (var method in resManagerType.GetMethods(bf))
		{
			if (!string.Equals(method.Name, "Get", StringComparison.Ordinal))
			{
				continue;
			}

			var ps = method.GetParameters();
			if (ps.Length != 1 || !ParameterLooksLikeInteropString(ps[0].ParameterType))
			{
				continue;
			}

			if (method.IsGenericMethodDefinition)
			{
				if (method.GetGenericArguments().Length != 1)
				{
					continue;
				}

				try
				{
					return method.MakeGenericMethod(typeof(GameObject));
				}
				catch
				{
					continue;
				}
			}

			if (method.ReturnType == typeof(GameObject))
			{
				return method;
			}
		}

		return null;
	}

	internal static UnitViewConfig GetBattleUnitViewConfig(Unit unit)
	{
		if (unit == null)
		{
			return null;
		}

		if (_unitViewConfigProperty == null)
		{
			// Avoid AccessTools.Property(typeof(Unit),"viewConfig") — IL2CPP playtests often omit that name and Harmony logs noise.
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
			foreach (var prop in typeof(Unit).GetProperties(flags))
			{
				if (prop.PropertyType != typeof(UnitViewConfig) || !prop.CanRead)
				{
					continue;
				}

				_unitViewConfigProperty = prop;
				break;
			}
		}

		try
		{
			return _unitViewConfigProperty?.GetValue(unit, null) as UnitViewConfig;
		}
		catch
		{
			return null;
		}
	}

	internal static bool TryGetPrototypeExportFolder(string unitSid, out string exportFolderName)
	{
		var route = Routes.FirstOrDefault(candidate =>
			string.Equals(candidate.UnitSid, unitSid, StringComparison.Ordinal) &&
			!string.IsNullOrWhiteSpace(candidate.ExportFolderName));
		if (route != null)
		{
			exportFolderName = route.ExportFolderName;
			return true;
		}

		exportFolderName = null;
		return false;
	}

	/// <summary>
	/// Resolves billboard export folder for <see cref="TempleSwordsmanBillboardPrototype"/>.
	/// Battle code may rewrite <see cref="UnitViewConfig.mesh"/> to the donor path (e.g. halfling), so we match
	/// <see cref="Route.UnitSid"/>, original <see cref="Route.MeshKey"/>, or donor <see cref="Route.RuntimeMesh"/>.
	/// </summary>
	internal static bool TryResolvePrototypeExportFolder(UnitViewConfig cfg, out string configId, out string exportFolderName)
	{
		configId = null;
		exportFolderName = null;
		if (cfg == null)
		{
			return false;
		}

		if (!DeobfInteropCompat.TryGetConfigElementId(cfg, out configId))
		{
			Plugin.LogSource?.LogWarning(
				$"Skipping custom map-view routing for {cfg.GetType().FullName}: ConfigElementBase<string> id could not be read from the native field.");
			return false;
		}

		if (TryGetPrototypeExportFolder(configId, out exportFolderName))
		{
			return true;
		}

		foreach (var route in Routes)
		{
			if (string.IsNullOrWhiteSpace(route.ExportFolderName))
			{
				continue;
			}

			if (!string.IsNullOrEmpty(cfg.mesh))
			{
				if (string.Equals(route.MeshKey, cfg.mesh, StringComparison.Ordinal) ||
				    string.Equals(route.RuntimeMesh, cfg.mesh, StringComparison.Ordinal))
				{
					exportFolderName = route.ExportFolderName;
					return true;
				}
			}

			if (!string.IsNullOrEmpty(cfg.mapMesh) &&
			    string.Equals(route.MapMeshKey, cfg.mapMesh, StringComparison.Ordinal))
			{
				exportFolderName = route.ExportFolderName;
				return true;
			}
		}

		return false;
	}

	internal static bool TryGetBattlePrefabRequest(string path, out string unitSid, out string exportFolderName, out string donorMesh)
	{
		const string prefix = "units/";
		if (string.IsNullOrWhiteSpace(path) || !path.StartsWith(prefix, StringComparison.Ordinal))
		{
			unitSid = null;
			exportFolderName = null;
			donorMesh = null;
			return false;
		}

		var meshKey = path.Substring(prefix.Length);
		var route = Routes.FirstOrDefault(candidate =>
			string.Equals(candidate.MeshKey, meshKey, StringComparison.Ordinal) &&
			!string.IsNullOrWhiteSpace(candidate.ExportFolderName) &&
			!string.IsNullOrWhiteSpace(candidate.RuntimeMesh));
		if (route != null)
		{
			unitSid = route.UnitSid;
			exportFolderName = route.ExportFolderName;
			donorMesh = route.RuntimeMesh;
			return true;
		}

		unitSid = null;
		exportFolderName = null;
		donorMesh = null;
		return false;
	}

	/// <summary>
	/// Same mesh routing as <see cref="TryRewriteUnregisteredCustomUnitsPath"/> but for the relative segment passed to
	/// <c>UiModelsSpawner.Spawn</c> (<c>units/</c> is prepended inside that method). See demo_hex_all.txt UiModelsSpawner.Spawn.
	/// </summary>
	internal static bool TryRewriteRelativeMeshForUiSpawn(ref string meshRelativeToUnitsFolder)
	{
		if (string.IsNullOrEmpty(meshRelativeToUnitsFolder))
		{
			return false;
		}

		var full = "units/" + meshRelativeToUnitsFolder;
		if (!TryRewriteUnregisteredCustomUnitsPath(ref full))
		{
			return false;
		}

		const string prefix = "units/";
		meshRelativeToUnitsFolder = full.StartsWith(prefix, StringComparison.Ordinal)
			? full.Substring(prefix.Length)
			: full;
		return true;
	}

	/// <summary>
	/// Rewrites <c>units/&lt;custom mesh key&gt;</c> to a shipped donor path when the key is declared in <see cref="MeshRoutes"/>.
	/// Used from ResManager.bmeo before load; use <see cref="TryRewriteRelativeMeshForUiSpawn"/> for <c>UiModelsSpawner.Spawn</c>.
	/// </summary>
	internal static bool TryRewriteUnregisteredCustomUnitsPath(ref string fullUnitsPath)
	{
		const string prefix = "units/";
		if (string.IsNullOrEmpty(fullUnitsPath) ||
		    !fullUnitsPath.StartsWith(prefix, StringComparison.Ordinal))
		{
			return false;
		}

		var meshKey = fullUnitsPath.Substring(prefix.Length);
		if (string.IsNullOrEmpty(meshKey))
		{
			return false;
		}

		if (!MeshRoutes.TryGetValue(meshKey, out var donorMesh) ||
		    string.Equals(meshKey, donorMesh, StringComparison.Ordinal))
		{
			return false;
		}

		var rewritten = prefix + donorMesh;
		if (string.Equals(fullUnitsPath, rewritten, StringComparison.Ordinal))
		{
			return false;
		}

		LogRoute("resmanager-mesh-fallback", meshKey, donorMesh);
		fullUnitsPath = rewritten;
		return true;
	}

	private static bool IsFloatLikeParameter(Type t)
	{
		return t == typeof(float) || t == typeof(double);
	}

	/// <summary>
	/// Il2Cpp interop ships obfuscated names (e.g. <c>hqv</c>); <c>UiModelsSpawner</c> may not appear as a managed type at all.
	/// Preview pool calls <c>LoadModel(sid, mesh, scale)</c> or a foreach helper taking <see cref="UnitViewConfig"/> — rewrite mesh before Spawn.
	/// demo_hex_all.txt BhUnitPreviews ~24465–24527.
	/// </summary>
	internal static Type TryResolveBhUnitPreviewsType()
	{
		return GameAssembly.GetType("Hex.BhUnitPreviews", throwOnError: false)
		       ?? TryFindLoadedTypeByShortName("BhUnitPreviews");
	}

	internal static List<MethodInfo> EnumerateBhUnitPreviewsMeshRewriteTargets(Type bhUnitPreviewsType)
	{
		var result = new List<MethodInfo>();
		if (bhUnitPreviewsType == null)
		{
			return result;
		}

		const BindingFlags bf = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.DeclaredOnly;
		var seen = new HashSet<int>();
		foreach (var m in bhUnitPreviewsType.GetMethods(bf))
		{
			var ps = m.GetParameters();
			if (ps.Length == 1 && ps[0].ParameterType == typeof(UnitViewConfig))
			{
				if (seen.Add(m.MetadataToken))
				{
					result.Add(m);
				}
			}
		}

		foreach (var m in bhUnitPreviewsType.GetMethods(bf))
		{
			var ps = m.GetParameters();
			if (ps.Length == 3 &&
			    ParameterLooksLikeInteropString(ps[0].ParameterType) &&
			    ParameterLooksLikeInteropString(ps[1].ParameterType) &&
			    IsFloatLikeParameter(ps[2].ParameterType))
			{
				if (seen.Add(m.MetadataToken))
				{
					result.Add(m);
				}
			}
		}

		return result;
	}
}

/// <summary>
/// Runs before preview pool creation if session loader has not run yet (ordering safety).
/// </summary>
[HarmonyPatch]
internal static class BhUnitPreviewsStartBootstrapPatch
{
	private static readonly MethodBase StartMethod = AccessTools.Method(
		CustomUnitViewRouting.TryResolveBhUnitPreviewsType(),
		"Start");

	private static bool Prepare()
	{
		return StartMethod != null;
	}

	private static MethodBase TargetMethod()
	{
		return StartMethod;
	}

	private static void Prefix()
	{
		CustomUnitViewRouting.ApplyDonorMeshKeysToDatabaseOnce();
	}
}

/// <summary>
/// Interop may not expose <c>UiModelsSpawner</c> or <c>ResManager.Get&lt;T&gt;</c> for Harmony; the crash is in
/// <c>BhUnitPreviews</c> when building the preview pool. Patch obfuscated <c>LoadModel</c> / foreach helpers here
/// (string mesh path or <see cref="UnitViewConfig"/>) so donor paths are used before <c>UiModelsSpawner.Spawn</c>.
/// </summary>
internal static class BhUnitPreviewsMeshRewritePatch
{
	private static bool _patched;
	private static bool _loggedUnavailable;

	internal static void TryInstall(Harmony harmony, bool logIfUnavailable = false)
	{
		if (_patched || harmony == null)
		{
			return;
		}

		var bh = CustomUnitViewRouting.TryResolveBhUnitPreviewsType();
		var targets = CustomUnitViewRouting.EnumerateBhUnitPreviewsMeshRewriteTargets(bh);
		if (targets.Count == 0)
		{
			if (logIfUnavailable && !_loggedUnavailable)
			{
				_loggedUnavailable = true;
				Plugin.LogSource?.LogWarning(
					"BhUnitPreviews mesh rewrite: no compatible methods (UnitViewConfig or string,string,float) — preview crash may persist.");
			}

			return;
		}

		var ok = 0;
		foreach (var method in targets)
		{
			try
			{
				var ps = method.GetParameters();
				HarmonyMethod hm;
				if (ps.Length == 1 && ps[0].ParameterType == typeof(UnitViewConfig))
				{
					hm = new HarmonyMethod(typeof(BhUnitPreviewsMeshRewritePatch), nameof(PrefixUnitViewConfig));
				}
				else if (ps.Length == 3)
				{
					hm = new HarmonyMethod(typeof(BhUnitPreviewsMeshRewritePatch), nameof(PrefixSidPathScale));
				}
				else
				{
					continue;
				}

				harmony.Patch(method, prefix: hm);
				ok++;
				Plugin.LogSource?.LogInfo(
					$"Patched BhUnitPreviews preview mesh hook: {method.Name} ({string.Join(", ", ps.Select(p => p.ParameterType.Name))}).");
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning($"BhUnitPreviews.{method.Name} mesh prefix failed: {ex.Message}");
			}
		}

		if (ok > 0)
		{
			_patched = true;
		}
	}

	private static void PrefixUnitViewConfig(UnitViewConfig __0)
	{
		if (__0 == null)
		{
			return;
		}

		var mesh = __0.mesh;
		if (string.IsNullOrEmpty(mesh))
		{
			return;
		}

		if (CustomUnitViewRouting.TryRewriteRelativeMeshForUiSpawn(ref mesh))
		{
			__0.mesh = mesh;
		}
	}

	/// <summary>Matches <c>LoadModel(string sid, string path, float scale)</c>; path is the second argument.</summary>
	private static void PrefixSidPathScale(ref string __1)
	{
		if (string.IsNullOrEmpty(__1))
		{
			return;
		}

		CustomUnitViewRouting.TryRewriteRelativeMeshForUiSpawn(ref __1);
	}
}

[HarmonyPatch]
internal static class UnitViewConfigGetMapPrefabPatch
{
	private static MethodInfo _targetMethod;
	private static bool _targetResolved;

	private static bool Prepare()
	{
		ResolveTargetMethod();
		return _targetMethod != null;
	}

	private static MethodBase TargetMethod()
	{
		ResolveTargetMethod();
		return _targetMethod
			?? throw new MissingMethodException(
				$"Could not resolve {GameSymbols.UnitViewConfig.MapMeshLoader.Id} as a unique declared instance GameObject() method.");
	}

	private static void ResolveTargetMethod()
	{
		if (_targetResolved)
		{
			return;
		}

		_targetResolved = true;
		var candidates = GameMember.FindMethods(
			typeof(UnitViewConfig),
			typeof(GameObject),
			Type.EmptyTypes,
			GameSymbols.UnitViewConfig.MapMeshLoader);
		if (candidates.Length == 1 &&
			candidates[0].DeclaringType == typeof(UnitViewConfig) &&
			!candidates[0].IsStatic &&
			!candidates[0].IsGenericMethod)
		{
			_targetMethod = candidates[0];
			return;
		}

		Plugin.LogSource?.LogWarning(
			$"Skipping UnitViewConfig map prefab patch: expected one declared instance GameObject() method for " +
			$"{GameSymbols.UnitViewConfig.MapMeshLoader.Id}, found {candidates.Length}.");
	}

	private static bool Prefix(UnitViewConfig __instance, ref GameObject __result)
	{
		if (__instance == null)
		{
			return true;
		}

		if (TempleSwordsmanBillboardPrototype.TryGetMapPrefab(__instance, out var customPrefab) && customPrefab != null)
		{
			__result = customPrefab;
			return false;
		}

		if (CustomUnitViewRouting.TryResolveMapMesh(__instance.mapMesh, out var resolvedMapMesh) &&
			!string.Equals(__instance.mapMesh, resolvedMapMesh, StringComparison.Ordinal))
		{
			__instance.mapMesh = resolvedMapMesh;
		}

		return true;
	}
}

/// <summary>
/// Battle roster previews call <see cref="UiModelsSpawner.Spawn"/> with <see cref="UnitViewConfig.mesh"/> — not ResManager.bmeo.
/// Spawn does <c>units/{{_path}}</c> then <c>ResManager.Get&lt;GameObject&gt;</c>; on failure it still dereferences null (game bug).
/// Rewriting _path here matches dump contract regardless of DB list reflection. demo_hex_all.txt ~171094–171121, ~24524–24527.
/// Installed manually (not <see cref="HarmonyPatch"/>): <c>UiModelsSpawner</c> may load after <see cref="Plugin.Load"/>.
/// </summary>
internal static class UiModelsSpawnerSpawnMeshRewritePatch
{
	private static bool _installed;
	private static bool _loggedSpawnUnavailable;

	internal static void TryInstall(Harmony harmony, bool logIfUnavailable = false)
	{
		if (_installed || harmony == null)
		{
			return;
		}

		var target = ResolveSpawnMethod();
		if (target == null)
		{
			if (logIfUnavailable && !_loggedSpawnUnavailable)
			{
				_loggedSpawnUnavailable = true;
				Plugin.LogSource?.LogWarning(
					"UiModelsSpawner.Spawn still not patchable after session load — relying on ResManager.Get<GameObject> rewrite.");
			}

			return;
		}

		try
		{
			harmony.Patch(
				target,
				prefix: new HarmonyMethod(typeof(UiModelsSpawnerSpawnMeshRewritePatch), nameof(Prefix)));
			_installed = true;
			Plugin.LogSource?.LogInfo("Patched UiModelsSpawner.Spawn for custom unit mesh path rewrite.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"UiModelsSpawner.Spawn patch failed: {ex.Message}");
		}
	}

	private static MethodBase ResolveSpawnMethod()
	{
		var t = CustomUnitViewRouting.TryFindLoadedTypeByShortName("UiModelsSpawner");
		if (t == null)
		{
			return null;
		}

		return AccessTools.GetDeclaredMethods(t)
			.FirstOrDefault(m => m is { Name: "Spawn", IsStatic: true } && m.GetParameters().Length == 5);
	}

	/// <summary>
	/// IL2CPP emitted parameter name is typically <c>a</c>, not <c>_path</c>; bind by index (<c>__0</c>) so the rewrite applies.
	/// </summary>
	private static void Prefix(ref string __0)
	{
		if (string.IsNullOrEmpty(__0))
		{
			return;
		}

		CustomUnitViewRouting.TryRewriteRelativeMeshForUiSpawn(ref __0);
	}
}

/// <summary>
/// Primary load path used by <c>UiModelsSpawner.Spawn</c>: <c>ResManager.Get&lt;GameObject&gt;(string)</c> with full keys like
/// <c>units/Neutral/...</c> (<c>demo_hex_all.txt</c> ~171097–171099). Patches the string arg so registered custom mesh keys rewrite
/// even when Spawn prefix argument binding fails under IL2CPP.
/// </summary>
internal static class ResManagerGetGameObjectUnitsPathPatch
{
	private static bool _installed;

	internal static void TryInstall(Harmony harmony)
	{
		if (_installed || harmony == null)
		{
			return;
		}

		var rm = CustomUnitViewRouting.GameAssembly.GetType("Hex.ResManager", throwOnError: false);
		if (rm == null)
		{
			Plugin.LogSource?.LogWarning("Hex.ResManager not found — cannot patch Get<GameObject>(string).");
			return;
		}

		var concrete = CustomUnitViewRouting.TryResolveResManagerGetGameObjectMethod(rm);
		if (concrete == null)
		{
			Plugin.LogSource?.LogWarning(
				"ResManager.Get for GameObject + string-like path could not be resolved (check Il2Cpp interop signatures).");
			return;
		}

		try
		{
			harmony.Patch(
				concrete,
				prefix: new HarmonyMethod(typeof(ResManagerGetGameObjectUnitsPathPatch), nameof(Prefix)));
			_installed = true;
			Plugin.LogSource?.LogInfo(
				$"Patched ResManager resource load ({concrete.DeclaringType?.Name}.{concrete.Name}) for custom units/ mesh rewrite.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"ResManager Get<GameObject> patch failed: {ex.Message}");
		}
	}

	private static void Prefix(ref string __0)
	{
		if (string.IsNullOrEmpty(__0))
		{
			return;
		}

		var path = __0;
		if (!CustomUnitViewRouting.TryRewriteUnregisteredCustomUnitsPath(ref path))
		{
			return;
		}

		__0 = path;
	}
}

/// <summary>
/// After battle wires <see cref="UnitDrawer"/> via <c>Listen(IUnitListenner)</c>, install billboard patches using the runtime drawer CLR type.
/// Installed manually: playtest builds may rename <c>Listen</c> / interfaces so <see cref="HarmonyPatch"/> <c>TargetMethod()</c> threw before patch apply.
/// </summary>
internal static class BattleUnitListenBillboardBootstrapPatch
{
	private static bool _installed;

	internal static bool TryInstall(Harmony harmony)
	{
		if (_installed || harmony == null)
		{
			return _installed;
		}

		try
		{
			var method = ResolveUnitListenMethod(out var resolutionNote);
			if (method == null)
			{
				Plugin.LogSource?.LogWarning($"Battle Listen bootstrap: unresolved ({resolutionNote}).");
				return false;
			}

			harmony.Patch(
				method,
				postfix: new HarmonyMethod(typeof(BattleUnitListenBillboardBootstrapPatch), nameof(Postfix)));
			_installed = true;
			var p0 = method.GetParameters()[0].ParameterType;
			Plugin.LogSource?.LogInfo(
				$"Battle Listen bootstrap: patched {method.DeclaringType?.FullName}.{method.Name} — {resolutionNote}; param={p0.FullName ?? p0.Name}");
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Battle Listen bootstrap: Patch() failed — {ex}");
			return false;
		}
	}

	/// <summary>
	/// Playtest metadata may omit <c>IUnitListenner</c>; <see cref="Unit.listener"/> still carries the CLR type used by Listen/Unlisten.
	/// </summary>
	private static bool TryResolveListenViaListenerProperty(BindingFlags methodFlags, out MethodInfo method, out string note)
	{
		method = null;
		note = string.Empty;

		// DeclaredOnly: skip Il2CppObjectBase junk (ObjectClass→IntPtr matched Il2CppObjectBase.CreateGCHandle).
		const BindingFlags pf =
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

		PropertyInfo[] props;
		try
		{
			props = typeof(Unit).GetProperties(pf);
		}
		catch
		{
			return false;
		}

		var ordered = props
			.Where(IsPlausibleBattleListenerProperty)
			.OrderByDescending(p => string.Equals(p.Name, "listener", StringComparison.OrdinalIgnoreCase))
			.ThenBy(p => p.MetadataToken)
			.ToArray();

		foreach (var listenerProp in ordered)
		{
			var ifaceType = listenerProp.PropertyType;

			var candidates = new List<MethodInfo>();
			foreach (var m in typeof(Unit).GetMethods(methodFlags))
			{
				var ps = m.GetParameters();
				if (ps.Length != 1 || m.ReturnType != typeof(void))
				{
					continue;
				}

				if (!Equals(ps[0].ParameterType, ifaceType))
				{
					continue;
				}

				candidates.Add(m);
			}

			if (candidates.Count == 0)
			{
				continue;
			}

			foreach (var m in candidates)
			{
				if (string.Equals(m.Name, "Listen", StringComparison.OrdinalIgnoreCase))
				{
					method = m;
					note = $"listener property '{listenerProp.Name}' → method name Listen";
					return true;
				}
			}

			foreach (var m in candidates)
			{
				if (m.Name.IndexOf("Listen", StringComparison.OrdinalIgnoreCase) >= 0 &&
				    m.Name.IndexOf("Unlisten", StringComparison.OrdinalIgnoreCase) < 0)
				{
					method = m;
					note = $"listener property '{listenerProp.Name}' → name contains Listen";
					return true;
				}
			}

			if (candidates.Count == 1)
			{
				method = candidates[0];
				note = $"listener property '{listenerProp.Name}' → sole void(paramType==propertyType)";
				return true;
			}

			note =
				$"listener property '{listenerProp.Name}': ambiguous [{string.Join(", ", candidates.Select(c => c.Name))}]";
			return false;
		}

		return false;
	}

	private static bool IsPlausibleBattleListenerProperty(PropertyInfo p)
	{
		if (p == null)
		{
			return false;
		}

		var pt = p.PropertyType;
		if (pt == null || pt == typeof(object))
		{
			return false;
		}

		if (pt == typeof(IntPtr) || pt.IsPointer || pt.IsPrimitive && pt != typeof(bool))
		{
			return false;
		}

		// Game stores IUnitListenner — must be interface (Il2Cpp keeps this).
		return pt.IsInterface;
	}

	private static MethodInfo ResolveUnitListenMethod(out string resolutionNote)
	{
		const BindingFlags bf =
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

		var ga = CustomUnitViewRouting.GameAssembly;
		var iface = ga?.GetType("Hex.Session.Battle.IUnitListenner", throwOnError: false);
		var ud = TempleSwordsmanBillboardPrototype.ResolveBattleUnitDrawerClrTypeStatic();

		if (TryResolveListenViaListenerProperty(bf, out var viaListener, out var listenerNote))
		{
			resolutionNote = listenerNote;
			return viaListener;
		}

		if (iface != null)
		{
			var viaAccess = AccessTools.Method(typeof(Unit), "Listen", new[] { iface })
				?? AccessTools.DeclaredMethod(typeof(Unit), "Listen", new[] { iface });
			if (viaAccess != null)
			{
				resolutionNote = "AccessTools Listen(IUnitListenner)";
				return viaAccess;
			}
		}

		MethodInfo byIfaceParam = null;
		MethodInfo byStableName = null;
		MethodInfo byParamTypename = null;
		var drawerAcceptors = new List<MethodInfo>();

		for (var t = typeof(Unit); t != null && t != typeof(object); t = t.BaseType)
		{
			foreach (var m in t.GetMethods(bf))
			{
				var ps = m.GetParameters();
				if (ps.Length != 1 || m.ReturnType != typeof(void))
				{
					continue;
				}

				var pt = ps[0].ParameterType;
				if (pt == typeof(object))
				{
					continue;
				}

				if (string.Equals(m.Name, "Listen", StringComparison.Ordinal))
				{
					byStableName ??= m;
				}

				var pfn = pt.FullName ?? pt.Name ?? string.Empty;
				if (pfn.IndexOf("IUnitListenner", StringComparison.OrdinalIgnoreCase) >= 0 ||
				    pfn.IndexOf("UnitListenner", StringComparison.OrdinalIgnoreCase) >= 0)
				{
					byParamTypename ??= m;
				}

				if (iface != null)
				{
					try
					{
						if (iface.IsAssignableFrom(pt))
						{
							byIfaceParam ??= m;
						}
					}
					catch
					{
						// ignored
					}
				}

				if (ud != null)
				{
					try
					{
						if (pt.IsAssignableFrom(ud))
						{
							drawerAcceptors.Add(m);
						}
					}
					catch
					{
						// ignored
					}
				}
			}
		}

		if (byIfaceParam != null)
		{
			resolutionNote = "parameter type assignable from IUnitListenner metadata";
			return byIfaceParam;
		}

		if (drawerAcceptors.Count == 1)
		{
			resolutionNote = "single void(Instance) whose parameter accepts resolved UnitDrawer CLR type";
			return drawerAcceptors[0];
		}

		if (drawerAcceptors.Count > 1)
		{
			foreach (var m in drawerAcceptors)
			{
				if (m.Name.IndexOf("Listen", StringComparison.OrdinalIgnoreCase) >= 0)
				{
					resolutionNote =
						$"multiple drawer-acceptors ({drawerAcceptors.Count}); picked name containing Listen";
					return m;
				}
			}

			resolutionNote =
				$"ambiguous drawer-acceptors ({drawerAcceptors.Count}): {string.Join(", ", drawerAcceptors.Select(x => x.Name))}";
			return null;
		}

		if (byStableName != null)
		{
			resolutionNote = "method name Listen";
			return byStableName;
		}

		if (byParamTypename != null)
		{
			resolutionNote = "parameter type name contains Listenner";
			return byParamTypename;
		}

		resolutionNote =
			$"iface={(iface != null ? "ok" : "missing")}, unitDrawerClr={(ud != null ? ud.FullName ?? ud.Name : "missing")}; no Listen candidate";
		return null;
	}

	private static void Postfix(Unit __instance, object listener)
	{
		if (listener == null)
		{
			return;
		}

		TempleSwordsmanBillboardPrototype.EnsureBattlePatchesInstalled(__instance, listener.GetType());
	}

	internal static bool IsListenPatchInstalled => _installed;

	/// <summary>
	/// One-file snapshot for fast iteration: open <c>resolution_probe.txt</c> next to the DLL instead of hunting LogOutput.
	/// </summary>
	internal static string BuildIterationProbeReport(bool verbose)
	{
		var sb = new StringBuilder();
		sb.AppendLine($"listen_patch_installed={_installed}");
		var listen = ResolveUnitListenMethod(out var note);
		sb.AppendLine($"listen_resolve={(listen != null ? "OK" : "FAIL")}");
		sb.AppendLine($"listen_note={note}");
		if (listen != null)
		{
			sb.AppendLine($"listen_method={listen.DeclaringType?.FullName}.{listen.Name}");
		}

		var ga = CustomUnitViewRouting.GameAssembly;
		sb.AppendLine($"game_assembly={ga?.GetName().Name}");
		sb.AppendLine(
			$"hex.IUnitListenner={(ga?.GetType("Hex.Session.Battle.IUnitListenner", false) != null ? "found" : "missing")}");
		sb.AppendLine(
			$"hex.UnitDrawer_static={(ga?.GetType("Hex.Session.Battle.UnitDrawer", false)?.FullName ?? "missing")}");
		var ud = TempleSwordsmanBillboardPrototype.ResolveBattleUnitDrawerClrTypeStatic();
		sb.AppendLine($"resolved_unit_drawer_clr={ud?.FullName ?? "missing"}");

		sb.AppendLine("--- Unit properties (interface-typed, DeclaredOnly — listener candidates) ---");
		foreach (var prop in typeof(Unit).GetProperties(
			         BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic |
			         BindingFlags.DeclaredOnly))
		{
			if (!prop.PropertyType.IsInterface)
			{
				continue;
			}

			sb.AppendLine($"  {prop.Name}: {prop.PropertyType.FullName ?? prop.PropertyType.Name}");
		}

		if (verbose)
		{
			sb.AppendLine("--- void(T) single-arg instance methods (Unit hierarchy, DeclaredOnly) ---");
			const BindingFlags bf =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var t = typeof(Unit); t != null && t != typeof(object); t = t.BaseType)
			{
				foreach (var m in t.GetMethods(bf))
				{
					var ps = m.GetParameters();
					if (ps.Length != 1 || m.ReturnType != typeof(void))
					{
						continue;
					}

					sb.AppendLine($"  {t.Name}.{m.Name}({ps[0].ParameterType.FullName ?? ps[0].ParameterType.Name})");
				}
			}
		}

		sb.AppendLine("--- ResManager ---");
		sb.AppendLine($"Hex.ResManager={(ga?.GetType("Hex.ResManager", false)?.FullName ?? "missing")}");

		return sb.ToString();
	}
}

[HarmonyPatch]
internal static class BattleUnitInitMeshRoutePatch
{
	private static MethodBase TargetMethod()
	{
		return AccessTools.DeclaredMethod(typeof(Unit), nameof(Unit.Init))
			?? throw new MissingMethodException($"{typeof(Unit).FullName}.Init");
	}

	private static void Postfix(Unit __instance, bool __result)
	{
		if (!__result)
		{
			return;
		}

		// Billboard battle hooks install from Unit.Listen(unitDrawer): Init runs before the drawer is wired.
		TempleSwordsmanBillboardPrototype.EnsureRuntimePrefabRouteInstalled();
		TempleSwordsmanBillboardPrototype.NotifyBattleUnitInit();

		var viewConfig = CustomUnitViewRouting.GetBattleUnitViewConfig(__instance);
		if (viewConfig == null)
		{
			return;
		}

		if (CustomUnitViewRouting.TryResolveBattleMesh(viewConfig.mesh, out var resolvedMesh) &&
			!string.Equals(viewConfig.mesh, resolvedMesh, StringComparison.Ordinal))
		{
			Plugin.LogSource?.LogInfo(
				$"Battle Unit.Init: rewriting viewConfig.mesh '{viewConfig.mesh}' -> '{resolvedMesh}' so ResManager resolves a shipped prefab path.");
			viewConfig.mesh = resolvedMesh;
		}
	}
}
