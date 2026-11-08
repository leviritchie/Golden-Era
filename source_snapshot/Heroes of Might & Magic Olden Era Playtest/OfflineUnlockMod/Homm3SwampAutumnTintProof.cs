using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Map;
using Hex.Render;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.Runtime;
using UnityEngine;
using Il2CppIntDictionary = Il2CppSystem.Collections.Generic.Dictionary<int, int>;

namespace OfflineUnlockMod;

/// <summary>
/// Copy-install proof hook: register custom terrain material entries before
/// native terrain renderer and biome sound consumers build tile-code-indexed lookups.
/// </summary>
internal static class Homm3SwampAutumnTintProof
{
	private const string DefinitionsPath = "homm3_runtime_assets/custom_biomes/custom_biomes.json";
	private const string TerrainBindingProbeFlagName = "homm3_terrain_binding_probe.flag";
	private const string TerrainBindingDeepProbeFlagName = "homm3_terrain_binding_deep_probe.flag";
	private const string TerrainRendererBroadProbeFlagName = "homm3_terrain_renderer_broad_probe.flag";
	private const string TerrainFirstFiveMaterialProbeFlagName = "homm3_terrain_first_five_material_probe.flag";
	private const string TerrainFirstNineMaterialProbeFlagName = "homm3_terrain_first_nine_material_probe.flag";
	private const string TerrainRebuildCandidateFlagPrefix = "homm3_terrain_rebuild_candidate_";
	private const string TerrainRebuildCandidateFlagSuffix = ".flag";

	private static ManualLogSource _log;
	private static CustomBiomeDefinition[] _definitions;
	private static readonly Dictionary<string, Texture2D[]> TextureCache = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, List<GameSymbols.FieldSymbol>> ResolvedNativeLookupSymbolsByType =
		new(StringComparer.Ordinal);
	private static readonly HashSet<string> FailedNativeLookupKeys = new(StringComparer.Ordinal);
	private static readonly HashSet<long> ValidatedRendererKeys = new();
	private static readonly HashSet<long> SeededRendererKeys = new();
	private static readonly HashSet<long> RebuiltRendererKeys = new();
	private static readonly HashSet<long> ManagedExtendedRendererKeys = new();
	private static readonly HashSet<string> RejectedRendererRebuildMethods = new(StringComparer.Ordinal);
	private static readonly HashSet<string> FlaggedRendererRebuildMethods = new(StringComparer.Ordinal);
	private static HashSet<int> _currentMapCustomVisualTileCodes;
	private static HashSet<int> _currentMapNativeWaterTerrainTileCodes;
	// Per-tileCode tile counts for the active map (all codes, native and custom).
	private static Dictionary<int, int> _currentMapTileCounts = new();
	private static Dictionary<int, int> _scanTileCounts = new();
	// Active-map custom terrains rendered with their material donor's slot because the compacted table would
	// exceed the shader's 16 packed slots (GH#29; user-approved prune + fallback 2026-10-13).
	private static HashSet<int> _currentMapDemotedCustomTileCodes = new();
	// Native biome rows as first seen in SoTerrainMaterial, so a pruned table can be restored for later maps / RMG.
	private static List<SoTerrainMaterial.Biome> _nativeBiomeSnapshot;
	private static bool _nativeBiomesPruned;
	private static bool _currentMapUsesDisplayWaterAlias;
	private static bool _currentMapVisualSlotScopeKnown;
	private static int _currentMapVisualSlotScopeGeneration;
	private static int _currentMapPackedLayerWidth;
	private static int _currentMapPackedLayerHeight;
	private static bool _activeMapMaterialSlotsApplied;
	// the shipped TerrainMaterials asset has no Water biome row in the compacted active map.
	// AppendNativeWaterTerrainBiomesFromCatalog clones native Sand seabed textures for tile ids
	// 18-22 when present on the active Homecoming map so the land under the waterMap mesh reads
	// as shoreline sand; EnsureNativeWaterTerrainLookupEntries maps those ids to compacted slots.
	// Native animated ocean visuals come from MapData.waterMap bytes and the bws water-mesh
	// chunk system, not from Homm3TerrainWaterAnimator or HoMM3 terrain texture sheets.
	private const int NativeWaterTerrainDonorTileCode = 18;
	private const int NativeWaterTerrainSeabedDonorTileCode = 2;
	/// <summary>
	/// Must stay aligned with Core.zip <c>DB/map/tiles/tiles.json</c> biome strings.
	/// RMG <c>bjl</c> indexes configs by biome name; repeating <c>Water</c> on tiles 18-22 aborts GenerateMap.
	/// </summary>
	private static readonly Dictionary<int, string> NativeWaterTerrainBiomeNameByTileCode = new()
	{
		[NativeWaterTerrainDonorTileCode] = "Water",
		[19] = "Water Shore North",
		[20] = "Water Shore South",
		[21] = "Water Shore West",
		[22] = "Water Shore East",
	};
	private static SoTerrainMaterial.Biome _nativeWaterDonorBiome;
	private static bool _nativeWaterDonorBiomeCaptureAttempted;
	private static bool _registered;
	private static bool _rmgGenerateMapSanitizeRegistered;
	private static bool _ambientFogControllerExtensionAvailable = true;
	private static bool _ambientFogControllerWarningLogged;
	private static bool _terrainGlobalVectorArraysPreseeded;
	private static bool _terrainGlobalVectorArrayPreseedAttempted;
	private static string _terrainGlobalVectorArrayPreseedFailure;
	private static int _biomeSlotAuditRemaining = 3;
	private static int _terrainMaterialAuditRemaining = 8;
	private static int _rebuildRejectionLogsRemaining = 6;
	private static int _terrainGlobalVectorArrayPreseedLogsRemaining = 3;
	private static int _packedBuildNaturalCallLogsRemaining = 80;
	[ThreadStatic] private static int _ambientFogControllerRefreshDepth;

	internal static void RegisterRequired(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony is required for custom biome registration.");
		_log = log;
		_definitions = LoadDefinitions();
		// Homecoming native water uses tilesMap ids 18-22 plus MapData.waterMap bytes for the mesh overlay.
		var skipTerrainRendererRegistration = Homm3MapLoadFlightRecorder.DisableTerrainRendererRegistration;
		var skipTerrainSoundRegistration = Homm3MapLoadFlightRecorder.DisableTerrainSoundRegistration;

		if (skipTerrainRendererRegistration)
		{
			log?.LogWarning("HoMM3 custom biome terrain renderer/material hooks skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableTerrainRendererRegistrationFlag + ".");
			Homm3MapLoadFlightRecorder.Mark("plugin.skip-terrain-renderer-registration", Homm3MapLoadFlightRecorder.DisableTerrainRendererRegistrationFlag);
		}
		else
		{
			var instanceGetter = GameMember.FindFirstMethod(
				typeof(SoTerrainMaterial),
				typeof(SoTerrainMaterial),
				Type.EmptyTypes,
				GameSymbols.TerrainMaterial.InstanceGetter);
			if (instanceGetter == null)
				throw new MissingMethodException("Could not resolve SoTerrainMaterial instance getter for custom biome registration.");

			var materialGetter = GameMember.FindFirstMethod(
				typeof(SoTerrainMaterial),
				typeof(Material),
				Type.EmptyTypes,
				GameSymbols.TerrainMaterial.MaterialGetter);
			if (materialGetter == null)
				throw new MissingMethodException("Could not resolve SoTerrainMaterial material getter for custom biome registration.");

			var rendererType = ResolveTerrainRendererType();
			if (rendererType == null)
				throw new MissingMethodException("Could not resolve terrain renderer type for custom biome registration.");

			var rendererCtor = AccessTools.Constructor(rendererType, Type.EmptyTypes);
			if (rendererCtor == null)
				throw new MissingMethodException("Could not resolve terrain renderer constructor for custom biome registration.");

			var rendererPrepareMap = GameMember.FindFirstMethod(
				rendererType,
				typeof(void),
				new[] { typeof(Map), typeof(bool), typeof(bool) },
				GameSymbols.TerrainMaterial.RendererPrepareMap);
			if (rendererPrepareMap == null)
				throw new MissingMethodException("Could not resolve terrain renderer prepare-map method for custom biome registration.");
			harmony.Patch(instanceGetter, postfix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PostfixInstanceGetter)));
			harmony.Patch(materialGetter, prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixMaterialGetter)));
			harmony.Patch(
				rendererCtor,
				prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixRendererConstructor)),
				postfix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PostfixRendererConstructor)));
			harmony.Patch(
				rendererPrepareMap,
				prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixRendererPrepareMap)),
				postfix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PostfixRendererPrepareMapRebuild)));
			RegisterGenerateMapBiomeNameSanitize(harmony, log);
			if (Homm3DiagnosticFlags.IsEnabled(TerrainBindingDeepProbeFlagName)
			    || Homm3DiagnosticFlags.IsEnabled(TerrainRendererBroadProbeFlagName))
				PatchRendererPackedBuildNaturalCallProbes(harmony, log, rendererType);
			else if (Homm3DiagnosticFlags.IsEnabled(TerrainBindingProbeFlagName))
				log?.LogWarning("HoMM3 custom biome registration terrain binding probe enabled in safe-point mode; extra renderer method patching is skipped.");
			else
				log?.LogInfo("HoMM3 custom biome registration terrain binding probe skipped; create " + TerrainBindingProbeFlagName + " for passive renderer binding diagnostics.");
		}

		if (skipTerrainSoundRegistration)
		{
			log?.LogWarning("HoMM3 custom biome sound/fog hooks skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableTerrainSoundRegistrationFlag + ".");
			Homm3MapLoadFlightRecorder.Mark("plugin.skip-terrain-sound-registration", Homm3MapLoadFlightRecorder.DisableTerrainSoundRegistrationFlag);
		}
		else
		{
			var heroBiomeSoundType = ResolveHeroBiomeSoundType(log);
			if (heroBiomeSoundType == null)
				throw new MissingMethodException("Could not resolve hero biome sound type for custom biome registration.");
			var heroBiomeBuildMap = GameMember.FindFirstMethod(
				heroBiomeSoundType,
				typeof(void),
				new[] { typeof(Map) },
				GameSymbols.TerrainSound.HeroBiomeBuildMap);
			if (heroBiomeBuildMap == null)
				throw new MissingMethodException("Could not resolve hero biome sound map-build method for custom biome registration.");
			var ambientBiomeSoundType = ResolveAmbientBiomeSoundType(log);
			if (ambientBiomeSoundType == null)
				throw new MissingMethodException("Could not resolve ambient biome sound type for custom biome registration.");
			var ambientBiomeBuild = GameMember.FindFirstMethod(
				ambientBiomeSoundType,
				typeof(void),
				Type.EmptyTypes,
				GameSymbols.TerrainSound.AmbientBiomeBuild);
			var ambientGetVolumes = GameMember.FindMethodsByNames(
				ambientBiomeSoundType,
				3,
				GameSymbols.TerrainSound.AmbientBiomeGetVolumes.Id,
				GameSymbols.TerrainSound.AmbientBiomeGetVolumes.NameHints).FirstOrDefault();
			if (ambientBiomeBuild == null && ambientGetVolumes == null)
				throw new MissingMethodException("Could not resolve ambient biome sound build/GetSoundsVolume methods for custom biome registration.");
			harmony.Patch(
				heroBiomeBuildMap,
				prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixHeroBiomeSoundBuildMap)),
				postfix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PostfixHeroBiomeSoundBuildMap)));
			PrimeHeroBiomeStaticLookupMappings(heroBiomeSoundType, "custom biome registration startup");
			try
			{
				PatchHeroBiomeController(harmony, log, heroBiomeSoundType);
			}
			catch (Exception ex)
			{
				log?.LogWarning("HoMM3 custom biome registration could not patch hero biome controller lifecycle; map-build selector hooks remain active: " + ex.Message);
			}
			PatchHeroBiomeSelectors(harmony, log, heroBiomeSoundType);
			if (ambientBiomeBuild != null)
				harmony.Patch(ambientBiomeBuild, prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixAmbientBiomeSoundBuild)));
			if (ambientGetVolumes != null)
				harmony.Patch(ambientGetVolumes, prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixAmbientBiomeGetSoundsVolume)));
			PatchAmbientFogController(harmony, log);
		}
		Homm3CustomBiomeMinimapHook.Register(harmony, log);
		_registered = true;
		log?.LogWarning("HoMM3 custom biome registration enabled for " + _definitions.Length + " definition(s): " + string.Join(", ", _definitions.Select(DescribeDefinition)) + ".");
	}

	internal static CustomBiomeDefinition[] EnabledBiomeDefinitions => Definitions;

	private static Type ResolveTerrainRendererType()
	{
		foreach (var hint in GameSymbols.TerrainMaterial.RendererTypeHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = GameMember.FindType(
				GameSymbols.TerrainMaterial.RendererTypeId + "." + hint,
				hint,
				logMiss: false);
			if (HasTerrainRendererSurface(type))
				return type;
		}
		Plugin.LogSource?.LogWarning(
			"GameMember type MISS: " + GameSymbols.TerrainMaterial.RendererTypeId
			+ " — no hint in list resolved a terrain renderer surface; this surface is unavailable.");
		return null;
	}

	private static bool HasTerrainRendererSurface(Type type)
	{
		if (type == null)
			return false;
		var hasTerrainMaterial = false;
		var hasTextureArray = false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			FieldInfo[] fields;
			try { fields = current.GetFields(flags); }
			catch { fields = Array.Empty<FieldInfo>(); }
			foreach (var field in fields)
			{
				hasTerrainMaterial |= GameMember.TypesEquivalent(typeof(SoTerrainMaterial), field.FieldType);
				hasTextureArray |= GameMember.TypesEquivalent(typeof(Texture2DArray), field.FieldType);
			}

			PropertyInfo[] properties;
			try { properties = current.GetProperties(flags); }
			catch { properties = Array.Empty<PropertyInfo>(); }
			foreach (var property in properties)
			{
				if (property.GetIndexParameters().Length != 0)
					continue;
				hasTerrainMaterial |= GameMember.TypesEquivalent(typeof(SoTerrainMaterial), property.PropertyType);
				hasTextureArray |= GameMember.TypesEquivalent(typeof(Texture2DArray), property.PropertyType);
			}
		}

		if (!hasTerrainMaterial || !hasTextureArray)
			return false;
		return GameMember.FindFirstMethod(type, typeof(void), new[] { typeof(Map), typeof(bool), typeof(bool) }, GameSymbols.TerrainMaterial.RendererPrepareMap) != null;
	}

	private static void PatchRendererPackedBuildNaturalCallProbes(Harmony harmony, ManualLogSource log, Type rendererType)
	{
		if (harmony == null || rendererType == null)
			return;
		var prefix = new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixRendererPackedBuildNaturalCallProbe));
		var postfix = new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PostfixRendererPackedBuildNaturalCallProbe));
		var patched = 0;
		var patchedNames = new List<string>();
		var includeDeepZeroArgMethods =
			Homm3DiagnosticFlags.IsEnabled(TerrainBindingDeepProbeFlagName)
			|| Homm3DiagnosticFlags.IsEnabled(TerrainRendererBroadProbeFlagName);
		if (includeDeepZeroArgMethods)
		{
			PatchRendererNaturalCallProbeMethods(
				harmony,
				log,
				rendererType,
				typeof(void),
				Type.EmptyTypes,
				GameSymbols.TerrainMaterial.RendererPackedBuildNaturalCallProbe,
				prefix,
				postfix,
				ref patched,
				patchedNames);
		}
		else
		{
			log?.LogWarning("HoMM3 custom biome registration terrain binding probe: zero-arg renderer methods skipped; create "
				+ TerrainBindingDeepProbeFlagName
				+ " for crash-risk deep probing after lifecycle probes are exhausted.");
		}
		PatchRendererNaturalCallProbeMethods(
			harmony,
			log,
			rendererType,
			typeof(void),
			new[] { typeof(int), typeof(int) },
			GameSymbols.TerrainMaterial.RendererTextureArrayBuildNaturalCallProbe,
			prefix,
			postfix,
			ref patched,
			patchedNames);
		PatchRendererNaturalCallProbeMethods(
			harmony,
			log,
			rendererType,
			typeof(void),
			new[] { typeof(Map) },
			GameSymbols.TerrainMaterial.RendererMapNaturalCallProbe,
			prefix,
			postfix,
			ref patched,
			patchedNames);
		PatchRendererNaturalCallProbeMethods(
			harmony,
			log,
			rendererType,
			typeof(void),
			new[] { typeof(Map), typeof(bool), typeof(bool) },
			GameSymbols.TerrainMaterial.RendererPrepareNaturalCallProbe,
			prefix,
			postfix,
			ref patched,
			patchedNames);
		if (patched > 0)
		{
			log?.LogWarning("HoMM3 custom biome registration patched "
				+ patched
				+ " passive terrain binding probe method(s) on "
				+ rendererType.FullName
				+ ": "
				+ string.Join(", ", patchedNames)
				+ ".");
		}
	}

	private static void PatchRendererNaturalCallProbeMethods(
		Harmony harmony,
		ManualLogSource log,
		Type rendererType,
		Type returnType,
		Type[] parameterTypes,
		GameSymbols.MethodSymbol symbol,
		HarmonyMethod prefix,
		HarmonyMethod postfix,
		ref int patched,
		List<string> patchedNames)
	{
		var methods = GameMember.FindMethods(
			rendererType,
			returnType,
			parameterTypes,
			symbol);
		var seen = new HashSet<string>(StringComparer.Ordinal);
		var allowedNames = new HashSet<string>(
			symbol.NameHints ?? Array.Empty<string>(),
			StringComparer.Ordinal);
		foreach (var method in methods)
		{
			if (method == null || !allowedNames.Contains(method.Name) || !seen.Add(method.Name))
				continue;
			if (IsRejectedRendererNaturalProbeMethod(method))
			{
				log?.LogWarning("HoMM3 custom biome registration terrain binding probe skipped rejected renderer method "
					+ rendererType.FullName
					+ "."
					+ method.Name
					+ ".");
				continue;
			}
			try
			{
				harmony.Patch(method, prefix: prefix, postfix: postfix);
				patched++;
				patchedNames.Add(method.Name + "(" + string.Join(",", parameterTypes.Select(type => type.Name)) + ")");
			}
			catch (Exception ex)
			{
				log?.LogWarning("HoMM3 custom biome registration could not patch natural packed-build probe "
					+ rendererType.FullName
					+ "."
					+ method.Name
					+ ": "
					+ ex.GetType().Name
					+ ": "
					+ ex.Message);
			}
		}
	}

	private static bool IsRejectedRendererNaturalProbeMethod(MethodInfo method)
	{
		if (method == null)
			return false;
		return GameSymbols.TerrainMaterial.RejectedRendererRebuildMethodNames
			.Any(name => string.Equals(name, method.Name, StringComparison.Ordinal));
	}

	private static Type ResolveHeroBiomeSoundType(ManualLogSource log)
	{
		var hinted = GameMember.FindType(
			GameSymbols.TerrainSound.HeroBiomeSoundTypeId,
			GameSymbols.TerrainSound.HeroBiomeSoundTypeHint);
		if (HasHeroBiomeSoundSurface(hinted))
			return hinted;

		foreach (var candidate in GameMember.EnumerateHexTypes())
		{
			if (!HasHeroBiomeSoundSurface(candidate))
				continue;
			log?.LogWarning(
				"HoMM3 custom biome registration: hero biome sound type hint "
				+ (hinted?.FullName ?? "(null)")
				+ " lacked map-build/lookup surfaces; using shape-resolved "
				+ candidate.FullName
				+ ".");
			return candidate;
		}

		return hinted;
	}

	private static bool HasHeroBiomeSoundSurface(Type type)
	{
		if (type == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		MethodInfo[] methods;
		try { methods = type.GetMethods(flags); }
		catch { return false; }
		var hasLookup = false;
		var hasBuildMap = false;
		foreach (var method in methods)
		{
			if (!hasLookup
			    && method.GetParameters().Length == 1
			    && method.GetParameters()[0].ParameterType == typeof(int)
			    && string.Equals(method.ReturnType?.Name, "EHeroSoundType", StringComparison.Ordinal))
			{
				hasLookup = true;
			}
			if (!hasBuildMap
			    && method.ReturnType == typeof(void)
			    && method.GetParameters().Length == 1
			    && method.GetParameters()[0].ParameterType == typeof(Map))
			{
				hasBuildMap = true;
			}
			if (hasLookup && hasBuildMap)
				return true;
		}
		return false;
	}

	private static Type ResolveHeroSoundEnumType(Type heroBiomeSoundType)
	{
		if (heroBiomeSoundType == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		MethodInfo[] methods;
		try { methods = heroBiomeSoundType.GetMethods(flags); }
		catch { methods = Array.Empty<MethodInfo>(); }
		foreach (var method in methods)
		{
			if (method.GetParameters().Length != 1 || method.GetParameters()[0].ParameterType != typeof(int))
				continue;
			if (string.Equals(method.ReturnType?.Name, "EHeroSoundType", StringComparison.Ordinal))
				return method.ReturnType;
		}
		return null;
	}

	private static void PrimeHeroBiomeStaticLookupMappings(Type heroBiomeSoundType, string source)
	{
		if (heroBiomeSoundType == null)
			return;
		var extended = false;
		var extendedSymbols = new List<string>();
		try
		{
			foreach (var definition in Definitions)
			{
				foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeStaticArrays)
				{
					if (TryExtendStaticArraySlot(heroBiomeSoundType, symbol, definition.TileCode, definition.SoundDonorTileCode, source))
					{
						extended = true;
						extendedSymbols.Add(symbol.Id);
					}
				}
			}
		}
		catch (Exception ex)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration could not prime static hero biome lookup mappings via "
				+ (source ?? "?")
				+ ": "
				+ ex.GetType().Name
				+ ": "
				+ ex.Message);
			return;
		}
		if (extended)
			_log?.LogWarning(
				"HoMM3 custom biome registration primed static hero biome lookup mappings via "
				+ (source ?? "?")
				+ ": "
				+ string.Join(", ", extendedSymbols.Distinct())
				+ ".");
	}

	private static void PatchHeroBiomeController(Harmony harmony, ManualLogSource log, Type heroBiomeSoundType)
	{
		var controllerType = GameMember.FindType(
			GameSymbols.TerrainSound.HeroBiomeControllerTypeId,
			GameSymbols.TerrainSound.HeroBiomeControllerTypeHint);
		if (controllerType == null)
			throw new MissingMethodException("Could not resolve hero biome sound controller type for custom biome registration.");
		var selectorFields = FindHeroBiomeControllerSelectorFields(controllerType, heroBiomeSoundType).ToArray();
		if (selectorFields.Length == 0)
			throw new MissingFieldException(controllerType.FullName, "hero biome selector field of type " + (heroBiomeSoundType?.FullName ?? "?"));
		var lifecycleMethods = FindDeclaredNoArgVoidMethodsByHintNames(
			controllerType,
			GameSymbols.TerrainSound.HeroBiomeControllerLifecycle)
			.ToList();
		if (lifecycleMethods.Count == 0)
			throw new MissingMethodException("Could not resolve hero biome sound controller lifecycle methods on " + controllerType.FullName + ".");
		var patch = new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixHeroBiomeControllerLifecycle));
		foreach (var method in lifecycleMethods)
			harmony.Patch(method, prefix: patch);
		log?.LogWarning(
			"HoMM3 custom biome registration patched hero biome sound controller "
			+ controllerType.FullName
			+ ": "
			+ string.Join(", ", lifecycleMethods.Select(method => method.Name).Distinct())
			+ "; selector field(s): "
			+ string.Join(", ", selectorFields.Select(field => field.Name))
			+ ".");
	}

	private static IEnumerable<FieldInfo> FindHeroBiomeControllerSelectorFields(Type controllerType, Type heroBiomeSoundType)
	{
		if (controllerType == null || heroBiomeSoundType == null)
			return Array.Empty<FieldInfo>();
		var fields = new List<FieldInfo>();
		foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeControllerSelectorFields)
		{
			var field = FindField(controllerType, symbol);
			if (IsHeroBiomeSelectorField(field, heroBiomeSoundType))
				fields.Add(field);
		}
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = controllerType; type != null; type = type.BaseType)
		{
			FieldInfo[] declared;
			try { declared = type.GetFields(flags | BindingFlags.DeclaredOnly); }
			catch { continue; }
			foreach (var field in declared)
			{
				if (fields.Contains(field))
					continue;
				if (IsHeroBiomeSelectorField(field, heroBiomeSoundType))
					fields.Add(field);
			}
		}
		return fields;
	}

	private static bool IsHeroBiomeSelectorField(FieldInfo field, Type heroBiomeSoundType)
	{
		if (field == null || field.IsStatic || heroBiomeSoundType == null)
			return false;
		Type fieldType;
		try { fieldType = field.FieldType; }
		catch { return false; }
		return fieldType == heroBiomeSoundType
		       || string.Equals(fieldType.FullName, heroBiomeSoundType.FullName, StringComparison.Ordinal)
		       || string.Equals(fieldType.Name, heroBiomeSoundType.Name, StringComparison.Ordinal);
	}

	private static void PatchHeroBiomeSelectors(Harmony harmony, ManualLogSource log, Type heroBiomeSoundType)
	{
		var selectorTypes = FindHeroBiomeSelectorTypes(heroBiomeSoundType).Distinct().ToArray();
		var patch = new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PostfixHeroBiomeSelectorBuildMap));
		var patched = new List<string>();
		foreach (var selectorType in selectorTypes)
		{
			foreach (var method in FindHeroBiomeSelectorBuildMapMethods(selectorType))
			{
				harmony.Patch(method, postfix: patch);
				patched.Add(selectorType.FullName + "." + method.Name);
			}
		}

		if (patched.Count == 0)
		{
			log?.LogWarning("HoMM3 custom biome registration found no extra nested hero biome selector map-build methods; using the required hero biome sound map-build hook.");
			return;
		}
		log?.LogWarning("HoMM3 custom biome registration patched hero biome selector map-build methods: " + string.Join(", ", patched) + ".");
	}

	private static IEnumerable<Type> FindHeroBiomeSelectorTypes(Type heroBiomeSoundType)
	{
		if (heroBiomeSoundType != null)
		{
			foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeSelectorFields)
			{
				var field = FindField(heroBiomeSoundType, symbol);
				Type fieldType = null;
				try { fieldType = field?.FieldType; }
				catch { fieldType = null; }
				if (fieldType != null && HasHeroBiomeSelectorBuildMapMethod(fieldType))
					yield return fieldType;
			}
		}
	}

	private static bool IsHeroBiomeSelectorType(Type type)
	{
		if (type == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		FieldInfo[] fields;
		try { fields = type.GetFields(flags); }
		catch { return false; }
		return fields.Any(IsHeroSoundArrayField) && FindHeroBiomeSelectorBuildMapMethods(type).Any();
	}

	private static bool HasHeroBiomeSelectorBuildMapMethod(Type type)
	{
		return type != null && FindHeroBiomeSelectorBuildMapMethods(type).Any();
	}

	private static bool IsHeroSoundArrayField(FieldInfo field)
	{
		var fieldType = field?.FieldType;
		if (fieldType == null)
			return false;
		if (fieldType.IsArray)
			return string.Equals(fieldType.GetElementType()?.Name, "EHeroSoundType", StringComparison.Ordinal);
		var fullName = fieldType.FullName ?? fieldType.Name;
		return fullName.IndexOf("EHeroSoundType", StringComparison.Ordinal) >= 0
		       && fullName.IndexOf("Array", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static IEnumerable<MethodInfo> FindHeroBiomeSelectorBuildMapMethods(Type type)
	{
		if (type == null)
			return Array.Empty<MethodInfo>();
		return GameMember.FindMethods(
			type,
			typeof(void),
			new[] { typeof(Map) },
			GameSymbols.TerrainSound.HeroBiomeBuildMap);
	}

	private static void PatchAmbientFogController(Harmony harmony, ManualLogSource log)
	{
		var controllerType = GameMember.FindType(
			GameSymbols.TerrainSound.AmbientFogControllerTypeId,
			GameSymbols.TerrainSound.AmbientFogControllerTypeHint,
			FindAmbientFogControllerTypeByShape);
		if (controllerType == null)
		{
			DisableAmbientFogControllerExtension("could not resolve ambient fog controller type");
			return;
		}
		if (FindField(controllerType, GameSymbols.TerrainSound.AmbientFogControllerActiveByTileCode) == null)
		{
			DisableAmbientFogControllerExtension(
				"could not resolve ambient fog controller active tile-code field on " + controllerType.FullName);
			return;
		}

		var refresh = GameMember.FindFirstMethod(
			controllerType,
			typeof(void),
			Type.EmptyTypes,
			GameSymbols.TerrainSound.AmbientFogControllerRefresh);
		var lifecycleMethods = FindDeclaredNoArgVoidMethodsByHintNames(
			controllerType,
			GameSymbols.TerrainSound.AmbientFogControllerEarlyRefresh)
			.ToList();
		if (refresh != null && lifecycleMethods.All(method => method != refresh))
			lifecycleMethods.Add(refresh);
		if (lifecycleMethods.Count == 0)
		{
			DisableAmbientFogControllerExtension("could not resolve ambient fog controller lifecycle methods on " + controllerType.FullName);
			return;
		}

		var patch = new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixAmbientFogControllerRefresh));
		foreach (var method in lifecycleMethods)
			harmony.Patch(method, prefix: patch);
		log?.LogWarning(
			"HoMM3 custom biome registration patched ambient fog controller "
			+ controllerType.FullName
			+ ": "
			+ string.Join(", ", lifecycleMethods.Select(method => method.Name).Distinct())
			+ ".");
	}

	private static Type FindAmbientFogControllerTypeByShape()
	{
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		foreach (var assembly in assemblies)
		{
			Type[] types;
			try { types = assembly.GetTypes(); }
			catch { continue; }
			foreach (var type in types)
			{
				if (type == null)
					continue;
				if (FindField(type, GameSymbols.TerrainSound.AmbientFogControllerActiveByTileCode) == null)
					continue;
				var hasRefresh = FindDeclaredNoArgVoidMethodsByHintNames(type, GameSymbols.TerrainSound.AmbientFogControllerRefresh).Any();
				var hasLifecycle = FindDeclaredNoArgVoidMethodsByHintNames(type, GameSymbols.TerrainSound.AmbientFogControllerEarlyRefresh).Any();
				if (hasRefresh && hasLifecycle)
					return type;
			}
		}
		return null;
	}

	private static IEnumerable<MethodInfo> FindDeclaredNoArgVoidMethodsByHintNames(Type type, GameSymbols.MethodSymbol symbol)
	{
		if (type == null || symbol.NameHints == null || symbol.NameHints.Length == 0)
			return Array.Empty<MethodInfo>();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		var hints = new HashSet<string>(symbol.NameHints.Where(name => !string.IsNullOrWhiteSpace(name)), StringComparer.Ordinal);
		return type.GetMethods(flags)
			.Where(method => hints.Contains(method.Name)
			                 && method.ReturnType == typeof(void)
			                 && method.GetParameters().Length == 0)
			.OrderBy(method => Array.IndexOf(symbol.NameHints, method.Name))
			.ToArray();
	}

	private static CustomBiomeDefinition[] Definitions
	{
		get
		{
			_definitions ??= LoadDefinitions();
			return _definitions;
		}
	}

	private static CustomBiomeDefinition[] LoadDefinitions()
	{
		var path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", DefinitionsPath);
		if (!File.Exists(path))
			throw new FileNotFoundException("Custom biome registration is enabled but the biome definition file is missing.", path);

		var json = File.ReadAllText(path);
		var objects = Regex.Matches(json, "\\{[^{}]*\\}");
		var definitions = new List<CustomBiomeDefinition>();
		foreach (Match objectMatch in objects)
		{
			var raw = objectMatch.Value;
			var enabled = ReadBool(raw, "enabled", true);
			if (!enabled)
				continue;
			var definition = new CustomBiomeDefinition
			{
				Id = ReadString(raw, "id", null),
				Name = ReadString(raw, "name", null),
				TileCode = ReadInt(raw, "tileCode", -1),
				MaterialDonorName = ReadString(raw, "materialDonorName", null),
				MaterialDonorTileCode = ReadInt(raw, "materialDonorTileCode", -1),
				SoundDonorTileCode = ReadInt(raw, "soundDonorTileCode", -1),
				MaterialAliasOnly = ReadBool(raw, "materialAliasOnly", false),
				TextureAssetDir = ReadString(raw, "textureAssetDir", null),
				MarkerBiomeName = ReadString(raw, "markerBiomeName", null),
				MarkerTileCode = ReadInt(raw, "markerTileCode", -1),
				MarkerTextureAssetDir = ReadString(raw, "markerTextureAssetDir", null),
				TextureFiles = ReadStringArray(raw, "textureFiles"),
				TexturesCount = ReadString(raw, "texturesCount", null),
				Mode = ReadString(raw, "mode", null),
				BlendDepth = ReadFloat(raw, "blendDepth"),
				Tiling0 = ReadFloat(raw, "tiling0"),
				HeightmapScale0 = ReadFloat(raw, "heightmapScale0"),
				Tiling1 = ReadFloat(raw, "tiling1"),
				HeightmapScale1 = ReadFloat(raw, "heightmapScale1"),
				Tiling2 = ReadFloat(raw, "tiling2"),
				HeightmapScale2 = ReadFloat(raw, "heightmapScale2")
			};
			definition.Validate(path);
			definitions.Add(definition);
		}

		if (definitions.Count == 0)
			throw new InvalidOperationException("Custom biome registration is enabled but " + path + " contains no enabled biome definitions.");
		var duplicateTile = definitions.GroupBy(definition => definition.TileCode).FirstOrDefault(group => group.Count() > 1);
		if (duplicateTile != null)
			throw new InvalidOperationException("Custom biome definitions contain duplicate tileCode " + duplicateTile.Key + ".");
		var materialLimit = 0;
		var materialLimitFlag = (string)null;
		var materialLimitDescription = (string)null;
		if (Homm3DiagnosticFlags.IsEnabled(TerrainFirstNineMaterialProbeFlagName))
		{
			materialLimit = 9;
			materialLimitFlag = TerrainFirstNineMaterialProbeFlagName;
			materialLimitDescription = "the suspected native packed-vector 0..15 ceiling; texture/color packed arrays may still be shallower";
		}
		else if (Homm3DiagnosticFlags.IsEnabled(TerrainFirstFiveMaterialProbeFlagName))
		{
			materialLimit = 5;
			materialLimitFlag = TerrainFirstFiveMaterialProbeFlagName;
			materialLimitDescription = "native packed depth 12 for Blitz/Stronghold Wasteland isolation";
		}
		if (materialLimit > 0)
		{
			var limited = definitions
				.Where(definition => definition.MaterialAliasOnly)
				.Concat(definitions.Where(definition => !definition.MaterialAliasOnly).Take(materialLimit))
				.ToList();
			_log?.LogWarning("HoMM3 custom biome registration FIRST-"
				+ materialLimit.ToString(CultureInfo.InvariantCulture)
				+ " MATERIAL DIAGNOSTIC active via "
				+ materialLimitFlag
				+ ": registering "
				+ limited.Count(definition => !definition.MaterialAliasOnly)
				+ " non-alias custom material biome(s); highest expected custom material slot should stay within "
				+ materialLimitDescription
				+ ".");
			definitions = limited;
		}
		return definitions.ToArray();
	}

	private static string DescribeDefinition(CustomBiomeDefinition definition)
	{
		return definition.Name + "(tileCode=" + definition.TileCode + ", donor=" + definition.MaterialDonorName + "/" + definition.MaterialDonorTileCode + ", soundDonor=" + definition.SoundDonorTileCode + ")";
	}

	private static string ReadString(string json, string key, string fallback)
	{
		var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"", RegexOptions.IgnoreCase);
		return match.Success ? Regex.Unescape(match.Groups[1].Value) : fallback;
	}

	private static int ReadInt(string json, string key, int fallback)
	{
		var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?\\d+)", RegexOptions.IgnoreCase);
		return match.Success && int.TryParse(match.Groups[1].Value, out var value) ? value : fallback;
	}

	private static bool ReadBool(string json, string key, bool fallback)
	{
		var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(true|false)", RegexOptions.IgnoreCase);
		return match.Success && bool.TryParse(match.Groups[1].Value, out var value) ? value : fallback;
	}

	private static float? ReadFloat(string json, string key)
	{
		var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?(?:\\d+\\.?\\d*|\\d*\\.\\d+))", RegexOptions.IgnoreCase);
		if (!match.Success)
			return null;
		return float.TryParse(match.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) ? value : null;
	}
	private static string[] ReadStringArray(string json, string key)
	{
		var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\\[(.*?)\\]", RegexOptions.IgnoreCase | RegexOptions.Singleline);
		if (!match.Success)
			return Array.Empty<string>();
		return Regex.Matches(match.Groups[1].Value, "\"((?:\\\\.|[^\"])*)\"")
			.Cast<Match>()
			.Select(item => Regex.Unescape(item.Groups[1].Value))
			.Where(item => !string.IsNullOrWhiteSpace(item))
			.ToArray();
	}

	private static void PostfixInstanceGetter(SoTerrainMaterial __result)
	{
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.instance-getter.postfix", __result);
	}

	private static void PrefixMaterialGetter(SoTerrainMaterial __instance)
	{
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.material-getter.prefix", __instance);
	}

	private static void PrefixRendererConstructor()
	{
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.renderer-ctor.prefix", null, census: true);
		EnsureTerrainGlobalVectorArrayCapacity("terrain renderer constructor prefix");
	}

	private static void PostfixRendererConstructor(object __instance)
	{
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.renderer-ctor.postfix", __instance, census: true);
		EnsureRendererPackedStateCapacity(__instance, __instance?.GetType(), "terrain renderer constructor postfix");
	}

	private static bool HasActiveMapCustomVisualTileCodes()
	{
		return _currentMapVisualSlotScopeKnown
		       && _currentMapCustomVisualTileCodes != null
		       && _currentMapCustomVisualTileCodes.Count > 0;
	}

	private static bool HasActiveMapNativeWaterTerrainTileCodes()
	{
		return _currentMapVisualSlotScopeKnown
		       && _currentMapNativeWaterTerrainTileCodes != null
		       && _currentMapNativeWaterTerrainTileCodes.Count > 0;
	}

	private static void PrefixRendererPrepareMap(object __instance, Map __0)
	{
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.prefix.enter", __instance, census: true);
		LogTerrainBindingProbeSafePoint("prepare-map.prefix.enter", __instance);
		SetActiveMapVisualSlotScope(__0, "terrain renderer prepare-map prefix");
		// The renderer survives map unload. Replace its complete lookup even when the next map has no custom tiles.
		SeedRendererLookupDictionary(__instance, "terrain renderer prepare-map prefix", _currentMapCustomVisualTileCodes);
		if (HasActiveMapCustomVisualTileCodes())
		{
			EnsureRendererPackedStateCapacity(__instance, __instance?.GetType(), "terrain renderer prepare-map prefix");
		}
		else if (HasActiveMapNativeWaterTerrainTileCodes())
		{
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.prefix.native-water-lookup-only", __instance, census: true);
		}
		else
		{
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.prefix.stock-lookup-replaced", __instance, census: true);
		}
		LogTerrainBindingProbeSafePoint("prepare-map.prefix.exit", __instance);
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.prefix.exit", __instance, census: true);
	}



	private static bool EnsureTerrainGlobalVectorArrayCapacity(string source)
	{
		if (_terrainGlobalVectorArraysPreseeded)
			return true;
		if (_terrainGlobalVectorArrayPreseedAttempted && !string.IsNullOrEmpty(_terrainGlobalVectorArrayPreseedFailure))
			return false;
		_terrainGlobalVectorArrayPreseedAttempted = true;
		try
		{
			// Hex/TerrainMap declares Terrain_BiomParams / Tilings / HeightmapScales at length 16.
			// SetGlobalVectorArray(30) is capped by Unity ("30 vs 16") and does not enlarge the
			// shader property. Match the declared size here; PDM_5 packed-state arrays still
			// expand to CustomBiomePackedSlotCapacity separately.
			var capacity = GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit;
			var values = new Il2CppStructArray<Vector4>(capacity);
			foreach (var propertyName in GameSymbols.TerrainMaterial.TerrainMapPackedVectorArrayProperties)
			{
				if (string.IsNullOrWhiteSpace(propertyName))
					throw new InvalidOperationException("centralized terrain packed vector property name was empty");
				var propertyId = Shader.PropertyToID(propertyName);
				Shader.SetGlobalVectorArray(propertyId, values);
			}
			_terrainGlobalVectorArraysPreseeded = true;
			_terrainGlobalVectorArrayPreseedFailure = null;
			if (_terrainGlobalVectorArrayPreseedLogsRemaining > 0)
			{
				_terrainGlobalVectorArrayPreseedLogsRemaining--;
				_log?.LogWarning(
					"HoMM3 custom biome registration preseeded terrain packed global vector arrays to "
					+ capacity.ToString(CultureInfo.InvariantCulture)
					+ " (shader-declared NativePackedMaterialSlotLimit; PDM_5 packed-state uses "
					+ GameSymbols.TerrainMaterial.CustomBiomePackedSlotCapacity.ToString(CultureInfo.InvariantCulture)
					+ ") via "
					+ (source ?? "?")
					+ ": "
					+ string.Join("/", GameSymbols.TerrainMaterial.TerrainMapPackedVectorArrayProperties)
					+ ".");
			}
			return true;
		}
		catch (Exception ex)
		{
			_terrainGlobalVectorArrayPreseedFailure = ex.GetType().Name + ": " + ex.Message;
			_log?.LogWarning(
				"HoMM3 custom biome registration could not preseed terrain packed global vector arrays via "
				+ (source ?? "?")
				+ "; custom packed terrain rebuild will stay disabled to avoid Unity vector-array size rejection: "
				+ _terrainGlobalVectorArrayPreseedFailure);
			return false;
		}
	}

	private static bool CanUseCustomPackedTerrainRebuild(string source)
	{
		if (EnsureTerrainGlobalVectorArrayCapacity(source))
			return true;
		if (_rebuildRejectionLogsRemaining > 0)
		{
			_rebuildRejectionLogsRemaining--;
			_log?.LogWarning(
				"HoMM3 custom biome registration skipped custom packed terrain rebuild via "
				+ (source ?? "?")
				+ " because terrain global vector arrays were not safely preseeded to "
				+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
				+ " (shader-declared Terrain_BiomParams size): "
				+ (_terrainGlobalVectorArrayPreseedFailure ?? "unknown failure")
				+ ".");
		}
		return false;
	}

	private static void EnsureRendererPackedStateCapacity(object renderer, Type rendererType, string source)
	{
		if (renderer == null || rendererType == null)
			return;
		if (!CanUseCustomPackedTerrainRebuild(source))
			return;
		var changes = ExpandRendererPackedStateArrays(
			renderer,
			rendererType,
			GameSymbols.TerrainMaterial.CustomBiomePackedSlotCapacity);
		if (changes.Count == 0)
			return;
		_log?.LogWarning(
			"HoMM3 custom biome registration expanded terrain renderer packed-state arrays via "
			+ (source ?? "?")
			+ ": "
			+ string.Join(", ", changes)
			+ ".");
	}

	private static void PrefixHeroBiomeSoundBuildMap(object __instance)
	{
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.hero-biome-sound.prefix", __instance);
		EnsureBiomeSoundMappings(__instance, null, "hero biome sound map-build prefix");
	}

	private static void PostfixHeroBiomeSoundBuildMap(object __instance)
	{
		EnsureBiomeSoundMappings(__instance, null, "hero biome sound map-build postfix");
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.hero-biome-sound.postfix", __instance);
	}

	private static void PostfixHeroBiomeSelectorBuildMap(object __instance, MethodBase __originalMethod)
	{
		EnsureHeroBiomeSelectorMappings(__instance, "hero biome selector " + (__originalMethod?.Name ?? "?") + " postfix");
	}

	private sealed class TerrainBindingProbeSnapshot
	{
		public string PackedArray;
		public string RendererTextures;
		public string PackedState;
		public string RendererStaticInts;
		public string SingletonBiomes;
		public string RendererTerrainBiomes;
		public string TerrainMaterial;
		public string MaterialTextures;
		public string Dictionaries;
		public int RequiredSlot;
	}

	private static void PrefixRendererPackedBuildNaturalCallProbe(object __instance, out TerrainBindingProbeSnapshot __state)
	{
		__state = null;
		if (__instance == null || _packedBuildNaturalCallLogsRemaining <= 0)
			return;
		try
		{
			__state = CaptureTerrainBindingProbeSnapshot(__instance, __instance.GetType());
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 custom biome registration terrain binding probe could not capture pre-call snapshot: "
				+ ex.GetType().Name
				+ ": "
				+ ex.Message);
		}
	}

	private static void PostfixRendererPackedBuildNaturalCallProbe(object __instance, MethodBase __originalMethod, object[] __args, TerrainBindingProbeSnapshot __state)
	{
		if (__instance == null || _packedBuildNaturalCallLogsRemaining <= 0)
			return;
		_packedBuildNaturalCallLogsRemaining--;
		try
		{
			var rendererType = __instance.GetType();
			var after = CaptureTerrainBindingProbeSnapshot(__instance, rendererType);
			var before = __state ?? new TerrainBindingProbeSnapshot();
			_log?.LogWarning(
				"HoMM3 custom biome registration terrain binding probe "
				+ DescribeRendererType(__instance, rendererType)
				+ "."
				+ (__originalMethod?.Name ?? "?")
				+ "("
				+ DescribeProbeArgs(__args)
				+ ")"
				+ " changed=["
				+ DescribeTerrainBindingProbeChanges(before, after)
				+ "]"
				+ " requiredSlot="
				+ after.RequiredSlot
				+ " before={"
				+ DescribeTerrainBindingProbeSnapshot(before)
				+ "} after={"
				+ DescribeTerrainBindingProbeSnapshot(after)
				+ "}.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 custom biome registration terrain binding probe failed after "
				+ (__originalMethod?.Name ?? "?")
				+ ": "
				+ ex.GetType().Name
				+ ": "
				+ ex.Message);
		}
	}

	private static void LogTerrainBindingProbeSafePoint(string point, object renderer)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(TerrainBindingProbeFlagName) || renderer == null)
			return;
		try
		{
			var rendererType = renderer.GetType();
			var snapshot = CaptureTerrainBindingProbeSnapshot(renderer, rendererType);
			_log?.LogWarning(
				"HoMM3 custom biome registration terrain binding probe safe-point "
				+ point
				+ " "
				+ DescribeRendererType(renderer, rendererType)
				+ " requiredSlot="
				+ snapshot.RequiredSlot
				+ " snapshot={"
				+ DescribeTerrainBindingProbeSnapshot(snapshot)
				+ "}.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 custom biome registration terrain binding probe safe-point "
				+ point
				+ " failed: "
				+ ex.GetType().Name
				+ ": "
				+ ex.Message);
		}
	}

	private static TerrainBindingProbeSnapshot CaptureTerrainBindingProbeSnapshot(object renderer, Type rendererType)
	{
		var accessor = FindRendererTextureArrayAccessor(renderer, rendererType);
		Texture2DArray packedArray = null;
		if (accessor.IsValid)
		{
			try { packedArray = accessor.Get(renderer) as Texture2DArray; }
			catch { packedArray = null; }
		}
		var terrain = SoTerrainMaterial.instance;
		var rendererTerrain = FindRendererTerrainMaterial(renderer, rendererType);
		var material = terrain?.terrainMaterial;
		return new TerrainBindingProbeSnapshot
		{
			PackedArray = (accessor.IsValid ? accessor.Name : "(none)") + "=" + DescribeTextureForAudit(packedArray),
			RendererTextures = DescribeRendererTextureFieldsForAudit(renderer, rendererType),
			PackedState = DescribeRendererPackedStateFieldsForAudit(renderer, rendererType),
			RendererStaticInts = DescribeRendererStaticIntsForAudit(rendererType),
			SingletonBiomes = DescribeTerrainBiomeState(terrain),
			RendererTerrainBiomes = DescribeTerrainBiomeState(rendererTerrain),
			TerrainMaterial = (material ? material.name : "(null)") + "/" + (material && material.shader ? material.shader.name : "?"),
			MaterialTextures = DescribeMaterialTexturesForAudit(material),
			Dictionaries = DescribeRendererDictionaries(renderer, rendererType),
			RequiredSlot = GetHighestCustomMaterialSlot(renderer, rendererType)
		};
	}

	private static string DescribeTerrainBindingProbeChanges(TerrainBindingProbeSnapshot before, TerrainBindingProbeSnapshot after)
	{
		if (after == null)
			return "after-missing";
		var changes = new List<string>();
		AddChange(changes, "packed", before?.PackedArray, after.PackedArray);
		AddChange(changes, "rendererTextures", before?.RendererTextures, after.RendererTextures);
		AddChange(changes, "packedState", before?.PackedState, after.PackedState);
		AddChange(changes, "rendererStaticInts", before?.RendererStaticInts, after.RendererStaticInts);
		AddChange(changes, "singletonBiomes", before?.SingletonBiomes, after.SingletonBiomes);
		AddChange(changes, "rendererTerrainBiomes", before?.RendererTerrainBiomes, after.RendererTerrainBiomes);
		AddChange(changes, "terrainMaterial", before?.TerrainMaterial, after.TerrainMaterial);
		AddChange(changes, "materialTextures", before?.MaterialTextures, after.MaterialTextures);
		AddChange(changes, "dictionaries", before?.Dictionaries, after.Dictionaries);
		if ((before?.RequiredSlot ?? int.MinValue) != after.RequiredSlot)
			changes.Add("requiredSlot");
		return changes.Count == 0 ? "none" : string.Join(",", changes);
	}

	private static void AddChange(List<string> changes, string name, string before, string after)
	{
		if (!string.Equals(before ?? string.Empty, after ?? string.Empty, StringComparison.Ordinal))
			changes.Add(name);
	}

	private static string DescribeTerrainBindingProbeSnapshot(TerrainBindingProbeSnapshot snapshot)
	{
		if (snapshot == null)
			return "(missing)";
		return "packed="
		       + snapshot.PackedArray
		       + " rendererTextures=["
		       + snapshot.RendererTextures
		       + "] packedState=["
		       + snapshot.PackedState
		       + "] rendererStaticInts=["
		       + snapshot.RendererStaticInts
		       + "] singletonBiomes=["
		       + snapshot.SingletonBiomes
		       + "] rendererTerrainBiomes=["
		       + snapshot.RendererTerrainBiomes
		       + "] terrainMaterial="
		       + snapshot.TerrainMaterial
		       + " materialTextures=["
		       + snapshot.MaterialTextures
		       + "] dictionaries=["
		       + snapshot.Dictionaries
		       + "]";
	}

	private static string DescribeProbeArgs(object[] args)
	{
		if (args == null || args.Length == 0)
			return "";
		try
		{
			return string.Join(",", args.Select(arg =>
			{
				if (arg == null)
					return "null";
				if (arg is int || arg is bool || arg is byte || arg is float || arg is double)
					return Convert.ToString(arg, CultureInfo.InvariantCulture);
				return arg.GetType().Name;
			}));
		}
		catch
		{
			return "?";
		}
	}

	private static SoTerrainMaterial FindRendererTerrainMaterial(object renderer, Type rendererType)
	{
		if (renderer == null || rendererType == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var field in rendererType.GetFields(flags))
		{
			if (!GameMember.TypesEquivalent(field.FieldType, typeof(SoTerrainMaterial)))
				continue;
			try
			{
				if (field.GetValue(renderer) is SoTerrainMaterial terrain)
					return terrain;
			}
			catch
			{
				return null;
			}
		}
		return null;
	}

	private static string DescribeTerrainBiomeState(SoTerrainMaterial terrain)
	{
		if (terrain == null)
			return "(null)";
		try
		{
			var pointer = terrain is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero
				? "@0x" + il2Cpp.Pointer.ToString("x")
				: string.Empty;
			var biomes = terrain.biomes;
			if (biomes == null)
				return pointer + ":biomes=(null)";
			var rows = new List<string>();
			var nullCount = 0;
			for (var i = 0; i < biomes.Length; i++)
			{
				var biome = biomes[i];
				if (biome == null)
				{
					nullCount++;
					continue;
				}
				if (i < 8 || Definitions.Any(definition => definition.TileCode == biome.tileCode))
				{
					rows.Add(
						i.ToString(CultureInfo.InvariantCulture)
						+ ":"
						+ biome.tileCode.ToString(CultureInfo.InvariantCulture)
						+ "/"
						+ (biome.name ?? "?")
						+ "/tc="
						+ biome.texturesCount.ToString(CultureInfo.InvariantCulture)
						+ "/mode="
						+ biome.mode.ToString(CultureInfo.InvariantCulture)
						+ "/tex="
						+ DescribeTextureForAudit(biome.texture0)
						+ ","
						+ DescribeTextureForAudit(biome.texture1)
						+ ","
						+ DescribeTextureForAudit(biome.texture2));
				}
			}
			return pointer
			       + ":len="
			       + biomes.Length.ToString(CultureInfo.InvariantCulture)
			       + ":nulls="
			       + nullCount.ToString(CultureInfo.InvariantCulture)
			       + ":"
			       + (rows.Count == 0 ? "(no-sampled-biomes)" : string.Join("|", rows));
		}
		catch (Exception ex)
		{
			return "(unreadable:" + ex.GetType().Name + ")";
		}
	}

	private static bool EnsureHeroBiomeSoundLookupMappings(object heroSoundInstance, string source)
	{
		if (heroSoundInstance == null)
			return false;
		var heroType = heroSoundInstance.GetType();
		var extended = false;
		var extendedSymbols = new List<string>();
		foreach (var definition in Definitions)
		{
			foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeStaticArrays)
			{
				if (TryExtendStaticArraySlot(heroType, symbol, definition.TileCode, definition.SoundDonorTileCode, source))
				{
					extended = true;
					extendedSymbols.Add(symbol.Id);
				}
			}
			foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeInstanceArrays)
			{
				if (ExtendInstanceArraySlot(heroSoundInstance, heroType, symbol, definition.TileCode, definition.SoundDonorTileCode, source))
				{
					extended = true;
					extendedSymbols.Add(symbol.Id);
				}
			}
		}
		if (EnsureHeroBiomeSelectorMappings(heroSoundInstance, source))
		{
			extended = true;
			extendedSymbols.Add("nested-self-selector");
		}
		foreach (var selector in FindHeroBiomeSelectorInstances(heroSoundInstance, heroType))
		{
			if (EnsureHeroBiomeSelectorMappings(selector, source + " nested selector"))
			{
				extended = true;
				extendedSymbols.Add("nested-selector");
			}
		}
		if (extended)
			_log?.LogWarning(
				"HoMM3 custom biome registration extended hero biome lookup mappings via "
				+ source
				+ ": "
				+ string.Join(", ", extendedSymbols.Distinct())
				+ ".");
		return extended;
	}

	private static void PrefixHeroBiomeControllerLifecycle(object __instance, MethodBase __originalMethod)
	{
		EnsureHeroBiomeControllerSelectorMappings(__instance, "hero biome controller " + (__originalMethod?.Name ?? "?") + " prefix");
	}

	private static void PrefixAmbientBiomeSoundBuild(object __instance)
	{
		EnsureBiomeSoundMappings(null, __instance, "ambient biome sound build prefix");
	}

	private static void PrefixAmbientBiomeGetSoundsVolume(object __instance)
	{
		EnsureBiomeSoundMappings(null, __instance, "ambient biome GetSoundsVolume prefix");
	}

	private static Type ResolveAmbientBiomeSoundType(ManualLogSource log)
	{
		var hinted = GameMember.FindType(
			GameSymbols.TerrainSound.AmbientBiomeSoundTypeId,
			GameSymbols.TerrainSound.AmbientBiomeSoundTypeHint,
			FindAmbientBiomeSoundTypeByShape);
		if (hinted != null && HasAmbientBiomeSoundSurface(hinted))
			return hinted;
		var shaped = FindAmbientBiomeSoundTypeByShape();
		if (shaped != null)
		{
			log?.LogWarning(
				"HoMM3 custom biome registration resolved ambient biome sound type via GetSoundsVolume shape fallback to "
				+ shaped.FullName
				+ " (update AmbientBiomeSoundTypeHint).");
			return shaped;
		}
		return hinted;
	}

	private static Type FindAmbientBiomeSoundTypeByShape()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types; }
			catch { continue; }
			if (types == null)
				continue;
			for (var i = 0; i < types.Length; i++)
			{
				var type = types[i];
				if (HasAmbientBiomeSoundSurface(type))
					return type;
			}
		}
		return null;
	}

	private static bool HasAmbientBiomeSoundSurface(Type type)
	{
		if (type == null)
			return false;
		return GameMember.FindMethodsByNames(
			type,
			3,
			GameSymbols.TerrainSound.AmbientBiomeGetVolumes.Id,
			GameSymbols.TerrainSound.AmbientBiomeGetVolumes.NameHints).Length > 0;
	}

	private static void PrefixAmbientFogControllerRefresh(object __instance, MethodBase __originalMethod)
	{
		if (_ambientFogControllerRefreshDepth > 0)
			return;
		_ambientFogControllerRefreshDepth++;
		try
		{
			EnsureAmbientFogControllerMappings(__instance, "ambient fog controller " + (__originalMethod?.Name ?? "?") + " prefix");
		}
		finally
		{
			_ambientFogControllerRefreshDepth--;
		}
	}

    private static void SetActiveMapVisualSlotScope(Map map, string source)
    {
        if (!TryReadActiveMapCustomVisualTileCodes(map, out var tileCodes, out var nativeWaterTerrainTileCodes, out var usesDisplayWaterAlias, out var width, out var height, out var reason))
            throw new InvalidOperationException(
                "Custom biome registration could not resolve active map tile scope for custom terrain material slot compaction via "
                + (source ?? "?")
                + ": "
                + reason
                + ".");
        var changed = !_currentMapVisualSlotScopeKnown
            || _currentMapCustomVisualTileCodes == null
            || !_currentMapCustomVisualTileCodes.SetEquals(tileCodes)
            || _currentMapNativeWaterTerrainTileCodes == null
            || !_currentMapNativeWaterTerrainTileCodes.SetEquals(nativeWaterTerrainTileCodes)
            || _currentMapUsesDisplayWaterAlias != usesDisplayWaterAlias
            || _currentMapPackedLayerWidth != width
            || _currentMapPackedLayerHeight != height;
        _currentMapVisualSlotScopeKnown = true;
        _currentMapCustomVisualTileCodes = tileCodes;
        _currentMapNativeWaterTerrainTileCodes = nativeWaterTerrainTileCodes;
        _currentMapUsesDisplayWaterAlias = usesDisplayWaterAlias;
        _currentMapPackedLayerWidth = width;
        _currentMapPackedLayerHeight = height;
        _currentMapTileCounts = _scanTileCounts;
        if (changed)
            _currentMapDemotedCustomTileCodes = new HashSet<int>();
        // Same-size reloads can rebuild terrain renderers without changing the custom tile set.
        // Invalidate animation bindings for every renderer scope; compact material slots only when the scope shape changes.
        _currentMapVisualSlotScopeGeneration++;
        ValidatedRendererKeys.Clear();
        SeededRendererKeys.Clear();
        RebuiltRendererKeys.Clear();
        ManagedExtendedRendererKeys.Clear();
        Homm3TerrainWaterAnimator.ResetBindingsForMapScopeChange(source);
        Homm3HomecomingNativeWaterMeshBridge.ResetCompletedScopesForMapScopeChange(source);
        if (changed)
        {
            _activeMapMaterialSlotsApplied = false;
        }
        _log?.LogWarning(
            "HoMM3 custom biome registration resolved active map custom visual terrain tileCode(s) for slot compaction via "
            + (source ?? "?")
            + ": "
            + DescribeActiveMapCustomVisualTileCodes()
            + "; nativeWaterTerrainTileCode(s)="
            + DescribeActiveMapNativeWaterTerrainTileCodes()
            + "; displayWaterAlias="
            + (_currentMapUsesDisplayWaterAlias ? "present" : "absent")
            + "; packedLayer="
            + DescribeCurrentPackedLayerShape()
            + ".");
    }
	internal static bool IsTerrainWaterAnimationBindingCurrent(int mapScopeGeneration)
	{
		return _currentMapVisualSlotScopeKnown && mapScopeGeneration == _currentMapVisualSlotScopeGeneration;
	}

	private static CustomBiomeDefinition[] ResolveActiveMapVisualDefinitions()
	{
		if (!_currentMapVisualSlotScopeKnown || _currentMapCustomVisualTileCodes == null)
			throw new InvalidOperationException("Custom biome registration cannot resolve active map visual definitions before terrain prepare-map establishes tile scope.");
		return Definitions
			.Where(definition => !definition.MaterialAliasOnly
				&& _currentMapCustomVisualTileCodes.Contains(definition.TileCode)
				&& !_currentMapDemotedCustomTileCodes.Contains(definition.TileCode))
			.ToArray();
	}

	private static string DescribeActiveMapCustomVisualTileCodes()
	{
		if (!_currentMapVisualSlotScopeKnown)
			return "<scope-unset>";
		if (_currentMapCustomVisualTileCodes == null || _currentMapCustomVisualTileCodes.Count == 0)
			return "<none>";
		return string.Join(",", _currentMapCustomVisualTileCodes.OrderBy(value => value).Select(value => value.ToString(CultureInfo.InvariantCulture)));
	}

	private static string DescribeActiveMapNativeWaterTerrainTileCodes()
	{
		if (!_currentMapVisualSlotScopeKnown)
			return "<scope-unset>";
		if (_currentMapNativeWaterTerrainTileCodes == null || _currentMapNativeWaterTerrainTileCodes.Count == 0)
			return "<none>";
		return string.Join(",", _currentMapNativeWaterTerrainTileCodes.OrderBy(value => value).Select(value => value.ToString(CultureInfo.InvariantCulture)));
	}

    private static bool TryReadActiveMapCustomVisualTileCodes(Map map, out HashSet<int> tileCodes, out HashSet<int> nativeWaterTerrainTileCodes, out bool usesDisplayWaterAlias, out int width, out int height, out string reason)
    {
        tileCodes = new HashSet<int>();
        nativeWaterTerrainTileCodes = new HashSet<int>();
        _scanTileCounts = new Dictionary<int, int>();
        usesDisplayWaterAlias = false;
        width = 0;
        height = 0;
        reason = null;
        if (map == null)
        {
            reason = "map argument was null";
            return false;
        }
        if (!TryGetMapData(map, out var mapData))
        {
            reason = "mapData was unresolved";
            return false;
        }
        var raw = TryReadFirstMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataTilesMapMembers);
        if (raw == null)
        {
            reason = "tilesMap member was missing";
            return false;
        }
        if (!TryReadMapDataDimensions(mapData, raw, out width, out height, out reason))
            return false;
        var customVisualTileCodes = new HashSet<int>(Definitions.Where(definition => !definition.MaterialAliasOnly).Select(definition => definition.TileCode));
        var displayWaterAliasTileCodes = new HashSet<int>(Definitions.Where(definition => definition.MaterialAliasOnly).Select(definition => definition.TileCode));
        if (raw is byte[] bytes)
        {
            for (var i = 0; i < bytes.Length; i++)
                ConsiderTilesMapTile(bytes[i], tileCodes, nativeWaterTerrainTileCodes, customVisualTileCodes, displayWaterAliasTileCodes, ref usesDisplayWaterAlias);
            return true;
        }
        if (raw is Il2CppStructArray<byte> il2CppBytes)
        {
            for (var i = 0; i < il2CppBytes.Length; i++)
                ConsiderTilesMapTile(il2CppBytes[i], tileCodes, nativeWaterTerrainTileCodes, customVisualTileCodes, displayWaterAliasTileCodes, ref usesDisplayWaterAlias);
            return true;
        }
        if (raw is Array array)
        {
            try
            {
                for (var i = 0; i < array.Length; i++)
                {
                    ConsiderTilesMapTile(
                        Convert.ToInt32(array.GetValue(i), CultureInfo.InvariantCulture),
                        tileCodes,
                        nativeWaterTerrainTileCodes,
                        customVisualTileCodes,
                        displayWaterAliasTileCodes,
                        ref usesDisplayWaterAlias);
                }
                return true;
            }
            catch (Exception ex)
            {
                reason = "tilesMap array conversion failed: " + ex.Message;
                return false;
            }
        }
        reason = "unsupported tilesMap type " + raw.GetType().FullName;
        return false;
    }

    private static void ConsiderTilesMapTile(
        int tile,
        HashSet<int> tileCodes,
        HashSet<int> nativeWaterTerrainTileCodes,
        HashSet<int> customVisualTileCodes,
        HashSet<int> displayWaterAliasTileCodes,
        ref bool usesDisplayWaterAlias)
    {
        _scanTileCounts.TryGetValue(tile, out var count);
        _scanTileCounts[tile] = count + 1;
        if (customVisualTileCodes.Contains(tile))
            tileCodes.Add(tile);
        if (GameSymbols.HomecomingBoatTravel.IsRetiredGoldenEraWaterTileCode(tile))
            nativeWaterTerrainTileCodes.Add(tile);
        if (!usesDisplayWaterAlias && displayWaterAliasTileCodes.Contains(tile))
            usesDisplayWaterAlias = true;
    }

    private static bool TryReadMapDataDimensions(object mapData, object tilesMap, out int width, out int height, out string reason)
    {
        width = 0;
        height = 0;
        reason = null;
        if (!TryReadPositiveIntMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeXMembers, out width, out reason))
        {
            reason = "sizeX_ member was unreadable: " + reason;
            return false;
        }
        if (!TryReadPositiveIntMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeZMembers, out height, out reason))
        {
            reason = "sizeZ_ member was unreadable: " + reason;
            return false;
        }
        var tileLength = ArrayLikeLength(tilesMap);
        if (tileLength <= 0)
        {
            reason = "tilesMap length was not positive";
            return false;
        }
        var expectedLength = (long)width * height;
        if (expectedLength != tileLength)
        {
            reason = "sizeX_/sizeZ_ "
                     + width.ToString(CultureInfo.InvariantCulture)
                     + "x"
                     + height.ToString(CultureInfo.InvariantCulture)
                     + " does not match tilesMap length "
                     + tileLength.ToString(CultureInfo.InvariantCulture);
            return false;
        }
        return true;
    }

    private static bool TryReadPositiveIntMember(object instance, string[] names, out int value, out string reason)
    {
        value = 0;
        reason = null;
        var raw = TryReadFirstMember(instance, names);
        if (raw == null)
        {
            reason = "member not found";
            return false;
        }
        try
        {
            value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
        }
        catch (Exception ex)
        {
            reason = raw.GetType().FullName + " conversion failed: " + ex.Message;
            return false;
        }
        if (value <= 0)
        {
            reason = "value was " + value.ToString(CultureInfo.InvariantCulture);
            return false;
        }
        return true;
    }
	private static bool TryGetMapData(object value, out object mapData)
	{
		mapData = null;
		if (value == null)
			return false;
		if (value is MapData)
		{
			mapData = value;
			return true;
		}
		var direct = InvokeFirstNoArg(value, typeof(MapData), GameSymbols.HomecomingBoatTravel.MapData);
		if (direct == null)
			return false;
		mapData = direct;
		return true;
	}

	private static object InvokeFirstNoArg(object obj, Type expectedReturnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null || expectedReturnType == null || symbol.NameHints == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method == null || !expectedReturnType.IsAssignableFrom(method.ReturnType))
					continue;
				try { return method.Invoke(obj, null); }
				catch { }
			}
		}
		return null;
	}

	private static object TryReadFirstMember(object instance, string[] names)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			var value = TryReadMember(instance, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryReadMember(object instance, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = instance.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(instance);
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(instance, null);
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null)
					return method.Invoke(instance, null);
			}
			catch { }
		}
		return null;
	}
	private static void Apply(SoTerrainMaterial terrain, string source, bool force = false)
	{
		if (terrain == null)
			return;
		if (!force && _activeMapMaterialSlotsApplied)
			return;
		if (!EnsureTerrainGlobalVectorArrayCapacity(source + " terrain material apply"))
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration refused to mutate SoTerrainMaterial.biomes via "
				+ (source ?? "?")
				+ " before terrain packed global vector arrays were preseeded to "
				+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
				+ " (shader-declared Terrain_BiomParams size): "
				+ (_terrainGlobalVectorArrayPreseedFailure ?? "unknown failure")
				+ ".");
			return;
		}
		var biomes = terrain.biomes;
		if (biomes == null || biomes.Length == 0)
			throw new InvalidOperationException("Custom biome registration could not inspect SoTerrainMaterial.biomes.");

		var visualDefinitions = Definitions.Where(definition => !definition.MaterialAliasOnly).ToArray();
		var customVisualTileCodes = new HashSet<int>(visualDefinitions.Select(definition => definition.TileCode));
		_currentMapDemotedCustomTileCodes = new HashSet<int>();
		var activeVisualDefinitions = ResolveActiveMapVisualDefinitions();
		var nonCustomBiomes = new List<SoTerrainMaterial.Biome>();
		for (var i = 0; i < biomes.Length; i++)
		{
			var biome = biomes[i];
			if (biome == null)
				continue;
			if (customVisualTileCodes.Contains(biome.tileCode))
				continue;
			// Water shells (18-22) are clones a previous Apply appended; BuildActiveBiomeTable re-adds them per map.
			// Keeping them here would count them twice in the over-limit plan and demote every custom terrain.
			if (GameSymbols.HomecomingBoatTravel.IsRetiredGoldenEraWaterTileCode(biome.tileCode))
				continue;
			nonCustomBiomes.Add(biome);
		}
		if (_nativeBiomeSnapshot == null)
		{
			_nativeBiomeSnapshot = nonCustomBiomes
				.Where(biome => !GameSymbols.HomecomingBoatTravel.IsRetiredGoldenEraWaterTileCode(biome.tileCode))
				.ToList();
		}
		// Restore native rows an earlier over-limit map pruned, so this map sees the full native table again.
		foreach (var native in _nativeBiomeSnapshot)
		{
			if (!nonCustomBiomes.Any(biome => biome.tileCode == native.tileCode))
				nonCustomBiomes.Add(native);
		}

		var activeBiomes = BuildActiveBiomeTable(nonCustomBiomes, activeVisualDefinitions, source);
		var pruned = false;
		if (activeBiomes.Count > GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit)
		{
			// Over the shader's fixed float4[16] packed arrays (Hex/TerrainMap): keep only native rows the map
			// needs, then render the least-used custom terrains with their donor's material until it fits.
			var keptNative = PlanOverLimitNativeRows(nonCustomBiomes, ref activeVisualDefinitions);
			activeBiomes = BuildActiveBiomeTable(keptNative, activeVisualDefinitions, source);
			pruned = true;
			_log?.LogWarning(
				"HoMM3 custom biome registration pruned the terrain material table to fit the native packed material slot limit "
				+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
				+ " via " + (source ?? "?")
				+ ": native rows kept=" + string.Join(",", keptNative.Select(biome => biome.tileCode.ToString(CultureInfo.InvariantCulture)))
				+ " of " + nonCustomBiomes.Count.ToString(CultureInfo.InvariantCulture)
				+ "; custom tileCode(s) drawn with donor material="
				+ (_currentMapDemotedCustomTileCodes.Count == 0
					? "<none>"
					: string.Join(",", _currentMapDemotedCustomTileCodes.OrderBy(value => value).Select(value => value.ToString(CultureInfo.InvariantCulture))))
				+ "; totalMaterialSlots=" + activeBiomes.Count.ToString(CultureInfo.InvariantCulture) + ".");
		}
		_nativeBiomesPruned = pruned;

		if (activeBiomes.Count > GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit)
			throw new InvalidOperationException(
				"Custom biome registration active-map custom visual terrain slot compaction produced "
				+ activeBiomes.Count.ToString(CultureInfo.InvariantCulture)
				+ " material slot(s), exceeding native packed material slot limit "
				+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
				+ ". Active custom tileCode(s): "
				+ DescribeActiveMapCustomVisualTileCodes()
				+ ".");

		var extended = new Il2CppReferenceArray<SoTerrainMaterial.Biome>(activeBiomes.Count);
		for (var i = 0; i < activeBiomes.Count; i++)
			extended[i] = activeBiomes[i];
		terrain.biomes = extended;

		_log?.LogWarning(
			"HoMM3 custom biome registration applied active-map custom visual terrain slot compaction via "
			+ source
			+ ": activeCustomTileCode(s)="
			+ DescribeActiveMapCustomVisualTileCodes()
			+ "; activeVisualDefinition(s)="
			+ string.Join(", ", activeVisualDefinitions.Select(DescribeDefinition))
			+ "; totalMaterialSlots="
			+ activeBiomes.Count.ToString(CultureInfo.InvariantCulture)
			+ "/"
			+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
			+ ".");
		LogBiomeSlotAudit(terrain, source);

		_activeMapMaterialSlotsApplied = _currentMapVisualSlotScopeKnown;
	}

	private static List<SoTerrainMaterial.Biome> BuildActiveBiomeTable(
		List<SoTerrainMaterial.Biome> nativeRows,
		CustomBiomeDefinition[] activeVisualDefinitions,
		string source)
	{
		var activeBiomes = new List<SoTerrainMaterial.Biome>(nativeRows);
		var activeVisualTileCodes = new HashSet<int>(activeVisualDefinitions.Select(definition => definition.TileCode));
		// Donors and markers resolve against the full native table: a pruned table may omit a donor row.
		var donorSource = _nativeBiomeSnapshot ?? nativeRows;
		var anyCustomOnMap = activeVisualDefinitions.Length > 0 || _currentMapDemotedCustomTileCodes.Count > 0;
		foreach (var definition in Definitions)
		{
			// Stock-only compaction must not activate custom-map donor marker textures.
			if (definition.MaterialAliasOnly || !anyCustomOnMap)
				continue;
			var donor = FindBiome(donorSource, definition.MaterialDonorName, definition.MaterialDonorTileCode);
			if (donor == null)
				throw new InvalidOperationException("Custom biome registration found no donor terrain biome for " + DescribeDefinition(definition) + ".");
			var marker = FindBiome(donorSource, definition.MarkerBiomeName, definition.MarkerTileCode) ?? donor;
			ApplyTextures(marker, definition.MarkerTextureAssetDir, definition.MarkerTextureNamePrefix, definition.TextureFiles);

			if (!activeVisualTileCodes.Contains(definition.TileCode))
				continue;
			var custom = CloneBiome(definition, donor);
			activeBiomes.Add(custom);
		}

		// Water-only maps retain the existing native-row/Sand binding instead of creating custom packed rows.
		if (anyCustomOnMap)
			AppendNativeWaterTerrainBiomesFromCatalog(activeBiomes, source);
		EnsureUniqueBiomeNamesForRmg(activeBiomes, source);
		return activeBiomes;
	}

	/// <summary>
	/// Over-limit plan (GH#29): keep native rows whose tileCode is on the map, alias donors, and the Sand seabed
	/// donor when water tiles exist; then demote the least-used custom terrains to their donor's material slot
	/// (adding that donor row) until the table fits. Updates <see cref="_currentMapDemotedCustomTileCodes"/>.
	/// </summary>
	private static List<SoTerrainMaterial.Biome> PlanOverLimitNativeRows(
		List<SoTerrainMaterial.Biome> nativeRows,
		ref CustomBiomeDefinition[] activeVisualDefinitions)
	{
		var limit = GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit;
		var tileCounts = _currentMapTileCounts ?? new Dictionary<int, int>();
		var required = new HashSet<int>(tileCounts.Keys);
		foreach (var alias in Definitions.Where(definition => definition.MaterialAliasOnly))
			required.Add(alias.MaterialDonorTileCode);
		if (_currentMapNativeWaterTerrainTileCodes != null && _currentMapNativeWaterTerrainTileCodes.Count > 0)
			required.Add(NativeWaterTerrainSeabedDonorTileCode);
		var waterShells = _currentMapNativeWaterTerrainTileCodes?.Count ?? 0;

		var customs = activeVisualDefinitions
			.OrderByDescending(definition => tileCounts.TryGetValue(definition.TileCode, out var n) ? n : 0)
			.ThenBy(definition => definition.TileCode)
			.ToList();
		int KeptNativeCount() => nativeRows.Count(biome => required.Contains(biome.tileCode));
		while (customs.Count > 0 && KeptNativeCount() + customs.Count + waterShells > limit)
		{
			var demoted = customs[customs.Count - 1];
			customs.RemoveAt(customs.Count - 1);
			_currentMapDemotedCustomTileCodes.Add(demoted.TileCode);
			if (!nativeRows.Any(biome => biome.tileCode == demoted.MaterialDonorTileCode))
				throw new InvalidOperationException("Custom biome registration cannot demote " + DescribeDefinition(demoted)
					+ " because donor tileCode=" + demoted.MaterialDonorTileCode.ToString(CultureInfo.InvariantCulture)
					+ " is not a native terrain material row.");
			required.Add(demoted.MaterialDonorTileCode);
		}
		activeVisualDefinitions = customs.ToArray();
		return nativeRows.Where(biome => required.Contains(biome.tileCode)).ToList();
	}

	/// <summary>Before RMG builds its biome-name dictionary, put back native rows an over-limit map pruned.</summary>
	private static void RestorePrunedNativeBiomesForRmg(string source)
	{
		if (!_nativeBiomesPruned || _nativeBiomeSnapshot == null)
			return;
		var terrain = SoTerrainMaterial.instance;
		var biomes = terrain?.biomes;
		if (biomes == null)
			return;
		var list = new List<SoTerrainMaterial.Biome>(biomes.Length + _nativeBiomeSnapshot.Count);
		for (var i = 0; i < biomes.Length; i++)
		{
			if (biomes[i] != null)
				list.Add(biomes[i]);
		}
		var restored = 0;
		foreach (var native in _nativeBiomeSnapshot)
		{
			if (list.Any(biome => biome.tileCode == native.tileCode))
				continue;
			list.Add(native);
			restored++;
		}
		_nativeBiomesPruned = false;
		_activeMapMaterialSlotsApplied = false;
		if (restored == 0)
			return;
		var extended = new Il2CppReferenceArray<SoTerrainMaterial.Biome>(list.Count);
		for (var i = 0; i < list.Count; i++)
			extended[i] = list[i];
		terrain.biomes = extended;
		_log?.LogWarning("HoMM3 custom biome registration restored " + restored.ToString(CultureInfo.InvariantCulture)
			+ " pruned native terrain material row(s) via " + (source ?? "?") + ".");
	}
	private static void LogBiomeSlotAudit(SoTerrainMaterial terrain, string source)
	{
		if (terrain?.biomes == null || _biomeSlotAuditRemaining <= 0)
			return;
		_biomeSlotAuditRemaining--;
		try
		{
			var rows = new List<string>();
			foreach (var definition in Definitions)
			{
				var index = FindBiomeIndex(terrain, definition.TileCode);
				var biome = index >= 0 ? terrain.biomes[index] : null;
				rows.Add(
					definition.TileCode
					+ "@"
					+ index
					+ ":"
					+ (biome?.name ?? "?")
					+ " textures="
					+ DescribeTextureForAudit(biome?.texture0)
					+ "/"
					+ DescribeTextureForAudit(biome?.texture1)
					+ "/"
					+ DescribeTextureForAudit(biome?.texture2));
			}
			_log?.LogWarning(
				"HoMM3 custom biome registration audit via "
				+ (source ?? "?")
				+ ": biome slots "
				+ string.Join("; ", rows)
				+ ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 custom biome registration biome audit failed: " + ex.Message);
		}
	}

	private static void LogTerrainMaterialAudit(object renderer, Type rendererType, string source)
	{
		if (_terrainMaterialAuditRemaining <= 0)
			return;
		_terrainMaterialAuditRemaining--;
		try
		{
			var terrain = SoTerrainMaterial.instance;
			var material = terrain?.terrainMaterial;
			var materialTextures = DescribeMaterialTexturesForAudit(material);
			var rendererTextures = DescribeRendererTextureFieldsForAudit(renderer, rendererType);
			var rendererPackedState = DescribeRendererPackedStateFieldsForAudit(renderer, rendererType);
			var dictionaries = DescribeRendererDictionaries(renderer, rendererType);
			_log?.LogWarning(
				"HoMM3 custom biome registration audit via "
				+ (source ?? "?")
				+ ": renderer="
				+ DescribeRendererType(renderer, rendererType)
				+ " terrainMaterial='"
				+ (material ? material.name : "(null)")
				+ "' shader='"
				+ (material && material.shader ? material.shader.name : "?")
				+ "' queue="
				+ (material ? material.renderQueue : -1)
				+ " materialTextures=["
				+ materialTextures
				+ "] rendererTextures=["
				+ rendererTextures
				+ "] packedState=["
				+ rendererPackedState
				+ "] dictionaries=["
				+ dictionaries
				+ "].");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 custom biome registration material audit failed via " + (source ?? "?") + ": " + ex.Message);
		}
	}

	private static string DescribeMaterialTexturesForAudit(Material material)
	{
		if (!material)
			return "(none)";
		try
		{
			var names = material.GetTexturePropertyNames();
			if (names == null || names.Length == 0)
				return "(none)";
			return string.Join(
				";",
				names.Take(24).Select(name => name + "=" + DescribeTextureForAudit(material.GetTexture(name))).ToArray());
		}
		catch (Exception ex)
		{
			return "(failed:" + ex.GetType().Name + ")";
		}
	}

	private static string DescribeRendererPackedStateFieldsForAudit(object renderer, Type rendererType)
	{
		if (renderer == null || rendererType == null)
			return "(none)";
		try
		{
			var parts = new List<string>();
			var seen = new HashSet<string>(StringComparer.Ordinal);
			foreach (var symbol in GameSymbols.TerrainMaterial.RendererPackedStateFields)
			{
				var property = FindProperty(rendererType, symbol);
				FieldInfo field = null;
				if (property == null)
				{
					field = FindField(rendererType, symbol);
					if (field != null && field.IsStatic)
						field = null;
				}
				var name = property?.Name ?? field?.Name;
				if (name == null || !seen.Add(name))
					continue;
				object value = null;
				var valueType = property?.PropertyType ?? field?.FieldType;
				try { value = property != null ? property.GetValue(renderer) : field.GetValue(renderer); }
				catch (Exception ex) { parts.Add(name + "=(failed:" + ex.GetType().Name + ")"); continue; }
				parts.Add(name + "=" + DescribePackedStateValueForAudit(value, valueType));
			}
			return parts.Count == 0 ? "(none)" : string.Join(";", parts);
		}
		catch (Exception ex)
		{
			return "(failed:" + ex.GetType().Name + ")";
		}
	}

	private static string DescribePackedStateValueForAudit(object value, Type declaredType)
	{
		if (value == null)
			return "(null)";
		var type = value.GetType();
		var length = ArrayLikeLength(value);
		var sample = DescribeArrayLikeSampleForAudit(value, GetPackedStateSampleIndices(value, declaredType, length));
		return type.Name + ":len=" + length + (string.IsNullOrEmpty(sample) ? string.Empty : ":sample=" + sample);
	}

	private static int[] GetPackedStateSampleIndices(object value, Type declaredType, int length)
	{
		if (value == null || length <= 0)
			return Array.Empty<int>();
		var name = (declaredType?.FullName ?? declaredType?.Name ?? value.GetType().FullName ?? value.GetType().Name ?? string.Empty);
		if (name.IndexOf("Vector4", StringComparison.OrdinalIgnoreCase) >= 0)
			return new[] { 0, 1, 2, 3, 7, 8, 11, 12, 15 }.Where(index => index < length).Distinct().ToArray();
		if (name.IndexOf("Color", StringComparison.OrdinalIgnoreCase) >= 0
		    || name.IndexOf("ReferenceArray", StringComparison.OrdinalIgnoreCase) >= 0)
			return new[] { 0, 1, 2, 3, 7, 8, 9, 10, 11, 12, 15 }.Where(index => index < length).Distinct().ToArray();
		return Enumerable.Range(0, Math.Min(length, 4)).ToArray();
	}

	private static string DescribeArrayLikeSampleForAudit(object value, int[] indices)
	{
		if (value == null || indices == null || indices.Length == 0)
			return string.Empty;
		try
		{
			var type = value.GetType();
			var getItem = type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance, null, new[] { typeof(int) }, null);
			if (getItem == null)
				return string.Empty;
			var values = new List<string>();
			foreach (var i in indices)
			{
				object item = null;
				try { item = getItem.Invoke(value, new object[] { i }); }
				catch (TargetInvocationException ex) { values.Add(i + "=(failed:" + (ex.InnerException?.GetType().Name ?? ex.GetType().Name) + ")"); continue; }
				catch (Exception ex) { values.Add(i + "=(failed:" + ex.GetType().Name + ")"); continue; }
				values.Add(i + "=" + DescribePackedStateItemForAudit(item));
			}
			return string.Join(",", values);
		}
		catch
		{
			return string.Empty;
		}
	}

	private static string DescribePackedStateItemForAudit(object item)
	{
		if (item == null)
			return "(null)";
		var nestedLength = ArrayLikeLength(item);
		if (nestedLength >= 0)
			return item.GetType().Name + "[len=" + nestedLength + "]";
		return item.ToString();
	}

	private static string DescribeRendererStaticIntsForAudit(Type rendererType)
	{
		if (rendererType == null)
			return "(none)";
		try
		{
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
			var parts = new List<string>();
			foreach (var field in rendererType.GetFields(flags))
			{
				if (field.FieldType != typeof(int))
					continue;
				try
				{
					parts.Add(field.Name + "=" + Convert.ToString(field.GetValue(null), CultureInfo.InvariantCulture));
				}
				catch (Exception ex)
				{
					parts.Add(field.Name + "=(failed:" + ex.GetType().Name + ")");
				}
			}
			foreach (var property in rendererType.GetProperties(flags))
			{
				if (property.PropertyType != typeof(int) || !property.CanRead || property.GetIndexParameters().Length != 0)
					continue;
				try
				{
					parts.Add(property.Name + "=" + Convert.ToString(property.GetValue(null), CultureInfo.InvariantCulture));
				}
				catch (Exception ex)
				{
					parts.Add(property.Name + "=(failed:" + ex.GetType().Name + ")");
				}
			}
			return parts.Count == 0 ? "(none)" : string.Join(";", parts.Distinct().Take(12));
		}
		catch (Exception ex)
		{
			return "(failed:" + ex.GetType().Name + ")";
		}
	}

	private static string DescribeRendererTextureFieldsForAudit(object renderer, Type rendererType)
	{
		if (renderer == null || rendererType == null)
			return "(none)";
		try
		{
			var parts = new List<string>();
			var accessor = FindRendererTextureArrayAccessor(renderer, rendererType);
			if (accessor.IsValid)
			{
				try
				{
					parts.Add(accessor.Name + "[accessor]=" + DescribeTextureForAudit(accessor.Get(renderer) as Texture));
				}
				catch (Exception ex)
				{
					parts.Add(accessor.Name + "[accessor]=(failed:" + ex.GetType().Name + ")");
				}
			}
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var type = rendererType; type != null && type != typeof(object) && parts.Count < 24; type = type.BaseType)
			{
				foreach (var field in type.GetFields(flags))
				{
					if (parts.Count >= 24)
						break;
					if (!typeof(Texture).IsAssignableFrom(field.FieldType) && !typeof(RenderTexture).IsAssignableFrom(field.FieldType))
						continue;
					object value = null;
					try { value = field.GetValue(renderer); }
					catch (Exception ex) { value = ex.GetType().Name; }
					parts.Add(field.Name + "=" + DescribeTextureForAudit(value as Texture));
				}
			}
			return parts.Count == 0 ? "(none)" : string.Join(";", parts);
		}
		catch (Exception ex)
		{
			return "(failed:" + ex.GetType().Name + ")";
		}
	}

	private static string DescribeTextureForAudit(Texture texture)
	{
		if (!texture)
			return "(null)";
		var type = texture.GetType().Name;
		var array = texture as Texture2DArray;
		var texture2D = texture as Texture2D;
		var renderTexture = texture as RenderTexture;
		return (texture.name ?? "?")
		       + ":"
		       + type
		       + ":"
		       + texture.width
		       + "x"
		       + texture.height
		       + (array ? "x" + array.depth : string.Empty)
		       + (array ? ":" + array.format : string.Empty)
		       + (texture2D ? ":" + texture2D.format : string.Empty)
		       + (renderTexture ? ":" + renderTexture.format : string.Empty);
	}

    private static void ValidateRendererRegistration(object renderer)
    {
        if (!CanUseCustomPackedTerrainRebuild("terrain renderer registration validation"))
            return;
        var rendererKey = GetRendererStateKey(renderer);
        if (ValidatedRendererKeys.Contains(rendererKey))
            return;
        if (renderer == null)
            throw new InvalidOperationException("Custom biome registration could not validate terrain renderer lookup because renderer instance was null.");

        var rendererType = renderer.GetType();
        var dictionaries = DescribeRendererDictionaries(renderer, rendererType);
        var requiredDefinitions = ResolveActiveMapVisualDefinitions();
        var missing = requiredDefinitions.Where(definition => !RendererHasTileCode(renderer, rendererType, definition.TileCode)).ToArray();
        if (missing.Length > 0)
        {
            throw new InvalidOperationException(
                "Custom biome registration did not reach native renderer registration for active map custom visual terrain tileCode(s) "
                + DescribeActiveMapCustomVisualTileCodes()
                + ": missing tileCode(s) "
                + string.Join(",", missing.Select(definition => definition.TileCode))
                + ". "
                + "Renderer: " + DescribeRendererType(renderer, rendererType)
                + "; visible fields: " + DescribeVisibleRendererFields(rendererType)
                + "; dictionaries: " + dictionaries);
        }
        ValidatedRendererKeys.Add(rendererKey);
        _log?.LogWarning(
            "HoMM3 custom biome registration validated native renderer registration via "
            + DescribeRendererType(renderer, rendererType)
            + "; active custom visual tileCode(s)="
            + DescribeActiveMapCustomVisualTileCodes()
            + "; required material lookup count="
            + requiredDefinitions.Length.ToString(CultureInfo.InvariantCulture)
            + "; dictionaries: "
            + dictionaries);
    }


	private static void EnsureRendererRegistration(object renderer, string source)
	{
		SeedRendererLookupDictionary(renderer, source, _currentMapCustomVisualTileCodes);
	}

	private static void PostfixRendererPrepareMapRebuild(object __instance, Map __0)
	{
		if (__instance == null)
			return;
		Homm3HomecomingNativeWaterMeshBridge.TryScheduleForMap(__0, __instance, "terrain.prepare-map.postfix");
		Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.enter", __instance, census: true);
		var rendererKey = GetRendererStateKey(__instance);
		if (RebuiltRendererKeys.Contains(rendererKey))
		{
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.already-rebuilt", __instance);
			return;
		}
		if (!HasActiveMapCustomVisualTileCodes())
		{
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.skip-no-active-custom-visual-tiles", __instance);
			return;
		}
		if (!Definitions.Any(definition => !definition.MaterialAliasOnly))
		{
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.no-material-definitions", __instance);
			return;
		}
		if (!TryResolveRendererRebuildMethod(__instance.GetType(), out var rebuildMethod))
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration skipped packed terrain material rebuild on "
				+ __instance.GetType().Name
				+ ": no verified rebuild method hint matched on Golden Era.");
			LogTerrainMaterialAudit(__instance, __instance.GetType(), "post-build-no-verified-rebuild");
			ExtendRendererTextureArrayManaged(__instance, __instance.GetType(), rendererKey, "post-build-managed-packed-array-bind");
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.no-verified-rebuild", __instance, census: true);
			return;
		}
		if (!CanUseCustomPackedTerrainRebuild("terrain prepare-map postfix " + rebuildMethod.Name))
		{
			LogTerrainMaterialAudit(__instance, __instance.GetType(), "post-build-global-vector-preseed-missing");
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.global-vector-preseed-missing", __instance, null, "method=" + rebuildMethod.Name, census: true);
			return;
		}
		Material previousTerrainMaterial = null;
		var capturedPreviousTerrainMaterial = false;
		try
		{
			if (!ShouldPreserveCachedTerrainMaterialForRebuild(__instance.GetType(), rebuildMethod))
				previousTerrainMaterial = InvalidateCachedTerrainMaterialForVerifiedRebuild(rebuildMethod.Name, out capturedPreviousTerrainMaterial);
			if (!PrepareRendererRebuildCandidateState(__instance, __instance.GetType(), rebuildMethod))
			{
				RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
				Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.packed-state-prep-rejected", __instance, null, "method=" + rebuildMethod.Name, census: true);
				return;
			}
			if (!TryResolveRendererTextureNodeUploadMethod(__instance.GetType(), out var textureNodeUploadMethod))
			{
				RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
				_log?.LogWarning(
					"HoMM3 custom biome registration rejected terrain water animation binding on "
					+ __instance.GetType().Name
					+ ": no verified texture-node upload method matched on Golden Era.");
				Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.no-texture-node-upload", __instance, null, "method=" + rebuildMethod.Name, census: true);
				return;
			}
			if (!SeedRendererPackedColorLayersBeforeNativeRebuild(__instance, __instance.GetType(), rebuildMethod, out var seedReason))
			{
				RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
				_log?.LogWarning(
					"HoMM3 custom biome registration rejected terrain rebuild "
					+ __instance.GetType().Name
					+ "."
					+ rebuildMethod.Name
					+ " before native invocation: "
					+ seedReason
					+ ".");
				Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.packed-color-seed-rejected", __instance, null, "method=" + rebuildMethod.Name + " reason=" + seedReason, census: true);
				return;
			}
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.invoke-rebuild.start", __instance, null, "method=" + rebuildMethod.Name, census: true);
			rebuildMethod.Invoke(__instance, Array.Empty<object>());
			if (!RecordRendererRebuildResult(__instance, __instance.GetType(), rendererKey, rebuildMethod, rebuildMethod.Name, "post-prepare-rebuild", __0, textureNodeUploadMethod))
				RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.invoke-rebuild.end", __instance, null, "method=" + rebuildMethod.Name, census: true);
		}
		catch (TargetInvocationException ex)
		{
			RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
			RejectRendererRebuildMethod(__instance.GetType(), rebuildMethod, "post-prepare-rebuild", ex.InnerException ?? ex);
			Homm3MapLoadFlightRecorder.MarkTerrain("terrain.prepare-map.postfix.invoke-rebuild.exception", __instance, null, "method=" + rebuildMethod.Name + " exception=" + (ex.InnerException ?? ex).GetType().FullName, census: true);
		}
	}

	private static bool TryResolveRendererRebuildMethod(Type rendererType, out MethodInfo rebuildMethod)
	{
		rebuildMethod = null;
		if (rendererType == null)
			return false;
		if (TryResolveFlaggedRendererRebuildCandidate(rendererType, out rebuildMethod))
			return true;
		var symbol = GameSymbols.TerrainMaterial.RendererRebuildMaterialArrays;
		foreach (var hint in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var method = rendererType.GetMethod(
				hint,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (method == null || method.ReturnType != typeof(void) || method.GetParameters().Length != 0)
				continue;
			if (IsRejectedRendererRebuildMethod(rendererType, method))
				continue;
			if (IsKnownBadGeneratedRendererRebuildMethod(rendererType, method))
			{
				RejectRendererRebuildMethod(rendererType, method, "resolve", "known bad Golden Era terrain rebuild candidate");
				continue;
			}
			rebuildMethod = method;
			return true;
		}
		if (IsGeneratedDeobfRendererType(rendererType))
			return false;

		rebuildMethod = GameMember.FindFirstMethod(rendererType, typeof(void), Type.EmptyTypes, symbol);
		return rebuildMethod != null
		       && !IsRejectedRendererRebuildMethod(rendererType, rebuildMethod)
		       && !string.Equals(rebuildMethod.Name, "Method_Private_Void_0", StringComparison.Ordinal);
	}

	private static bool TryResolveRendererTextureNodeUploadMethod(Type rendererType, out MethodInfo textureNodeUploadMethod)
	{
		textureNodeUploadMethod = null;
		if (rendererType == null)
			return false;
		textureNodeUploadMethod = GameMember.FindFirstMethod(
			rendererType,
			typeof(void),
			new[] { typeof(Map) },
			GameSymbols.TerrainMaterial.RendererUploadTextureNodes);
		return textureNodeUploadMethod != null;
	}

	private static bool TryResolveFlaggedRendererRebuildCandidate(Type rendererType, out MethodInfo rebuildMethod)
	{
		rebuildMethod = null;
		if (rendererType == null)
			return false;
		foreach (var hint in GameSymbols.TerrainMaterial.RendererPackedBuildNaturalCallProbe.NameHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var flagName = TerrainRebuildCandidateFlagPrefix + hint + TerrainRebuildCandidateFlagSuffix;
			if (!Homm3DiagnosticFlags.IsEnabled(flagName))
				continue;
			var method = rendererType.GetMethod(
				hint,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (method == null || method.ReturnType != typeof(void) || method.GetParameters().Length != 0)
			{
				_log?.LogWarning(
					"HoMM3 custom biome registration ignored terrain rebuild candidate flag "
					+ flagName
					+ ": no zero-arg void method named "
					+ hint
					+ " on "
					+ rendererType.Name
					+ ".");
				continue;
			}
			if (IsKnownBadGeneratedRendererRebuildMethod(rendererType, method) || IsRejectedRendererRebuildMethod(rendererType, method))
			{
				_log?.LogWarning(
					"HoMM3 custom biome registration ignored terrain rebuild candidate flag "
					+ flagName
					+ ": "
					+ rendererType.Name
					+ "."
					+ method.Name
					+ " is already rejected.");
				continue;
			}
			_log?.LogWarning(
				"HoMM3 custom biome registration will invoke flagged terrain rebuild candidate "
				+ rendererType.Name
				+ "."
				+ method.Name
				+ "; remove "
				+ flagName
				+ " after this probe.");
			FlaggedRendererRebuildMethods.Add(GetRendererRebuildMethodKey(rendererType, method.Name));
			rebuildMethod = method;
			return true;
		}
		return false;
	}

	private static bool IsFlaggedRendererRebuildMethod(Type rendererType, MethodInfo method)
	{
		return method != null && FlaggedRendererRebuildMethods.Contains(GetRendererRebuildMethodKey(rendererType, method.Name));
	}

	private static bool PrepareRendererRebuildCandidateState(object renderer, Type rendererType, MethodInfo method)
	{
		if (renderer == null || rendererType == null || method == null)
			return false;
		if (!IsPackedBuildStatePrepMethod(method))
			return true;
		if (!CanUseCustomPackedTerrainRebuild("terrain rebuild " + method.Name))
			return false;

		var changes = ExpandRendererPackedStateArrays(
			renderer,
			rendererType,
			GameSymbols.TerrainMaterial.CustomBiomePackedSlotCapacity);
		_log?.LogWarning(
			"HoMM3 custom biome registration prepared terrain rebuild "
			+ rendererType.Name
			+ "."
			+ method.Name
			+ " packed-state arrays for "
			+ GameSymbols.TerrainMaterial.CustomBiomePackedSlotCapacity.ToString(CultureInfo.InvariantCulture)
			+ "-slot native path: "
			+ (changes.Count == 0 ? "no changes" : string.Join(", ", changes))
			+ ".");
		if (!TryValidateRendererPackedStateCapacity(renderer, rendererType, out var reason))
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration rejected terrain rebuild "
				+ rendererType.Name
				+ "."
				+ method.Name
				+ " before native invocation: "
				+ reason
				+ ".");
			return false;
		}
		return true;
	}

	private static List<string> ExpandRendererPackedStateArrays(object renderer, Type rendererType, int targetLength)
	{
		var changes = new List<string>();
		if (renderer == null || rendererType == null || targetLength <= 0)
			return changes;
		var seenAccessors = new HashSet<string>(StringComparer.Ordinal);
		foreach (var symbol in GameSymbols.TerrainMaterial.RendererPackedStateFields)
		{
			if (!IsSlotIndexedPackedStateField(symbol))
				continue;
			var field = FindField(rendererType, symbol);
			if (field != null && field.IsStatic)
				field = null;
			PropertyInfo property = null;
			if (field == null)
				property = FindProperty(rendererType, symbol);
			if (property != null && (property.GetMethod == null || property.GetMethod.IsStatic || !property.CanWrite))
				property = null;
			var accessorName = field?.Name ?? property?.Name;
			if (string.IsNullOrEmpty(accessorName) || !seenAccessors.Add(accessorName))
				continue;
			try
			{
				var value = field != null ? field.GetValue(renderer) : property.GetValue(renderer);
				if (TryExpandPackedStateArray(value, targetLength, out var replacement, out var description))
				{
					if (field != null)
						field.SetValue(renderer, replacement);
					else
						property.SetValue(renderer, replacement);
					changes.Add(accessorName + ":" + description);
				}
			}
			catch (Exception ex)
			{
				changes.Add(accessorName + ":failed:" + ex.GetType().Name);
			}
		}
		return changes;
	}

	private static bool IsSlotIndexedPackedStateField(GameSymbols.FieldSymbol symbol)
	{
		var id = symbol.Id;
		if (string.IsNullOrEmpty(id))
			return false;
		return id.IndexOf(".colors.", StringComparison.Ordinal) >= 0
		       || id.IndexOf(".nodes.", StringComparison.Ordinal) >= 0
		       || id.IndexOf(".splat0.", StringComparison.Ordinal) >= 0
		       || id.IndexOf(".splat1.", StringComparison.Ordinal) >= 0;
	}

	private static bool TryValidateRendererPackedStateCapacity(object renderer, Type rendererType, out string reason)
	{
		reason = null;
		var requiredSlot = GetHighestCustomMaterialSlot(renderer, rendererType);
		if (requiredSlot < 0)
		{
			reason = "no custom material slot was registered";
			return false;
		}
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "colors", requiredSlot, out reason))
			return false;
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "nodes", requiredSlot, out reason))
			return false;
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "splat0", requiredSlot, out reason))
			return false;
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "splat1", requiredSlot, out reason))
			return false;
		return true;
	}

	private static bool ShouldPreserveCachedTerrainMaterialForRebuild(Type rendererType, MethodInfo method)
	{
		return IsGeneratedDeobfRendererType(rendererType)
		       && method != null
		       && IsPackedBuildStatePrepMethod(method);
	}

	private static bool IsPackedBuildStatePrepMethod(MethodInfo method)
	{
		if (method == null)
			return false;
		foreach (var name in GameSymbols.TerrainMaterial.RendererPackedBuildStatePrepMethodNames)
			if (string.Equals(method.Name, name, StringComparison.Ordinal))
				return true;
		return false;
	}

	private static bool TryExpandPackedStateArray(object value, int targetLength, out object replacement, out string description)
	{
		replacement = null;
		description = null;
		if (value == null || targetLength <= 0)
			return false;

		if (value is Il2CppStructArray<Vector4> vectors)
		{
			if (vectors.Length >= targetLength)
				return false;
			var expanded = new Il2CppStructArray<Vector4>(targetLength);
			for (var i = 0; i < vectors.Length; i++)
				expanded[i] = vectors[i];
			replacement = expanded;
			description = vectors.Length.ToString(CultureInfo.InvariantCulture) + "->" + targetLength.ToString(CultureInfo.InvariantCulture);
			return true;
		}

		if (value is Il2CppStructArray<int> ints)
		{
			if (ints.Length >= targetLength)
				return false;
			var expanded = new Il2CppStructArray<int>(targetLength);
			for (var i = 0; i < ints.Length; i++)
				expanded[i] = ints[i];
			replacement = expanded;
			description = ints.Length.ToString(CultureInfo.InvariantCulture) + "->" + targetLength.ToString(CultureInfo.InvariantCulture);
			return true;
		}

		if (value is Il2CppReferenceArray<Il2CppStructArray<Color>> colors)
		{
			if (colors.Length >= targetLength)
				return false;
			var expanded = new Il2CppReferenceArray<Il2CppStructArray<Color>>(targetLength);
			for (var i = 0; i < colors.Length; i++)
				expanded[i] = colors[i];
			replacement = expanded;
			description = colors.Length.ToString(CultureInfo.InvariantCulture) + "->" + targetLength.ToString(CultureInfo.InvariantCulture);
			return true;
		}

		if (value is Il2CppReferenceArray<Il2CppStructArray<int>> indices)
		{
			if (indices.Length >= targetLength)
				return false;
			var expanded = new Il2CppReferenceArray<Il2CppStructArray<int>>(targetLength);
			for (var i = 0; i < indices.Length; i++)
				expanded[i] = indices[i];
			replacement = expanded;
			description = indices.Length.ToString(CultureInfo.InvariantCulture) + "->" + targetLength.ToString(CultureInfo.InvariantCulture);
			return true;
		}

		return false;
	}

	private static bool IsKnownBadGeneratedRendererRebuildMethod(Type rendererType, MethodInfo method)
	{
		if (!IsGeneratedDeobfRendererType(rendererType) || method == null)
			return false;
		return GameSymbols.TerrainMaterial.RejectedRendererRebuildMethodNames
			.Any(name => string.Equals(method.Name, name, StringComparison.Ordinal));
	}

	private static bool IsRejectedRendererRebuildMethod(Type rendererType, MethodInfo method)
	{
		return method != null && RejectedRendererRebuildMethods.Contains(GetRendererRebuildMethodKey(rendererType, method.Name));
	}

	private static void RejectRendererRebuildMethod(Type rendererType, MethodInfo method, string source, Exception ex)
	{
		RejectRendererRebuildMethod(rendererType, method, source, ex?.GetType().Name + ": " + ex?.Message);
	}

	private static void RejectRendererRebuildMethod(Type rendererType, MethodInfo method, string source, string reason)
	{
		if (method == null)
			return;
		var key = GetRendererRebuildMethodKey(rendererType, method.Name);
		var first = RejectedRendererRebuildMethods.Add(key);
		if (first || _rebuildRejectionLogsRemaining > 0)
		{
			if (!first)
				_rebuildRejectionLogsRemaining--;
			_log?.LogWarning(
				"HoMM3 custom biome registration rejected packed terrain material rebuild candidate "
				+ (rendererType?.Name ?? "?")
				+ "."
				+ method.Name
				+ " from "
				+ (source ?? "?")
				+ ": "
				+ (reason ?? "unknown")
				+ ".");
		}
	}

	private static string GetRendererRebuildMethodKey(Type rendererType, string methodName)
	{
		return (rendererType?.FullName ?? rendererType?.Name ?? "?") + "::" + (methodName ?? "?");
	}

	private static void SeedRendererLookupDictionary(object renderer, string source, HashSet<int> activeCustomVisualTileCodes = null)
	{
		if (renderer == null)
			throw new InvalidOperationException("Custom biome registration could not register renderer lookup because renderer instance was null.");
		if (!EnsureTerrainGlobalVectorArrayCapacity(source + " renderer lookup"))
		{
			throw new InvalidOperationException(
				"HoMM3 custom biome registration cannot replace terrain renderer lookup via "
				+ (source ?? "?")
				+ " before terrain packed global vector arrays were preseeded to "
				+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
				+ " (shader-declared Terrain_BiomParams size): "
				+ (_terrainGlobalVectorArrayPreseedFailure ?? "unknown failure")
				+ ".");
		}
		var rendererKey = GetRendererStateKey(renderer);
		if (SeededRendererKeys.Contains(rendererKey))
			return;
		var rendererType = renderer.GetType();
		var terrain = SoTerrainMaterial.instance;
		var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		if (materialLookup.Value == null)
			throw new InvalidOperationException(
				"Custom biome registration could not find the terrain material lookup dictionary on "
				+ DescribeRendererType(renderer, rendererType)
				+ " before terrain material apply; dictionaries: "
				+ DescribeRendererDictionaries(renderer, rendererType));
		Apply(terrain, source + " terrain material", force: true);

		materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		if (materialLookup.Value == null)
			throw new InvalidOperationException(
				"Custom biome registration could not find the terrain material lookup dictionary on "
				+ DescribeRendererType(renderer, rendererType)
				+ "; dictionaries: "
				+ DescribeRendererDictionaries(renderer, rendererType));

		var biomes = terrain?.biomes;
		if (biomes == null || biomes.Length == 0)
			throw new InvalidOperationException("Custom biome registration cannot replace a renderer lookup without a current material table.");
		var expected = new Dictionary<int, int>();
		for (var slot = 0; slot < biomes.Length; slot++)
		{
			var biome = biomes[slot];
			if (biome == null)
				throw new InvalidOperationException("Custom biome registration found a null terrain material at slot " + slot + ".");
			if (expected.ContainsKey(biome.tileCode))
				throw new InvalidOperationException("Custom biome registration found duplicate terrain material tileCode=" + biome.tileCode + ".");
			expected.Add(biome.tileCode, slot);
		}

		var definitionsForLookup = Definitions
			.Where(definition => definition.MaterialAliasOnly
				|| (activeCustomVisualTileCodes != null && activeCustomVisualTileCodes.Contains(definition.TileCode)))
			.ToArray();
		foreach (var definition in definitionsForLookup)
		{
			// Over-limit maps (GH#29): a demoted custom terrain draws with its donor's material slot.
			var demoted = !definition.MaterialAliasOnly && _currentMapDemotedCustomTileCodes.Contains(definition.TileCode);
			var donorSlot = definition.MaterialAliasOnly || demoted;
			var targetTileCode = donorSlot
				? definition.MaterialDonorTileCode
				: definition.TileCode;
			var biomeIndex = donorSlot
				? ResolveAliasDonorMaterialSlot(expected, definition)
				: FindBiomeIndex(terrain, targetTileCode);
			if (demoted)
			{
				expected[definition.TileCode] = biomeIndex;
				continue;
			}
			if (biomeIndex < 0)
				throw new InvalidOperationException(
					"Custom biome registration could not find material slot for "
					+ DescribeDefinition(definition)
					+ " using custom biome registration tileCode="
					+ targetTileCode
					+ ". Active custom visual tileCode(s): "
					+ DescribeActiveMapCustomVisualTileCodes()
					+ ".");
			if (!definition.MaterialAliasOnly && biomeIndex >= GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit)
				throw new InvalidOperationException(
					"Custom biome registration mapped active custom visual tileCode="
					+ definition.TileCode.ToString(CultureInfo.InvariantCulture)
					+ " to material slot "
					+ biomeIndex.ToString(CultureInfo.InvariantCulture)
					+ ", exceeding native packed material slot limit "
					+ GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit.ToString(CultureInfo.InvariantCulture)
					+ ".");
			if (definition.MaterialAliasOnly)
			{
				// A declared alias intentionally redirects its own catalog row to the current donor slot.
				expected[definition.TileCode] = biomeIndex;
			}
			else if (expected.TryGetValue(definition.TileCode, out var existing))
			{
				if (existing != biomeIndex)
					throw new InvalidOperationException("Custom biome registration found conflicting current material slots for tileCode=" + definition.TileCode + ".");
			}
			else
			{
				expected.Add(definition.TileCode, biomeIndex);
			}
		}
		EnsureNativeWaterTerrainLookupEntries(expected, terrain, source);
		// Fortress -> Tower previously left Molten/Burrow at slot 8 after the table shrank to 8 slots.
		// Build from the current catalog, not the old native dictionary; see docs/homm3_terrain_map_transition.md.
		Homm3TerrainMaterialLookup.Replace(expected, biomes.Length, materialLookup.Value.Clear, materialLookup.Value.Add);
		SeededRendererKeys.Add(rendererKey);
		_log?.LogWarning(
			"HoMM3 custom biome registration replaced terrain renderer lookup via "
			+ source
			+ " renderer="
			+ DescribeRendererType(renderer, rendererType)
			+ ": "
			+ materialLookup.Name
			+ "["
			+ materialLookup.Source
			+ "; dictionaries: "
			+ DescribeRendererDictionaries(renderer, rendererType));
	}

	private static int FindBiomeIndex(SoTerrainMaterial terrain, int tileCode)
	{
		var biomes = terrain?.biomes;
		if (biomes == null)
			return -1;
		for (var i = 0; i < biomes.Length; i++)
		{
			var biome = biomes[i];
			if (biome != null && biome.tileCode == tileCode)
				return i;
		}
		return -1;
	}

	private static void AppendNativeWaterTerrainBiomesFromCatalog(List<SoTerrainMaterial.Biome> activeBiomes, string source)
	{
		if (activeBiomes == null)
			throw new InvalidOperationException("Custom biome registration could not append native water terrain biomes because activeBiomes was null.");
		if (!_currentMapVisualSlotScopeKnown || _currentMapNativeWaterTerrainTileCodes == null || _currentMapNativeWaterTerrainTileCodes.Count == 0)
			return;
		EnsureNativeWaterDonorBiomeCaptured(source);
		if (_nativeWaterDonorBiome == null)
			return;
		foreach (var tileCode in _currentMapNativeWaterTerrainTileCodes.OrderBy(value => value))
		{
			if (activeBiomes.Any(biome => biome != null && biome.tileCode == tileCode))
				continue;
			activeBiomes.Add(CloneNativeWaterBiomeShell(_nativeWaterDonorBiome, tileCode));
		}
	}

	/// <summary>
	/// RMG <c>bjl..ctor</c> builds a name→biome dictionary and throws on duplicate keys
	/// (observed: Key: Water). Keep the first occurrence; rename later collisions by tileCode.
	/// Must run before the first <c>bjg.may()</c> / <c>blc.GenerateMap</c> in the process.
	/// </summary>
	private static void EnsureUniqueBiomeNamesForRmg(List<SoTerrainMaterial.Biome> activeBiomes, string source)
	{
		if (activeBiomes == null || activeBiomes.Count == 0)
			return;
		var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		var renamed = 0;
		for (var i = 0; i < activeBiomes.Count; i++)
		{
			var biome = activeBiomes[i];
			if (biome == null)
				continue;
			var name = biome.name;
			if (string.IsNullOrWhiteSpace(name))
			{
				name = "Biome_" + biome.tileCode.ToString(CultureInfo.InvariantCulture);
				biome.name = name;
				renamed++;
			}
			if (seen.Add(name))
				continue;
			var unique = name + "_" + biome.tileCode.ToString(CultureInfo.InvariantCulture);
			var suffix = 1;
			while (!seen.Add(unique))
			{
				unique = name + "_" + biome.tileCode.ToString(CultureInfo.InvariantCulture) + "_"
					+ suffix.ToString(CultureInfo.InvariantCulture);
				suffix++;
			}
			biome.name = unique;
			renamed++;
		}
		if (renamed > 0)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration renamed "
				+ renamed.ToString(CultureInfo.InvariantCulture)
				+ " duplicate/empty biome name(s) for RMG compatibility via "
				+ (source ?? "?")
				+ ".");
		}
	}

	/// <summary>
	/// In-place sanitize of the live SoTerrainMaterial catalog before RMG GenerateMap.
	/// Safe to call repeatedly; only renames collisions.
	/// </summary>
	internal static int SanitizeLiveTerrainBiomeNamesForRmg(string source)
	{
		var terrain = SoTerrainMaterial.instance;
		if (terrain == null)
		{
			try { terrain = Resources.Load<SoTerrainMaterial>("configs/TerrainMaterials"); }
			catch { terrain = null; }
		}
		if (terrain?.biomes == null || terrain.biomes.Length == 0)
			return 0;

		var list = new List<SoTerrainMaterial.Biome>(terrain.biomes.Length);
		for (var i = 0; i < terrain.biomes.Length; i++)
		{
			if (terrain.biomes[i] != null)
				list.Add(terrain.biomes[i]);
		}
		var before = list.Select(b => b.name).ToArray();
		EnsureUniqueBiomeNamesForRmg(list, source ?? "pre-rmg-sanitize");
		var renamed = 0;
		for (var i = 0; i < list.Count; i++)
		{
			if (!string.Equals(before[i], list[i].name, StringComparison.Ordinal))
				renamed++;
		}
		if (renamed > 0)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration pre-RMG sanitized "
				+ renamed.ToString(CultureInfo.InvariantCulture)
				+ " SoTerrainMaterial biome name(s) via "
				+ (source ?? "?")
				+ ".");
		}
		return renamed;
	}

	private static void RegisterGenerateMapBiomeNameSanitize(Harmony harmony, ManualLogSource log)
	{
		if (_rmgGenerateMapSanitizeRegistered || harmony == null)
			return;
		var generateMap = FindGenerateMapMethod();
		if (generateMap == null)
		{
			log?.LogWarning("HoMM3 custom biome registration could not resolve blc.GenerateMap; pre-RMG biome sanitize will not run.");
			return;
		}
		harmony.Patch(
			generateMap,
			prefix: new HarmonyMethod(typeof(Homm3SwampAutumnTintProof), nameof(PrefixGenerateMapSanitizeBiomes)));
		_rmgGenerateMapSanitizeRegistered = true;
		log?.LogWarning(
			"HoMM3 custom biome registration patched "
			+ generateMap.DeclaringType?.Name
			+ "."
			+ generateMap.Name
			+ " for pre-RMG SoTerrainMaterial biome-name sanitize.");
	}

	private static void PrefixGenerateMapSanitizeBiomes()
	{
		try
		{
			RestorePrunedNativeBiomesForRmg("blc.GenerateMap.prefix");
			SanitizeLiveTerrainBiomeNamesForRmg("blc.GenerateMap.prefix");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 custom biome registration pre-RMG biome sanitize failed closed: " + ex.Message);
		}
	}

	private static MethodInfo FindGenerateMapMethod()
	{
		foreach (var hint in GameSymbols.RmgMapCapture.GeneratorTypeHints)
		{
			var type = GameMember.FindType(
				GameSymbols.RmgMapCapture.GeneratorTypeId + "." + hint,
				hint,
				() => AccessTools.TypeByName(hint) ?? AccessTools.TypeByName("Hex." + hint));
			if (type == null)
				continue;
			foreach (var name in GameSymbols.RmgMapCapture.GenerateMap.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				MethodInfo[] methods;
				try { methods = type.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic); }
				catch { continue; }
				foreach (var method in methods)
				{
					if (!string.Equals(method.Name, name, StringComparison.Ordinal)
					    && method.Name.IndexOf("GenerateMap", StringComparison.OrdinalIgnoreCase) < 0)
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length < 2)
						continue;
					if (parameters[0].ParameterType != typeof(string))
						continue;
					if (parameters[1].ParameterType != typeof(int))
						continue;
					return method;
				}
			}
		}
		var blcType = AccessTools.TypeByName("blc");
		if (blcType == null)
			return null;
		return AccessTools.Method(blcType, "GenerateMap");
	}

	private static void EnsureNativeWaterDonorBiomeCaptured(string source)
	{
		if (_nativeWaterDonorBiome != null || _nativeWaterDonorBiomeCaptureAttempted)
			return;
		_nativeWaterDonorBiomeCaptureAttempted = true;

		var terrainResource = Resources.Load<SoTerrainMaterial>("configs/TerrainMaterials");
		if (TryCaptureSandSeabedDonorBiomeFromTerrain(terrainResource, source + "/Resources.Load"))
			return;

		if (TryCaptureSandSeabedDonorBiomeFromTerrain(SoTerrainMaterial.instance, source + "/instance"))
			return;

		foreach (var terrain in Resources.FindObjectsOfTypeAll<SoTerrainMaterial>())
		{
			if (TryCaptureSandSeabedDonorBiomeFromTerrain(terrain, source + "/FindObjectsOfTypeAll"))
				return;
		}

		_log?.LogWarning(
			"HoMM3 custom biome registration could not capture native Sand seabed donor biome from SoTerrainMaterial catalog via "
			+ (source ?? "?")
			+ "; native water terrain lookup will fall back to Sand seabed slot "
			+ NativeWaterTerrainSeabedDonorTileCode.ToString(CultureInfo.InvariantCulture)
			+ ".");
	}

	private static bool TryCaptureSandSeabedDonorBiomeFromTerrain(SoTerrainMaterial terrain, string source)
	{
		var biomes = terrain?.biomes;
		if (biomes == null)
			return false;
		for (var i = 0; i < biomes.Length; i++)
		{
			var biome = biomes[i];
			if (biome == null)
				continue;
			var matchesTileCode = biome.tileCode == NativeWaterTerrainSeabedDonorTileCode;
			var matchesSandName = string.Equals(biome.name, "Sand", StringComparison.OrdinalIgnoreCase);
			if (!matchesTileCode && !matchesSandName)
				continue;
			if (!biome.texture0 && !biome.texture1 && !biome.texture2)
				continue;
			_nativeWaterDonorBiome = biome;
			_log?.LogWarning(
				"HoMM3 custom biome registration captured native Sand seabed donor biome via "
				+ (source ?? "?")
				+ " tileCode="
				+ biome.tileCode.ToString(CultureInfo.InvariantCulture)
				+ " name="
				+ (biome.name ?? "?")
				+ " for water terrain tile ids under the native waterMap mesh.");
			return true;
		}
		return false;
	}

	private static SoTerrainMaterial.Biome CloneNativeWaterBiomeShell(SoTerrainMaterial.Biome donor, int tileCode)
	{
		// RMG indexes biomes/tile configs by name (bjl..ctor). Reusing donor.name "Water"
		// for every shore/deep tile clone throws ArgumentException: duplicate key Water and aborts GenerateMap.
		if (!NativeWaterTerrainBiomeNameByTileCode.TryGetValue(tileCode, out var uniqueName)
		    || string.IsNullOrWhiteSpace(uniqueName))
		{
			uniqueName = "Water_" + tileCode.ToString(CultureInfo.InvariantCulture);
		}
		return new SoTerrainMaterial.Biome
		{
			name = uniqueName,
			tileCode = tileCode,
			splatmap = donor.splatmap,
			splatmapTiling = donor.splatmapTiling,
			blendDepth = donor.blendDepth,
			texturesCount = donor.texturesCount,
			mode = donor.mode,
			tiling0 = donor.tiling0,
			heightmapScale0 = donor.heightmapScale0,
			tiling1 = donor.tiling1,
			heightmapScale1 = donor.heightmapScale1,
			tiling2 = donor.tiling2,
			heightmapScale2 = donor.heightmapScale2,
			texture0 = donor.texture0,
			texture1 = donor.texture1,
			texture2 = donor.texture2,
			texture3 = donor.texture3,
			tiling3 = donor.tiling3,
			heightmapScale3 = donor.heightmapScale3
		};
	}

	private static void EnsureNativeWaterTerrainLookupEntries(Dictionary<int, int> materialLookup, SoTerrainMaterial terrain, string source)
	{
		if (materialLookup == null || terrain == null)
			return;
		if (!_currentMapVisualSlotScopeKnown || _currentMapNativeWaterTerrainTileCodes == null || _currentMapNativeWaterTerrainTileCodes.Count == 0)
			return;
		var seabedFallbackSlot = FindBiomeIndex(terrain, NativeWaterTerrainSeabedDonorTileCode);
		foreach (var tileCode in _currentMapNativeWaterTerrainTileCodes.OrderBy(value => value))
		{
			var waterSlot = FindBiomeIndex(terrain, tileCode);
			if (waterSlot < 0)
			{
				if (seabedFallbackSlot < 0)
				{
					throw new InvalidOperationException(
						"Custom biome registration could not resolve native water or Sand seabed material slot for tileCode="
						+ tileCode.ToString(CultureInfo.InvariantCulture)
						+ " via "
						+ (source ?? "?")
						+ ".");
				}
				waterSlot = seabedFallbackSlot;
			}
			if (materialLookup.TryGetValue(tileCode, out var existing))
			{
				if (existing != waterSlot)
				{
					throw new InvalidOperationException(
						"Custom biome registration found native water terrain tileCode="
						+ tileCode.ToString(CultureInfo.InvariantCulture)
						+ " mapped to material slot "
						+ existing.ToString(CultureInfo.InvariantCulture)
						+ " instead of the required native water slot "
						+ waterSlot.ToString(CultureInfo.InvariantCulture)
						+ " via "
						+ (source ?? "?")
						+ ".");
				}
				continue;
			}
			materialLookup.Add(tileCode, waterSlot);
		}
	}

	private static int ResolveAliasDonorMaterialSlot(
		IReadOnlyDictionary<int, int> materialLookup,
		CustomBiomeDefinition definition)
	{
		if (!materialLookup.TryGetValue(definition.MaterialDonorTileCode, out var slot))
		{
			throw new InvalidOperationException(
				"Custom biome registration could not resolve alias material slot for "
				+ DescribeDefinition(definition)
				+ " because donor tileCode="
				+ definition.MaterialDonorTileCode.ToString(CultureInfo.InvariantCulture)
				+ " was missing from the current material table; alias donors must be native biomes present in the TerrainMaterials asset.");
		}
		return slot;
	}

	private static RendererLookupDictionary FindMaterialLookupDictionary(object renderer, Type rendererType)
	{
		var materialNames = new HashSet<string>(
			GameSymbols.TerrainMaterial.RendererMaterialLookups
				.Where(symbol => symbol.Id.IndexOf("materialLookup", StringComparison.OrdinalIgnoreCase) >= 0)
				.SelectMany(symbol => new[] { symbol.FieldName, symbol.NativeFieldInfoName?.Replace("NativeFieldInfoPtr_", string.Empty) })
				.Where(name => !string.IsNullOrWhiteSpace(name)),
			StringComparer.Ordinal);
		foreach (var dictionary in FindRendererLookupDictionaries(renderer, rendererType))
		{
			if (materialNames.Contains(dictionary.Name))
				return dictionary;
		}

		return default;
	}

	private static void RebuildRendererMaterialState(object renderer, Type rendererType)
	{
		if (renderer == null)
			return;
		var rendererKey = GetRendererStateKey(renderer);
		if (RebuiltRendererKeys.Contains(rendererKey))
			return;
		if (!TryResolveRendererRebuildMethod(rendererType, out var rebuildMethod))
			return;
		if (!CanUseCustomPackedTerrainRebuild("terrain rebuild " + rebuildMethod.Name))
			return;
		Material previousTerrainMaterial = null;
		var capturedPreviousTerrainMaterial = false;
		try
		{
			if (!ShouldPreserveCachedTerrainMaterialForRebuild(rendererType, rebuildMethod))
				previousTerrainMaterial = InvalidateCachedTerrainMaterialForVerifiedRebuild(rebuildMethod.Name, out capturedPreviousTerrainMaterial);
			if (!PrepareRendererRebuildCandidateState(renderer, rendererType, rebuildMethod))
				return;
			if (!SeedRendererPackedColorLayersBeforeNativeRebuild(renderer, rendererType, rebuildMethod, out var seedReason))
			{
				RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
				_log?.LogWarning(
					"HoMM3 custom biome registration rejected terrain rebuild "
					+ rendererType.Name
					+ "."
					+ rebuildMethod.Name
					+ " before native invocation: "
					+ seedReason
					+ ".");
				return;
			}
			rebuildMethod.Invoke(renderer, Array.Empty<object>());
			if (!RecordRendererRebuildResult(renderer, rendererType, rendererKey, rebuildMethod, rebuildMethod.Name, "rebuild"))
				RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
		}
		catch (TargetInvocationException ex)
		{
			RestoreCachedTerrainMaterialAfterRejectedRebuild(previousTerrainMaterial, capturedPreviousTerrainMaterial, rebuildMethod.Name);
			RejectRendererRebuildMethod(rendererType, rebuildMethod, "rebuild", ex.InnerException ?? ex);
		}
	}

	private static Material InvalidateCachedTerrainMaterialForVerifiedRebuild(string methodName, out bool capturedPreviousMaterial)
	{
		capturedPreviousMaterial = false;
		try
		{
			var terrain = SoTerrainMaterial.instance;
			if (terrain == null)
				return null;
			var previous = terrain.terrainMaterial;
			capturedPreviousMaterial = true;
			terrain.terrainMaterial = null;
			return previous;
		}
		catch (Exception ex)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration could not invalidate cached terrain material before "
				+ (methodName ?? "rebuild")
				+ ": "
				+ ex.Message);
			return null;
		}
	}

	private static void RestoreCachedTerrainMaterialAfterRejectedRebuild(Material previousMaterial, bool capturedPreviousMaterial, string methodName)
	{
		if (!capturedPreviousMaterial || previousMaterial == null)
			return;
		try
		{
			var terrain = SoTerrainMaterial.instance;
			if (terrain == null)
				return;
			if (ReferenceEquals(terrain.terrainMaterial, previousMaterial))
				return;
			terrain.terrainMaterial = previousMaterial;
			_log?.LogWarning(
				"HoMM3 custom biome registration restored previous cached terrain material after rejected rebuild "
				+ (methodName ?? "?")
				+ ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration could not restore cached terrain material after rejected rebuild "
				+ (methodName ?? "?")
				+ ": "
				+ ex.Message);
		}
	}

	private static bool IsGeneratedDeobfRendererType(Type rendererType)
	{
		var name = rendererType?.Name;
		return !string.IsNullOrEmpty(name)
		       && (name.StartsWith("ObjectPublic", StringComparison.Ordinal)
		           || name.StartsWith("MonoBehaviourPublic", StringComparison.Ordinal));
	}

	private static bool RecordRendererRebuildResult(object renderer, Type rendererType, long rendererKey, MethodInfo rebuildMethod, string methodName, string source, Map map = null, MethodInfo textureNodeUploadMethod = null)
	{
		LogTerrainMaterialAudit(renderer, rendererType, source);
		var waterAnimationRequired = RequiresTerrainWaterAnimationBinding(source);
		if (!TryValidateRendererPackedMaterialState(renderer, rendererType, out var reason))
		{
			if (!string.IsNullOrEmpty(reason)
			    && reason.IndexOf("Texture2DArray depth", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				ExtendRendererTextureArrayManaged(renderer, rendererType, rendererKey, source + "-managed-texture-array-after-native-metadata");
				if (TryValidateRendererPackedMaterialState(renderer, rendererType, out reason))
				{
					if (!HasRequiredWaterAnimationBindingContext(waterAnimationRequired, map, textureNodeUploadMethod, source))
						return false;
					RebuiltRendererKeys.Add(rendererKey);
					if (waterAnimationRequired && map != null && textureNodeUploadMethod != null)
						RegisterTerrainWaterAnimationBinding(renderer, rendererType, map, textureNodeUploadMethod, source + "-managed-texture-array-after-native-metadata");
					_log?.LogWarning(
						"HoMM3 custom biome registration rebuilt packed terrain metadata via "
						+ DescribeRendererType(renderer, rendererType)
						+ "."
						+ (methodName ?? "?")
						+ " and completed texture depth with managed Texture2DArray extension.");
					return true;
				}
			}
			if (_rebuildRejectionLogsRemaining > 0)
			{
				_rebuildRejectionLogsRemaining--;
				_log?.LogWarning(
					"HoMM3 custom biome registration invoked packed terrain material rebuild via "
					+ DescribeRendererType(renderer, rendererType)
					+ "."
					+ (methodName ?? "?")
					+ " but did not mark it complete: "
					+ reason
					+ ".");
			}
			return false;
		}

		if (!HasRequiredWaterAnimationBindingContext(waterAnimationRequired, map, textureNodeUploadMethod, source))
			return false;
		RebuiltRendererKeys.Add(rendererKey);
		if (waterAnimationRequired && map != null && textureNodeUploadMethod != null)
			RegisterTerrainWaterAnimationBinding(renderer, rendererType, map, textureNodeUploadMethod, source + "-validated-packed-terrain-state");
		_log?.LogWarning(
			"HoMM3 custom biome registration rebuilt packed terrain materials via "
			+ DescribeRendererType(renderer, rendererType)
			+ "."
			+ (methodName ?? "?")
			+ " with validated packed terrain state.");
		return true;
	}

	private static void ExtendRendererTextureArrayManaged(object renderer, Type rendererType, long rendererKey, string source)
	{
		if (renderer == null || rendererType == null)
			return;
		if (ManagedExtendedRendererKeys.Contains(rendererKey) || RebuiltRendererKeys.Contains(rendererKey))
			return;

		Texture2DArray extended = null;
		var assignedExtended = false;
		TextureArrayAccessor textureAccessor = default;
		Texture2DArray sourceArray = null;
		TerrainPackedTextureArrayBindingSnapshot bindingSnapshot = null;
		try
		{
			textureAccessor = FindRendererTextureArrayAccessor(renderer, rendererType);
			if (!textureAccessor.IsValid)
			{
				_log?.LogWarning("HoMM3 custom biome registration could not managed-extend packed terrain textures: no renderer Texture2DArray field/property.");
				return;
			}

			sourceArray = textureAccessor.Get(renderer) as Texture2DArray;
			if (!sourceArray)
			{
				_log?.LogWarning("HoMM3 custom biome registration could not managed-extend packed terrain textures: renderer Texture2DArray was null.");
				return;
			}

			var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
			if (materialLookup.Value == null)
			{
				_log?.LogWarning("HoMM3 custom biome registration could not managed-extend packed terrain textures: material lookup dictionary was missing.");
				return;
			}

			var highestSlot = -1;
			foreach (var definition in ResolveActiveMapVisualDefinitions())
			{
				if (!materialLookup.Value.ContainsKey(definition.TileCode))
				{
					_log?.LogWarning(
						"HoMM3 custom biome registration could not managed-extend packed terrain textures: material lookup missing tileCode="
						+ definition.TileCode
						+ " on "
						+ DescribeRendererType(renderer, rendererType)
						+ ".");
					return;
				}
				highestSlot = Math.Max(highestSlot, materialLookup.Value[definition.TileCode]);
			}
			if (highestSlot < sourceArray.depth)
			{
				if (TryValidateRendererPackedMaterialState(renderer, rendererType, out _))
					ManagedExtendedRendererKeys.Add(rendererKey);
				return;
			}
			if (!HasActiveTerrainPackedTextureArrayMaterialBinding(out var bindingReason))
			{
				_log?.LogWarning(
					"HoMM3 custom biome registration skipped managed packed terrain texture extension: "
					+ bindingReason
					+ ".");
				return;
			}

			var extendedDepth = highestSlot + 1;
			extended = new Texture2DArray(sourceArray.width, sourceArray.height, extendedDepth, sourceArray.format, sourceArray.mipmapCount > 1)
			{
				name = (sourceArray.name ?? "terrain_texture_array") + "_homm3_extended",
				filterMode = sourceArray.filterMode,
				wrapMode = sourceArray.wrapMode,
				anisoLevel = sourceArray.anisoLevel
			};
			// Every slice below is filled by GPU-side Graphics.CopyTexture. Upload the (empty) CPU buffer first:
			// an Apply after the copies would overwrite slices from a non-readable native array with zeros (black ground).
			extended.Apply(false, false);

			for (var slice = 0; slice < sourceArray.depth; slice++)
			{
				for (var mip = 0; mip < Math.Min(sourceArray.mipmapCount, extended.mipmapCount); mip++)
					Graphics.CopyTexture(sourceArray, slice, mip, extended, slice, mip);
			}

			foreach (var definition in ResolveActiveMapVisualDefinitions())
			{
				var slot = materialLookup.Value[definition.TileCode];
				CopyBiomeTextureToArraySlot(GetPrimaryDefinitionTexture(definition), extended, slot, sourceArray.format);
			}
			textureAccessor.Set(renderer, extended);
			assignedExtended = true;
			bindingSnapshot = BindTerrainPackedTextureArray(extended);

			LogTerrainMaterialAudit(renderer, rendererType, source);
			if (!TryValidateManagedRendererPackedTextureArray(renderer, rendererType, textureAccessor, extended, out var reason)
			    || !TryValidateRendererPackedMaterialState(renderer, rendererType, out reason))
			{
				RestoreTerrainPackedTextureArrayBindings(bindingSnapshot);
				textureAccessor.Set(renderer, sourceArray);
				assignedExtended = false;
				UnityEngine.Object.Destroy(extended);
				extended = null;
				_log?.LogWarning(
					"HoMM3 custom biome registration rejected managed packed terrain texture extension: "
					+ reason
					+ ".");
				return;
			}

			ManagedExtendedRendererKeys.Add(rendererKey);
			_log?.LogWarning(
				"HoMM3 custom biome registration managed-extended packed terrain Texture2DArray via "
				+ DescribeRendererType(renderer, rendererType)
				+ "."
				+ textureAccessor.Name
				+ " from depth "
				+ sourceArray.depth
				+ " to "
				+ extended.depth
				+ " and bound it to Hex/TerrainMap packed texture properties.");
		}
		catch (Exception ex)
		{
			if (assignedExtended)
			{
				RestoreTerrainPackedTextureArrayBindings(bindingSnapshot);
				try { textureAccessor.Set(renderer, sourceArray); }
				catch { }
				assignedExtended = false;
			}
			_log?.LogWarning(
				"HoMM3 custom biome registration managed packed terrain texture extension failed via "
				+ (source ?? "?")
				+ ": "
				+ ex.GetType().Name
				+ ": "
				+ ex.Message);
		}
		finally
		{
			if (extended && !assignedExtended)
				UnityEngine.Object.Destroy(extended);
		}
	}

	private struct TextureArrayAccessor
	{
		public FieldInfo Field;
		public PropertyInfo Property;
		public bool IsValid => Field != null || Property != null;
		public string Name => Field != null ? Field.Name : Property?.Name;
		public object Get(object target) => Field != null ? Field.GetValue(target) : Property.GetValue(target);
		public void Set(object target, object value)
		{
			if (Field != null)
			{
				Field.SetValue(target, value);
				return;
			}
			Property.SetValue(target, value);
		}
	}

	private static TextureArrayAccessor FindRendererTextureArrayAccessor(object renderer, Type rendererType)
	{
		foreach (var symbol in GameSymbols.TerrainMaterial.RendererPackedTextureArrays)
		{
			var field = FindField(rendererType, symbol);
			if (field != null && typeof(Texture2DArray).IsAssignableFrom(field.FieldType))
			{
				try
				{
					if (field.GetValue(renderer) is Texture2DArray textureArray && textureArray)
						return new TextureArrayAccessor { Field = field };
				}
				catch
				{
				}
			}
			var property = FindProperty(rendererType, symbol);
			if (property == null || !property.CanRead || !property.CanWrite || !typeof(Texture2DArray).IsAssignableFrom(property.PropertyType))
				continue;
			try
			{
				if (property.GetValue(renderer) is Texture2DArray textureArray && textureArray)
					return new TextureArrayAccessor { Property = property };
			}
			catch
			{
			}
		}
		return default;
	}

	private static bool TryValidateManagedRendererPackedTextureArray(object renderer, Type rendererType, TextureArrayAccessor textureAccessor, Texture2DArray expected, out string reason)
	{
		reason = null;
		if (!textureAccessor.IsValid || !expected)
		{
			reason = "managed packed texture accessor or expected array was missing";
			return false;
		}
		try
		{
			var current = textureAccessor.Get(renderer) as Texture2DArray;
			if (!TexturesReferenceSameNativeObject(current, expected))
			{
				reason = "renderer packed texture accessor did not retain the managed extended array";
				return false;
			}
			var requiredSlot = GetHighestCustomMaterialSlot(renderer, rendererType);
			if (requiredSlot >= expected.depth)
			{
				reason = "managed extended array depth " + expected.depth + " does not cover required slot " + requiredSlot;
				return false;
			}
			if (!TryValidateTerrainPackedTextureArrayBinding(expected, out reason))
				return false;
			return true;
		}
		catch (Exception ex)
		{
			reason = "managed packed texture validation failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private sealed class TerrainPackedTextureArrayBindingSnapshot
	{
		public Material Material;
		public readonly Dictionary<string, Texture> MaterialTextures = new(StringComparer.Ordinal);
		public readonly List<string> BoundProperties = new();
	}

	private static TerrainPackedTextureArrayBindingSnapshot BindTerrainPackedTextureArray(Texture2DArray textureArray)
	{
		var snapshot = new TerrainPackedTextureArrayBindingSnapshot();
		if (!textureArray)
			return snapshot;
		var material = SoTerrainMaterial.instance?.terrainMaterial;
		snapshot.Material = material;
		foreach (var propertyName in GameSymbols.TerrainMaterial.TerrainMapPackedTextureArrayProperties)
		{
			if (string.IsNullOrWhiteSpace(propertyName))
				continue;
			if (!material)
				continue;
			try
			{
				if (!material.HasProperty(propertyName))
					continue;
				snapshot.MaterialTextures[propertyName] = material.GetTexture(propertyName);
				material.SetTexture(propertyName, textureArray);
				snapshot.BoundProperties.Add("material:" + propertyName);
			}
			catch (Exception ex)
			{
				_log?.LogWarning("HoMM3 custom biome registration could not bind material terrain packed texture "
					+ propertyName
					+ ": "
					+ ex.GetType().Name
					+ ": "
					+ ex.Message);
			}
		}
		if (snapshot.BoundProperties.Count > 0)
		{
			_log?.LogWarning("HoMM3 custom biome registration bound managed packed terrain Texture2DArray to "
				+ string.Join(", ", snapshot.BoundProperties)
				+ ".");
		}
		return snapshot;
	}

	private static void RestoreTerrainPackedTextureArrayBindings(TerrainPackedTextureArrayBindingSnapshot snapshot)
	{
		if (snapshot == null)
			return;
		if (!snapshot.Material)
			return;
		foreach (var entry in snapshot.MaterialTextures)
		{
			try { snapshot.Material.SetTexture(entry.Key, entry.Value); }
			catch { }
		}
	}

	private static bool TryValidateTerrainPackedTextureArrayBinding(Texture2DArray expected, out string reason)
	{
		reason = null;
		if (!expected)
		{
			reason = "expected managed packed terrain Texture2DArray was missing";
			return false;
		}
		var material = SoTerrainMaterial.instance?.terrainMaterial;
		foreach (var propertyName in GameSymbols.TerrainMaterial.TerrainMapPackedTextureArrayProperties)
		{
			if (string.IsNullOrWhiteSpace(propertyName))
				continue;
			if (material && material.HasProperty(propertyName))
			{
				try
				{
					if (TexturesReferenceSameNativeObject(material.GetTexture(propertyName) as Texture2DArray, expected))
						return true;
				}
				catch
				{
				}
			}
		}
		reason = "managed extended terrain Texture2DArray was not retained by any active Hex/TerrainMap material packed texture binding";
		return false;
	}

	private static bool HasActiveTerrainPackedTextureArrayMaterialBinding(out string reason)
	{
		reason = null;
		var material = SoTerrainMaterial.instance?.terrainMaterial;
		if (!material)
		{
			reason = "SoTerrainMaterial.terrainMaterial was null; cannot bind managed packed terrain Texture2DArray";
			return false;
		}
		foreach (var propertyName in GameSymbols.TerrainMaterial.TerrainMapPackedTextureArrayProperties)
		{
			if (string.IsNullOrWhiteSpace(propertyName))
				continue;
			try
			{
				if (material.HasProperty(propertyName))
					return true;
			}
			catch
			{
			}
		}
		reason = "active Hex/TerrainMap material does not expose centralized packed texture property "
		         + string.Join("/", GameSymbols.TerrainMaterial.TerrainMapPackedTextureArrayProperties)
		         + "; live material textures are "
		         + DescribeMaterialTexturesForAudit(material);
		return false;
	}

	private static bool TexturesReferenceSameNativeObject(Texture2DArray current, Texture2DArray expected)
	{
		if (!current || !expected)
			return false;
		if (ReferenceEquals(current, expected))
			return true;
		try
		{
			var currentPtr = IL2CPP.Il2CppObjectBaseToPtr((Il2CppObjectBase)(object)current);
			var expectedPtr = IL2CPP.Il2CppObjectBaseToPtr((Il2CppObjectBase)(object)expected);
			return currentPtr != IntPtr.Zero && currentPtr == expectedPtr;
		}
		catch
		{
			return false;
		}
	}

	private static int GetHighestCustomMaterialSlot(object renderer, Type rendererType)
	{
		var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		if (materialLookup.Value == null)
			return -1;
		var highest = -1;
		foreach (var definition in ResolveActiveMapVisualDefinitions())
		{
			if (materialLookup.Value.ContainsKey(definition.TileCode))
				highest = Math.Max(highest, materialLookup.Value[definition.TileCode]);
		}
		return highest;
	}

	private static void CopyBiomeTextureToArraySlot(Texture2D source, Texture2DArray target, int slot, TextureFormat targetFormat)
	{
		CopyTerrainTextureToArraySlot(source, target, slot, targetFormat);
	}

	internal static Texture2D PrepareTerrainTextureForArraySlot(Texture2D source, Texture2DArray target, TextureFormat targetFormat, string nameSuffix)
	{
		if (!source || !target)
			throw new InvalidOperationException("Custom biome texture was missing for terrain texture array conversion.");

		var temp = RenderTexture.GetTemporary(target.width, target.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
		var previous = RenderTexture.active;
		Texture2D resized = null;
		try
		{
			Graphics.Blit(source, temp);
			RenderTexture.active = temp;
			resized = new Texture2D(target.width, target.height, targetFormat, target.mipmapCount > 1)
			{
				name = source.name + "_terrain_" + (string.IsNullOrWhiteSpace(nameSuffix) ? "prepared" : nameSuffix),
				filterMode = target.filterMode,
				wrapMode = target.wrapMode
			};
			resized.ReadPixels(new Rect(0, 0, target.width, target.height), 0, 0);
			resized.Apply(target.mipmapCount > 1, false);
			var prepared = resized;
			resized = null;
			return prepared;
		}
		finally
		{
			RenderTexture.active = previous;
			if (resized)
				UnityEngine.Object.Destroy(resized);
			RenderTexture.ReleaseTemporary(temp);
		}
	}

	internal static void CopyPreparedTerrainTextureToArraySlot(Texture2D source, Texture2DArray target, int slot)
	{
		if (!source || !target)
			throw new InvalidOperationException("Prepared terrain texture was missing for terrain texture array slot " + slot + ".");
		if (slot < 0 || slot >= target.depth)
			throw new InvalidOperationException("Terrain texture array slot " + slot + " is outside target depth " + target.depth + ".");
		if (source.width != target.width || source.height != target.height)
			throw new InvalidOperationException("Prepared terrain texture size " + source.width + "x" + source.height + " does not match target texture array size " + target.width + "x" + target.height + ".");
		for (var mip = 0; mip < Math.Min(source.mipmapCount, target.mipmapCount); mip++)
			Graphics.CopyTexture(source, 0, mip, target, slot, mip);
	}

	internal static void CopyTerrainTextureToArraySlot(Texture2D source, Texture2DArray target, int slot, TextureFormat targetFormat)
	{
		var prepared = PrepareTerrainTextureForArraySlot(source, target, targetFormat, "slot_" + slot.ToString(CultureInfo.InvariantCulture));
		try
		{
			CopyPreparedTerrainTextureToArraySlot(prepared, target, slot);
		}
		finally
		{
			if (prepared)
				UnityEngine.Object.Destroy(prepared);
		}
	}

	private static bool RequiresTerrainWaterAnimationBinding(string source)
	{
		// Native animated ocean visuals use MapData.waterMap bytes and the bws water-mesh chunk
		// system. Homm3TerrainWaterAnimator terrain packed-color painting is retired.
		return false;
	}

	private static bool HasRequiredWaterAnimationBindingContext(bool waterAnimationRequired, Map map, MethodInfo textureNodeUploadMethod, string source)
	{
		if (!waterAnimationRequired || (map != null && textureNodeUploadMethod != null))
			return true;
		_log?.LogWarning(
			"HoMM3 custom biome registration could not mark packed terrain rebuild complete via "
			+ (source ?? "?")
			+ ": required map-scoped terrain water animation texture-node upload context was missing.");
		return false;
	}

	private static void RegisterTerrainWaterAnimationBinding(object renderer, Type rendererType, Map map, MethodInfo textureNodeUploadMethod, string source)
	{
		if (renderer == null)
			throw WaterAnimationBindingFailure(source, "renderer was null");
		if (rendererType == null)
			throw WaterAnimationBindingFailure(source, "renderer type was null");
		if (map == null)
			throw WaterAnimationBindingFailure(source, "map was null");
		if (textureNodeUploadMethod == null)
			throw WaterAnimationBindingFailure(source, "verified texture-node upload method was null");
		if (!_currentMapVisualSlotScopeKnown || _currentMapNativeWaterTerrainTileCodes == null || _currentMapNativeWaterTerrainTileCodes.Count == 0)
			return;
		var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		if (materialLookup.Value == null)
			throw WaterAnimationBindingFailure(source, "material lookup was missing");
		if (!TryReadPackedStateArray(renderer, rendererType, "colors", out var colorsValue, out var colorsName))
			throw WaterAnimationBindingFailure(source, "packed color layer array was missing");
		if (colorsValue is not Il2CppReferenceArray<Il2CppStructArray<Color>> colors)
			throw WaterAnimationBindingFailure(source, "packed color layer array had unexpected type " + colorsValue.GetType().FullName);
		var layerLength = 0;
		for (var index = 0; index < colors.Length; index++)
		{
			Il2CppStructArray<Color> layer = null;
			try { layer = colors[index]; }
			catch { continue; }
			if (layer == null || layer.Length <= 0)
				continue;
			layerLength = layer.Length;
			break;
		}
		if (layerLength <= 0)
			throw WaterAnimationBindingFailure(source, colorsName + " had no initialized packed color layers");
		if (!TryResolveCurrentPackedLayerShape(layerLength, out var shape, out var shapeReason))
			throw WaterAnimationBindingFailure(source, "unexpected " + colorsName + " layer length " + layerLength.ToString(CultureInfo.InvariantCulture) + ": " + shapeReason);
		var slots = new Dictionary<int, int>();
		foreach (var tileCode in _currentMapNativeWaterTerrainTileCodes.OrderBy(value => value))
		{
			if (!materialLookup.Value.ContainsKey(tileCode))
				throw WaterAnimationBindingFailure(source, "material lookup missing native water terrain tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture));
			var slot = materialLookup.Value[tileCode];
			if (slot < 0 || slot >= colors.Length)
				throw WaterAnimationBindingFailure(source, "native water terrain tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + " slot=" + slot.ToString(CultureInfo.InvariantCulture) + " outside packed color layer length=" + colors.Length.ToString(CultureInfo.InvariantCulture));
			slots[tileCode] = slot;
		}
		Homm3TerrainWaterAnimator.RegisterTerrainPackedColorLayerBinding(renderer, map, textureNodeUploadMethod, colors, slots, shape.Width, shape.Height, GetRendererStateKey(renderer), _currentMapVisualSlotScopeGeneration, source);
	}

	private static InvalidOperationException WaterAnimationBindingFailure(string source, string message, Exception inner = null)
	{
		var fullMessage = "Homecoming terrain water animation binding failed via " + (source ?? "?") + ": " + message + ".";
		return inner == null ? new InvalidOperationException(fullMessage) : new InvalidOperationException(fullMessage, inner);
	}

	private static Texture2D GetPrimaryDefinitionTexture(CustomBiomeDefinition definition)
	{
		if (definition == null || definition.MaterialAliasOnly)
			return null;
		var textures = EnsureReplacementTextures(definition.TextureAssetDir, definition.TextureNamePrefix, definition.TextureFiles);
		return textures.Length > 0 ? textures[0] : null;
	}

    private readonly struct PackedLayerShape
    {
        internal PackedLayerShape(int width, int height)
        {
            Width = width;
            Height = height;
        }

        internal int Width { get; }
        internal int Height { get; }
        internal int Length => Width * Height;
        internal string Description => Width.ToString(CultureInfo.InvariantCulture) + "x" + Height.ToString(CultureInfo.InvariantCulture);
    }

    private static string DescribeCurrentPackedLayerShape()
    {
        if (!_currentMapVisualSlotScopeKnown || _currentMapPackedLayerWidth <= 0 || _currentMapPackedLayerHeight <= 0)
            return "<shape-unset>";
        return _currentMapPackedLayerWidth.ToString(CultureInfo.InvariantCulture)
               + "x"
               + _currentMapPackedLayerHeight.ToString(CultureInfo.InvariantCulture);
    }

    private static bool TryResolveCurrentPackedLayerShape(int layerLength, out PackedLayerShape shape, out string reason)
    {
        shape = default;
        reason = null;
        if (!_currentMapVisualSlotScopeKnown || _currentMapPackedLayerWidth <= 0 || _currentMapPackedLayerHeight <= 0)
        {
            reason = "active map packed layer dimensions were unresolved";
            return false;
        }
        var expectedLength = (long)_currentMapPackedLayerWidth * _currentMapPackedLayerHeight;
        if (expectedLength != layerLength)
        {
            reason = "active map packed layer "
                     + DescribeCurrentPackedLayerShape()
                     + " requires length "
                     + expectedLength.ToString(CultureInfo.InvariantCulture)
                     + " but renderer layer length was "
                     + layerLength.ToString(CultureInfo.InvariantCulture);
            return false;
        }
        shape = new PackedLayerShape(_currentMapPackedLayerWidth, _currentMapPackedLayerHeight);
        return true;
    }
	private static bool SeedRendererPackedColorLayersBeforeNativeRebuild(object renderer, Type rendererType, MethodInfo method, out string reason)
	{
		reason = null;
		if (renderer == null || rendererType == null || method == null)
		{
			reason = "renderer, renderer type, or rebuild method was missing";
			return false;
		}
		if (!ShouldPreserveCachedTerrainMaterialForRebuild(rendererType, method))
			return true;
		var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		if (materialLookup.Value == null)
		{
			reason = "material lookup dictionary was missing";
			return false;
		}
		if (!TryReadPackedStateArray(renderer, rendererType, "colors", out var colorsValue, out var colorsName))
		{
			reason = "packed terrain colors array was missing before native rebuild";
			return false;
		}
		if (colorsValue is not Il2CppReferenceArray<Il2CppStructArray<Color>> colors)
		{
			reason = "packed terrain colors array had unexpected type " + colorsValue.GetType().FullName;
			return false;
		}

		var layerLength = 0;
		for (var i = 0; i < colors.Length; i++)
		{
			Il2CppStructArray<Color> layer = null;
			try { layer = colors[i]; }
			catch { continue; }
			if (layer == null || layer.Length <= 0)
				continue;
			layerLength = layer.Length;
			break;
		}
		if (layerLength <= 0)
		{
			reason = "packed terrain colors array had no initialized source layers before native rebuild";
			return false;
		}
		if (!TryResolveCurrentPackedLayerShape(layerLength, out var shape, out var shapeReason))
		{
			reason = "unexpected " + colorsName + " layer length " + layerLength.ToString(CultureInfo.InvariantCulture) + ": " + shapeReason;
			return false;
		}

		var enforced = new List<string>();
		foreach (var definition in ResolveActiveMapVisualDefinitions())
		{
			if (!materialLookup.Value.ContainsKey(definition.TileCode))
			{
				reason = "material lookup missing custom tileCode=" + definition.TileCode.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			var slot = materialLookup.Value[definition.TileCode];
			if (slot < 0 || slot >= colors.Length)
			{
				reason = "custom material slot " + slot.ToString(CultureInfo.InvariantCulture) + " outside colors length " + colors.Length.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			var texture = GetPrimaryDefinitionTexture(definition);
			if (!texture)
			{
				reason = "custom biome texture missing for tileCode=" + definition.TileCode.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			var layer = BuildPackedColorLayer(texture, shape);
			if (layer == null)
			{
				reason = "could not build packed color layer for tileCode=" + definition.TileCode.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			colors[slot] = layer;
			enforced.Add(definition.TileCode.ToString(CultureInfo.InvariantCulture) + "->" + slot.ToString(CultureInfo.InvariantCulture) + ":" + texture.name);
		}
		if (enforced.Count == 0)
		{
			reason = "no custom packed terrain color layers were seeded before native rebuild";
			return false;
		}
		_log?.LogWarning(
			"HoMM3 custom biome registration seeded custom packed terrain color layer(s) before native rebuild in "
			+ colorsName
			+ " for "
			+ rendererType.Name
			+ "."
			+ method.Name
			+ " shape="
			+ shape.Description
			+ ": "
			+ string.Join(", ", enforced)
			+ ".");
		return true;
	}

    internal static Il2CppStructArray<Color> BuildTerrainPackedColorLayer(Texture2D texture, int layerWidth, int layerHeight)
    {
        return BuildPackedColorLayer(texture, new PackedLayerShape(layerWidth, layerHeight));
    }

    private static Il2CppStructArray<Color> BuildPackedColorLayer(Texture2D texture, PackedLayerShape shape)
    {
        if (!texture || shape.Width <= 0 || shape.Height <= 0)
            return null;
        try
        {
            if (!texture.isReadable)
            {
                _log?.LogWarning("HoMM3 custom biome registration failed to build packed terrain color layer from " + (texture.name ?? "?") + ": texture is not readable.");
                return null;
            }
            var layer = new Il2CppStructArray<Color>(shape.Length);
            for (var y = 0; y < shape.Height; y++)
            {
                var v = (y + 0.5f) / shape.Height;
                for (var x = 0; x < shape.Width; x++)
                {
                    var u = (x + 0.5f) / shape.Width;
                    layer[(y * shape.Width) + x] = texture.GetPixelBilinear(u, v);
                }
            }
            return layer;
        }
        catch (Exception ex)
        {
            _log?.LogWarning("HoMM3 custom biome registration failed to build packed terrain color layer from " + (texture.name ?? "?") + ": " + ex.GetType().Name + ": " + ex.Message);
            return null;
        }
    }
	/// <summary>
	/// Crash breadcrumbs (2026-10-18): the 10-17 20:09 coreclr AV (0x1d1fdd, an uncatchable managed access violation) on the
	/// 4th new-map load in one session fell inside this validation. LogOutput flushes instantly (BepInEx InstantFlushing),
	/// so the last crumb names the native read that faulted. Remove once that read is fixed.
	/// </summary>
	private static int _crumbPass;

	private static void Crumb(string step)
	{
		_log?.LogInfo("HoMM3 biome crumb #" + _crumbPass.ToString(CultureInfo.InvariantCulture) + ": " + step);
	}

	private static bool TryValidateRendererPackedMaterialState(object renderer, Type rendererType, out string reason)
	{
		reason = null;
		_crumbPass++;
		Crumb("validate start renderer=" + DescribeRendererType(renderer, rendererType));
		var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		Crumb("material lookup read (" + (materialLookup.Value == null ? "null" : "ok") + ")");
		if (materialLookup.Value == null)
		{
			reason = "material lookup dictionary was missing";
			return false;
		}

		var requiredSlot = -1;
		var requiredSlots = new List<(int Slot, CustomBiomeDefinition Definition)>();
		foreach (var definition in ResolveActiveMapVisualDefinitions())
		{
			if (!materialLookup.Value.ContainsKey(definition.TileCode))
			{
				reason = "material lookup is missing tileCode=" + definition.TileCode;
				return false;
			}
			var slot = materialLookup.Value[definition.TileCode];
			Crumb("tileCode " + definition.TileCode.ToString(CultureInfo.InvariantCulture) + " -> slot " + slot.ToString(CultureInfo.InvariantCulture));
			requiredSlot = Math.Max(requiredSlot, slot);
			requiredSlots.Add((slot, definition));
		}

		if (requiredSlot < 0)
		{
			reason = "no non-alias custom biome material slots were required";
			return true;
		}

		Crumb("reading SoTerrainMaterial.terrainMaterial");
		var terrainMaterial = SoTerrainMaterial.instance?.terrainMaterial;
		if (!terrainMaterial)
		{
			reason = "SoTerrainMaterial.terrainMaterial was null after rebuild";
			return false;
		}

		Crumb("texture-node binding check");
		var hasTextureNodesBinding = HasActiveTerrainTextureNodesBinding(terrainMaterial, out var textureNodesDescription);
		Crumb("texture-node binding " + (hasTextureNodesBinding ? "present" : "absent"));
		if (!hasTextureNodesBinding)
		{
			var textureArrayDepth = FindRendererTextureArrayDepth(renderer, rendererType);
			if (textureArrayDepth <= 0)
			{
				reason = "no renderer Texture2DArray field/property was readable for material slot " + requiredSlot;
				return false;
			}
			if (requiredSlot >= textureArrayDepth)
			{
				reason = "material slot " + requiredSlot + " exceeds renderer Texture2DArray depth " + textureArrayDepth;
				return false;
			}
		}
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "colors", requiredSlot, out reason))
			return false;
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "nodes", requiredSlot, out reason))
			return false;
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "splat0", requiredSlot, out reason))
			return false;
		if (!TryValidatePackedStateArrayLength(renderer, rendererType, "splat1", requiredSlot, out reason))
			return false;
		foreach (var required in requiredSlots)
		{
			Crumb("slot " + required.Slot.ToString(CultureInfo.InvariantCulture) + " color layer");
			if (!TryValidateCustomSlotPackedColorLayer(renderer, rendererType, required.Slot, required.Definition, out reason))
				return false;
			Crumb("slot " + required.Slot.ToString(CultureInfo.InvariantCulture) + " vector metadata");
			if (!TryValidateCustomSlotVectorMetadata(renderer, rendererType, required.Slot, out reason))
				return false;
		}
		Crumb("validate done");

		if (hasTextureNodesBinding)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration validated active Hex/TerrainMap texture-node binding "
				+ textureNodesDescription
				+ "; skipping stale renderer Texture2DArray depth gate for this material path.");
		}

		return true;
	}

	private static bool HasActiveTerrainTextureNodesBinding(Material terrainMaterial, out string description)
	{
		description = null;
		if (!terrainMaterial)
			return false;
		foreach (var propertyName in GameSymbols.TerrainMaterial.TerrainMapTextureNodeProperties)
		{
			if (string.IsNullOrWhiteSpace(propertyName))
				continue;
			try
			{
				if (!terrainMaterial.HasProperty(propertyName))
					continue;
				var texture = terrainMaterial.GetTexture(propertyName);
				if (!texture)
					continue;
				description = propertyName
				              + "="
				              + (texture.name ?? "?")
				              + ":"
				              + texture.GetType().Name
				              + ":"
				              + texture.width.ToString(CultureInfo.InvariantCulture)
				              + "x"
				              + texture.height.ToString(CultureInfo.InvariantCulture);
				return true;
			}
			catch
			{
			}
		}
		return false;
	}

	private static bool TryValidatePackedStateArrayLength(object renderer, Type rendererType, string stateKind, int requiredSlot, out string reason)
	{
		reason = null;
		Crumb("length " + stateKind + ": read array");
		if (!TryReadPackedStateArray(renderer, rendererType, stateKind, out var array, out var name))
		{
			reason = "packed terrain " + stateKind + " array was missing";
			return false;
		}
		Crumb("length " + stateKind + ": " + name + " " + array.GetType().Name + " length");
		var length = ArrayLikeLength(array);
		if (requiredSlot >= length)
		{
			reason = "material slot "
			         + requiredSlot
			         + " exceeds packed terrain "
			         + stateKind
			         + " array "
			         + name
			         + " length "
			         + length;
			return false;
		}
		return true;
	}

    private static bool TryValidateCustomSlotPackedColorLayer(object renderer, Type rendererType, int slot, CustomBiomeDefinition definition, out string reason)
    {
        reason = null;
        if (!TryReadPackedStateArray(renderer, rendererType, "colors", out var array, out var name))
        {
            reason = "packed terrain colors array was missing for custom material slot " + slot;
            return false;
        }
        Crumb("colors " + name + ": element " + slot.ToString(CultureInfo.InvariantCulture));
        if (!TryReadArrayLikeElement(array, slot, out var item, out var itemReason))
        {
            reason = "packed terrain colors array " + name + " could not read custom material slot " + slot + ": " + itemReason;
            return false;
        }
        Crumb("colors element " + (item == null ? "null" : item.GetType().Name) + ": nested length");
        if (item == null)
        {
            reason = "custom material slot " + slot + " has no packed color layer in " + name;
            return false;
        }
        var nestedLength = ArrayLikeLength(item);
        if (nestedLength == 0)
        {
            reason = "custom material slot " + slot + " has an empty packed color layer in " + name;
            return false;
        }
        if (!TryResolveCurrentPackedLayerShape(nestedLength, out var shape, out var shapeReason))
        {
            reason = "custom material slot "
                     + slot
                     + " packed color layer length "
                     + nestedLength.ToString(CultureInfo.InvariantCulture)
                     + " does not match active map shape: "
                     + shapeReason;
            return false;
        }
        if (definition == null)
        {
            reason = "custom material slot " + slot + " has no custom biome definition for packed color validation";
            return false;
        }
        Crumb("colors: primary texture");
        var texture = GetPrimaryDefinitionTexture(definition);
        if (!texture)
        {
            reason = "custom material slot " + slot + " has no primary texture for packed color validation";
            return false;
        }
        if (!PackedColorLayerMatchesTexture(item, texture, shape, out var mismatch))
        {
            reason = "custom material slot "
                     + slot
                     + " packed color layer does not match "
                     + texture.name
                     + " in "
                     + name
                     + " shape="
                     + shape.Description
                     + ": "
                     + mismatch;
            return false;
        }
        return true;
    }
    private static bool PackedColorLayerMatchesTexture(object layerObject, Texture2D texture, PackedLayerShape shape, out string mismatch)
    {
        mismatch = null;
        if (layerObject is not Il2CppStructArray<Color> layer)
        {
            mismatch = "layer is not a Color array";
            return false;
        }
        if (!texture || shape.Width <= 0 || shape.Height <= 0 || layer.Length < shape.Length)
        {
            mismatch = "layer or texture was invalid";
            return false;
        }
        var samples = new[]
        {
            (0, 0),
            (Math.Max(0, shape.Width / 2), Math.Max(0, shape.Height / 2)),
            (Math.Max(0, shape.Width - 1), Math.Max(0, shape.Height - 1))
        };
        foreach (var sample in samples)
        {
            var x = sample.Item1;
            var y = sample.Item2;
            var u = (x + 0.5f) / shape.Width;
            var v = (y + 0.5f) / shape.Height;
            Crumb("sample " + x.ToString(CultureInfo.InvariantCulture) + "," + y.ToString(CultureInfo.InvariantCulture) + ": layer read (length " + layer.Length.ToString(CultureInfo.InvariantCulture) + ")");
            var actual = layer[(y * shape.Width) + x];
            Crumb("sample: texture " + texture.name + " GetPixelBilinear");
            var expected = texture.GetPixelBilinear(u, v);
            if (!ColorsClose(actual, expected, 0.025f))
            {
                mismatch = "sample "
                           + x.ToString(CultureInfo.InvariantCulture)
                           + ","
                           + y.ToString(CultureInfo.InvariantCulture)
                           + " actual="
                           + FormatColor(actual)
                           + " expected="
                           + FormatColor(expected);
                return false;
            }
        }
        return true;
    }
	private static bool ColorsClose(Color actual, Color expected, float tolerance)
	{
		return Math.Abs(actual.r - expected.r) <= tolerance
		       && Math.Abs(actual.g - expected.g) <= tolerance
		       && Math.Abs(actual.b - expected.b) <= tolerance
		       && Math.Abs(actual.a - expected.a) <= tolerance;
	}

	private static string FormatColor(Color color)
	{
		return "("
		       + color.r.ToString("0.###", CultureInfo.InvariantCulture)
		       + ","
		       + color.g.ToString("0.###", CultureInfo.InvariantCulture)
		       + ","
		       + color.b.ToString("0.###", CultureInfo.InvariantCulture)
		       + ","
		       + color.a.ToString("0.###", CultureInfo.InvariantCulture)
		       + ")";
	}

	private static bool TryValidateCustomSlotVectorMetadata(object renderer, Type rendererType, int slot, out string reason)
	{
		reason = null;
		var readable = 0;
		var nonZero = 0;
		foreach (var stateKind in new[] { "nodes", "splat0", "splat1" })
		{
			if (!TryReadPackedStateArray(renderer, rendererType, stateKind, out var array, out var name))
			{
				reason = "packed terrain " + stateKind + " array was missing for custom material slot " + slot;
				return false;
			}
			Crumb("vector " + stateKind + " " + name + " " + array.GetType().Name + ": element " + slot.ToString(CultureInfo.InvariantCulture));
			if (!TryReadArrayLikeElement(array, slot, out var item, out var itemReason))
			{
				reason = "packed terrain " + stateKind + " array " + name + " could not read custom material slot " + slot + ": " + itemReason;
				return false;
			}
			readable++;
			Crumb("vector " + stateKind + ": zero test on " + (item == null ? "null" : item.GetType().Name));
			if (!IsZeroVectorLike(item))
				nonZero++;
		}
		if (readable == 0 || nonZero == 0)
		{
			reason = "custom material slot " + slot + " has zero packed vector metadata across nodes/splat0/splat1";
			return false;
		}
		return true;
	}


	internal static bool TryGetCurrentTerrainPackedColorLayers(object renderer, int expectedLayerLength, out Il2CppReferenceArray<Il2CppStructArray<Color>> colors, out string reason)
	{
		colors = null;
		reason = null;
		if (renderer == null)
		{
			reason = "renderer was null";
			return false;
		}
		var rendererType = renderer.GetType();
		if (!TryReadPackedStateArray(renderer, rendererType, "colors", out var colorsValue, out var colorsName))
		{
			reason = "packed terrain colors array was missing";
			return false;
		}
		if (colorsValue is not Il2CppReferenceArray<Il2CppStructArray<Color>> typedColors)
		{
			reason = "packed terrain colors array had unexpected type " + colorsValue.GetType().FullName;
			return false;
		}
		if (expectedLayerLength > 0)
		{
			for (var index = 0; index < typedColors.Length; index++)
			{
				Il2CppStructArray<Color> layer = null;
				try { layer = typedColors[index]; }
				catch (Exception ex)
				{
					reason = "packed terrain colors array " + colorsName + " could not read layer " + index.ToString(CultureInfo.InvariantCulture) + ": " + ex.GetType().Name + ": " + ex.Message;
					return false;
				}
				if (layer != null && layer.Length != expectedLayerLength)
				{
					reason = "packed terrain colors array " + colorsName + " layer " + index.ToString(CultureInfo.InvariantCulture) + " length " + layer.Length.ToString(CultureInfo.InvariantCulture) + " did not match expected " + expectedLayerLength.ToString(CultureInfo.InvariantCulture);
					return false;
				}
			}
		}
		colors = typedColors;
		return true;
	}

	private static bool TryReadPackedStateArray(object renderer, Type rendererType, string stateKind, out object array, out string name)
	{
		array = null;
		name = null;
		if (renderer == null || rendererType == null || string.IsNullOrWhiteSpace(stateKind))
			return false;
		foreach (var symbol in GameSymbols.TerrainMaterial.RendererPackedStateFields)
		{
			if (symbol.Id == null || symbol.Id.IndexOf("." + stateKind + ".", StringComparison.Ordinal) < 0)
				continue;
			var field = FindField(rendererType, symbol);
			if (field != null && field.IsStatic)
				field = null;
			PropertyInfo property = null;
			if (field == null)
				property = FindProperty(rendererType, symbol);
			if (property != null && (property.GetMethod == null || property.GetMethod.IsStatic))
				property = null;
			if (field == null && property == null)
				continue;
			try
			{
				array = field != null ? field.GetValue(renderer) : property.GetValue(renderer);
				if (array == null)
					continue;
				name = field?.Name ?? property?.Name ?? stateKind;
				return true;
			}
			catch
			{
				array = null;
			}
		}
		return false;
	}

	private static bool TryReadArrayLikeElement(object array, int index, out object item, out string reason)
	{
		item = null;
		reason = null;
		if (array == null)
		{
			reason = "array was null";
			return false;
		}
		var length = ArrayLikeLength(array);
		if (index < 0 || index >= length)
		{
			reason = "index " + index + " outside length " + length;
			return false;
		}
		if (array is Array managed)
		{
			item = managed.GetValue(index);
			return true;
		}
		var type = array.GetType();
		var getItem = type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance, null, new[] { typeof(int) }, null);
		if (getItem == null)
		{
			reason = "no get_Item(int) accessor";
			return false;
		}
		try
		{
			item = getItem.Invoke(array, new object[] { index });
			return true;
		}
		catch (TargetInvocationException ex)
		{
			reason = (ex.InnerException ?? ex).GetType().Name + ": " + (ex.InnerException ?? ex).Message;
			return false;
		}
		catch (Exception ex)
		{
			reason = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool IsZeroVectorLike(object item)
	{
		if (item == null)
			return true;
		if (item is Vector4 vector)
			return Mathf.Approximately(vector.x, 0f)
			       && Mathf.Approximately(vector.y, 0f)
			       && Mathf.Approximately(vector.z, 0f)
			       && Mathf.Approximately(vector.w, 0f);
		var text = item.ToString();
		if (string.IsNullOrWhiteSpace(text))
			return true;
		return text.IndexOf("(0.00, 0.00, 0.00, 0.00)", StringComparison.Ordinal) >= 0
		       || text.IndexOf("(0, 0, 0, 0)", StringComparison.Ordinal) >= 0;
	}

	private static int FindRendererTextureArrayDepth(object renderer, Type rendererType)
	{
		if (renderer == null || rendererType == null)
			return -1;
		var textureAccessor = FindRendererTextureArrayAccessor(renderer, rendererType);
		if (!textureAccessor.IsValid)
			return -1;
		try
		{
			return textureAccessor.Get(renderer) is Texture2DArray textureArray && textureArray ? textureArray.depth : -1;
		}
		catch
		{
			return -1;
		}
	}

	private static void EnsureBiomeSoundMappings(object heroSoundInstance, object ambientSoundInstance, string source)
	{
		var heroType = heroSoundInstance?.GetType()
		               ?? GameMember.FindType(GameSymbols.TerrainSound.HeroBiomeSoundTypeId, GameSymbols.TerrainSound.HeroBiomeSoundTypeHint);
		var ambientType = ambientSoundInstance?.GetType()
		                  ?? GameMember.FindType(GameSymbols.TerrainSound.AmbientBiomeSoundTypeId, GameSymbols.TerrainSound.AmbientBiomeSoundTypeHint);
		var heroExtended = false;
		var heroInstanceExtended = false;
		var heroSelectorExtended = false;
		var ambientExtended = false;
		foreach (var definition in Definitions)
		{
			foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeStaticArrays)
				heroExtended |= TryExtendStaticArraySlot(heroType, symbol, definition.TileCode, definition.SoundDonorTileCode, source);
			if (heroSoundInstance != null)
			{
				foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeInstanceArrays)
					heroInstanceExtended |= ExtendInstanceArraySlot(heroSoundInstance, heroType, symbol, definition.TileCode, definition.SoundDonorTileCode, source);
			}
			// Golden Era ezd: only static cizf is tile-code-indexed. Instance counts/volumes are
			// EAmbientSoundType.NUM (8); extending them by custom tileCode makes GetSoundsVolume
			// return a longer float[] than ezi.cjab (bool[8]), and ezi.bidt IndexOutOfRange-spams
			// from BhWorldCamera (including ModeBattle.Activate). Per-cell cizd is map-sized.
			ambientExtended |= TryExtendStaticArraySlot(
				ambientType,
				GameSymbols.TerrainSound.AmbientSoundByTileCode,
				definition.TileCode,
				definition.SoundDonorTileCode,
				source);
		}
		if (heroSoundInstance != null)
		{
			foreach (var selector in FindHeroBiomeSelectorInstances(heroSoundInstance, heroType))
				heroSelectorExtended |= EnsureHeroBiomeSelectorMappings(selector, source + " nested selector");
		}
		if (heroExtended || heroInstanceExtended || heroSelectorExtended || ambientExtended)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration extended biome sound mappings via "
				+ source
				+ ": heroStatic="
				+ heroExtended
				+ ", heroInstance="
				+ heroInstanceExtended
				+ ", heroSelector="
				+ heroSelectorExtended
				+ ", ambientStatic="
				+ ambientExtended
				+ ".");
		}
	}

	private static IEnumerable<object> FindHeroBiomeSelectorInstances(object heroSoundInstance, Type heroType)
	{
		if (heroSoundInstance == null || heroType == null)
			return Array.Empty<object>();
		var instances = new List<object>();
		foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeSelectorFields)
		{
			var field = FindField(heroType, symbol);
			var property = field == null ? FindProperty(heroType, symbol.FieldName) : null;
			var value = field != null ? field.GetValue(heroSoundInstance) : property?.GetValue(heroSoundInstance);
			if (value != null)
				instances.Add(value);
		}
		return instances;
	}

	private static bool EnsureHeroBiomeSelectorMappings(object selectorInstance, string source)
	{
		if (selectorInstance == null)
			return false;
		var selectorType = selectorInstance.GetType();
		var extended = false;
		foreach (var definition in Definitions)
		{
			foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeStaticArrays)
				extended |= TryExtendStaticArraySlot(selectorType, symbol, definition.TileCode, definition.SoundDonorTileCode, source);
			foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeInstanceArrays)
				extended |= ExtendInstanceArraySlot(selectorInstance, selectorType, symbol, definition.TileCode, definition.SoundDonorTileCode, source);
		}
		if (extended)
			_log?.LogWarning("HoMM3 custom biome registration extended hero biome selector mappings via " + source + ".");
		return extended;
	}

	private static void EnsureHeroBiomeControllerSelectorMappings(object controllerInstance, string source)
	{
		if (controllerInstance == null)
			return;
		var controllerType = controllerInstance.GetType();
		var extended = false;
		var heroType = GameMember.FindType(GameSymbols.TerrainSound.HeroBiomeSoundTypeId, GameSymbols.TerrainSound.HeroBiomeSoundTypeHint);
		foreach (var field in FindHeroBiomeControllerSelectorFields(controllerType, heroType))
		{
			var selector = field.GetValue(controllerInstance);
			extended |= EnsureHeroBiomeSelectorMappings(selector, source + " " + field.Name);
		}
		if (extended)
			_log?.LogWarning("HoMM3 custom biome registration extended hero biome controller selector via " + source + ".");
	}

	private static void EnsureAmbientFogControllerMappings(object controllerInstance, string source)
	{
		if (!_ambientFogControllerExtensionAvailable)
			return;
		if (controllerInstance == null)
		{
			DisableAmbientFogControllerExtension("controller instance was null via " + source);
			return;
		}

		var controllerType = controllerInstance.GetType();
		var extended = false;
		try
		{
			foreach (var definition in Definitions)
			{
				extended |= ExtendInstanceArraySlotFieldOnly(
					controllerInstance,
					controllerType,
					GameSymbols.TerrainSound.AmbientFogControllerActiveByTileCode,
					definition.TileCode,
					definition.SoundDonorTileCode,
					source);
			}
		}
		catch (Exception ex)
		{
			DisableAmbientFogControllerExtension(ex.Message);
			return;
		}

		if (extended)
		{
			_log?.LogWarning(
				"HoMM3 custom biome registration extended ambient fog controller mappings via "
				+ source
				+ ".");
		}
	}

	private static void DisableAmbientFogControllerExtension(string reason)
	{
		_ambientFogControllerExtensionAvailable = false;
		if (_ambientFogControllerWarningLogged)
			return;
		_ambientFogControllerWarningLogged = true;
		_log?.LogWarning("HoMM3 custom biome registration disabled ambient fog controller extension: " + reason + ".");
	}

	private static bool ExtendStaticArraySlot(Type ownerType, GameSymbols.FieldSymbol symbol, int targetIndex, int donorIndex, string source)
	{
		if (ownerType == null)
			throw new MissingMemberException("Custom biome registration could not resolve owner type for " + symbol.Id + ".");
		if (!TryResolveStaticArrayAccessor(ownerType, symbol, out var field, out var property))
			throw new MissingFieldException(ownerType.FullName, symbol.FieldName);
		var current = field != null ? field.GetValue(null) : property.GetValue(null);
		var extended = ExtendArraySlot(current, targetIndex, donorIndex, symbol.Id, source);
		if (extended == null)
			return false;
		if (field != null)
			field.SetValue(null, extended);
		else
			property.SetValue(null, extended);
		return true;
	}

	private static bool TryExtendStaticArraySlot(Type ownerType, GameSymbols.FieldSymbol symbol, int targetIndex, int donorIndex, string source)
	{
		if (ownerType == null)
			return false;
		if (!TryResolveStaticArrayAccessor(ownerType, symbol, out var field, out var property))
			return false;
		var current = field != null ? field.GetValue(null) : property.GetValue(null);
		var extended = ExtendArraySlot(current, targetIndex, donorIndex, symbol.Id, source);
		if (extended == null)
			return false;
		if (field != null)
			field.SetValue(null, extended);
		else
			property.SetValue(null, extended);
		return true;
	}

	private static bool TryResolveStaticArrayAccessor(Type ownerType, GameSymbols.FieldSymbol symbol, out FieldInfo field, out PropertyInfo property)
	{
		// Il2CppInterop stores NativeFieldInfoPtr_* metadata as IntPtr fields. The real
		// tile-code arrays are properties (e.g. field_Private_Static_Il2CppStructArray_1_EAmbientSoundType_0).
		// Prefer the array property over that metadata pointer or GetValue returns System.IntPtr.
		field = FindArrayStorageField(ownerType, symbol);
		property = FindProperty(ownerType, symbol);
		if (field != null && field.IsStatic)
		{
			property = null;
			return true;
		}
		if (property != null && property.GetMethod != null && property.GetMethod.IsStatic)
		{
			field = null;
			return true;
		}
		field = null;
		property = null;
		return false;
	}

	private static bool ExtendInstanceArraySlot(object instance, Type ownerType, GameSymbols.FieldSymbol symbol, int targetIndex, int donorIndex, string source)
	{
		if (instance == null || ownerType == null)
			return false;
		if (!TryResolveArrayAccessor(ownerType, symbol, out var field, out var property))
			return false;
		var current = field != null ? field.GetValue(instance) : property.GetValue(instance);
		var extended = ExtendArraySlot(current, targetIndex, donorIndex, symbol.Id, source);
		if (extended == null)
			return false;
		if (field != null)
		{
			field.SetValue(instance, extended);
			return true;
		}
		if (property.CanWrite)
		{
			property.SetValue(instance, extended);
			return true;
		}
		var setMethod = ownerType.GetProperty(property.Name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.SetMethod
		                ?? property.SetMethod;
		if (setMethod == null)
			return false;
		setMethod.Invoke(instance, new[] { extended });
		return true;
	}

	private static bool ExtendInstanceArraySlotFieldOnly(object instance, Type ownerType, GameSymbols.FieldSymbol symbol, int targetIndex, int donorIndex, string source)
	{
		if (instance == null || ownerType == null)
			return false;
		var field = FindArrayStorageField(ownerType, symbol);
		if (field == null)
			throw new MissingFieldException(ownerType.FullName, symbol.FieldName);
		var current = field.GetValue(instance);
		var extended = ExtendArraySlot(current, targetIndex, donorIndex, symbol.Id, source);
		if (extended == null)
			return false;
		field.SetValue(instance, extended);
		return true;
	}

	private static object ExtendArraySlot(object current, int targetIndex, int donorIndex, string label, string source)
	{
		if (current == null)
			return null;
		if (current is Array managed)
		{
			if (managed.Length > targetIndex)
				return null;
			if (managed.Length <= donorIndex)
				throw new InvalidOperationException("Custom biome registration cannot extend " + label + " via " + source + ": donor index " + donorIndex + " is outside length " + managed.Length + ".");
			var elementType = managed.GetType().GetElementType();
			if (elementType == null)
				throw new InvalidOperationException("Custom biome registration cannot inspect element type for " + label + ".");
			var replacement = Array.CreateInstance(elementType, targetIndex + 1);
			Array.Copy(managed, replacement, managed.Length);
			replacement.SetValue(managed.GetValue(donorIndex), targetIndex);
			return replacement;
		}

		var currentType = current.GetType();
		if (TryExtendWrappedArray(current, currentType, targetIndex, donorIndex, out var wrappedExtended))
			return wrappedExtended;
		throw new InvalidOperationException("Custom biome registration cannot extend " + label + " via " + source + ": unsupported array wrapper " + currentType.FullName + ".");
	}

	private static bool TryExtendWrappedArray(object current, Type currentType, int targetIndex, int donorIndex, out object extended)
	{
		extended = null;
		if (!TryGetWrappedArrayAccessors(currentType, out var lengthProp, out var itemProp, out var getItem, out var setItem))
			return false;
		var length = Convert.ToInt32(lengthProp.GetValue(current));
		if (length > targetIndex)
			return true;
		if (length <= donorIndex)
			throw new InvalidOperationException("Custom biome registration cannot extend wrapped array: donor index " + donorIndex + " is outside length " + length + ".");
		var wrappedReplacement = CreateWrappedArrayReplacement(currentType, targetIndex + 1);
		for (var i = 0; i < length; i++)
			SetWrappedArrayElement(wrappedReplacement, itemProp, setItem, i, GetWrappedArrayElement(current, itemProp, getItem, i));
		SetWrappedArrayElement(
			wrappedReplacement,
			itemProp,
			setItem,
			targetIndex,
			GetWrappedArrayElement(current, itemProp, getItem, donorIndex));
		extended = wrappedReplacement;
		return true;
	}

	private static long GetRendererStateKey(object renderer)
	{
		if (renderer is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
			return il2Cpp.Pointer.ToInt64();
		return renderer == null ? 0L : renderer.GetHashCode();
	}

	private static object CreateWrappedArrayReplacement(Type currentType, int length)
	{
		try
		{
			return Activator.CreateInstance(currentType, (long)length);
		}
		catch (MissingMethodException)
		{
			return Activator.CreateInstance(currentType, length);
		}
	}

	private static bool TryGetWrappedArrayAccessors(
		Type currentType,
		out PropertyInfo lengthProp,
		out PropertyInfo itemProp,
		out MethodInfo getItem,
		out MethodInfo setItem)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.Instance;
		lengthProp = currentType.GetProperty("Length", flags);
		itemProp = currentType.GetProperty("Item", flags, null, null, new[] { typeof(int) }, null);
		getItem = currentType.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
		setItem = currentType.GetMethod("set_Item", flags, null, new[] { typeof(int), typeof(object) }, null)
		          ?? currentType.GetMethods(flags).FirstOrDefault(method =>
			          string.Equals(method.Name, "set_Item", StringComparison.Ordinal)
			          && method.GetParameters().Length == 2
			          && method.GetParameters()[0].ParameterType == typeof(int));
		if (lengthProp == null)
			return false;
		if (itemProp != null && itemProp.CanRead && itemProp.CanWrite)
			return true;
		return getItem != null && setItem != null;
	}

	private static object GetWrappedArrayElement(object array, PropertyInfo itemProp, MethodInfo getItem, int index)
	{
		if (itemProp != null && itemProp.CanRead)
			return itemProp.GetValue(array, new object[] { index });
		return getItem.Invoke(array, new object[] { index });
	}

	private static void SetWrappedArrayElement(object array, PropertyInfo itemProp, MethodInfo setItem, int index, object value)
	{
		if (itemProp != null && itemProp.CanWrite)
		{
			itemProp.SetValue(array, value, new object[] { index });
			return;
		}
		setItem.Invoke(array, new object[] { index, value });
	}

	private static FieldInfo FindField(Type ownerType, GameSymbols.FieldSymbol symbol)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in EnumerateFieldSymbolNames(symbol))
		{
			for (var t = ownerType; t != null; t = t.BaseType)
			{
				FieldInfo field = null;
				try { field = t.GetField(name, flags | BindingFlags.DeclaredOnly); }
				catch { field = null; }
				if (field != null)
					return field;
			}
		}
		return null;
	}

	private static bool TryResolveArrayAccessor(Type ownerType, GameSymbols.FieldSymbol symbol, out FieldInfo field, out PropertyInfo property)
	{
		field = FindArrayStorageField(ownerType, symbol);
		property = FindProperty(ownerType, symbol);
		if (field != null)
		{
			property = null;
			return true;
		}
		if (property != null)
		{
			field = null;
			return true;
		}
		if (!LooksLikeHeroSoundTileCodeArraySymbol(symbol.Id))
			return false;
		return TryFindHeroSoundArrayAccessor(ownerType, instanceOnly: true, out field, out property);
	}

	/// <summary>
	/// Resolves a real array storage field. Skips Il2CppInterop NativeFieldInfoPtr_* IntPtr metadata,
	/// which FindField can otherwise return for symbols that also name the managed property.
	/// </summary>
	private static FieldInfo FindArrayStorageField(Type ownerType, GameSymbols.FieldSymbol symbol)
	{
		var field = FindField(ownerType, symbol);
		return IsIl2CppNativeFieldInfoMetadata(field) ? null : field;
	}

	private static bool IsIl2CppNativeFieldInfoMetadata(FieldInfo field)
	{
		if (field == null)
			return false;
		if (field.FieldType == typeof(IntPtr) || field.FieldType == typeof(UIntPtr))
			return true;
		return field.Name.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal);
	}

	private static IEnumerable<string> EnumerateFieldSymbolNames(GameSymbols.FieldSymbol symbol)
	{
		if (!string.IsNullOrWhiteSpace(symbol.FieldName))
			yield return symbol.FieldName;
		if (!string.IsNullOrWhiteSpace(symbol.NativeFieldInfoName)
		    && !string.Equals(symbol.NativeFieldInfoName, symbol.FieldName, StringComparison.Ordinal))
			yield return symbol.NativeFieldInfoName;
	}

	private static bool LooksLikeHeroSoundTileCodeArraySymbol(string symbolId)
	{
		return !string.IsNullOrWhiteSpace(symbolId)
		       && symbolId.IndexOf("terrain.sound.heroBiome", StringComparison.Ordinal) >= 0;
	}

	private static bool HeroBiomeLookupStorageCoversTile(object heroSoundInstance, Type heroType, int tileCode)
	{
		foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeStaticArrays)
		{
			if (TryReadStaticArraySlotOwner(heroType, symbol, out var current) && ArrayLikeLength(current) > tileCode)
				return true;
		}
		foreach (var symbol in GameSymbols.TerrainSound.HeroBiomeInstanceArrays)
		{
			if (TryReadInstanceArraySlotOwner(heroSoundInstance, heroType, symbol, out var current) && ArrayLikeLength(current) > tileCode)
				return true;
		}
		return false;
	}

	private static bool TryReadStaticArraySlotOwner(Type ownerType, GameSymbols.FieldSymbol symbol, out object current)
	{
		current = null;
		if (ownerType == null || !TryResolveStaticArrayAccessor(ownerType, symbol, out var field, out var property))
			return false;
		try
		{
			current = field != null ? field.GetValue(null) : property.GetValue(null);
			return current != null;
		}
		catch
		{
			current = null;
			return false;
		}
	}

	private static bool TryReadInstanceArraySlotOwner(object instance, Type ownerType, GameSymbols.FieldSymbol symbol, out object current)
	{
		current = null;
		if (instance == null || ownerType == null || !TryResolveArrayAccessor(ownerType, symbol, out var field, out var property))
			return false;
		try
		{
			current = field != null ? field.GetValue(instance) : property.GetValue(instance);
			return current != null;
		}
		catch
		{
			current = null;
			return false;
		}
	}

	private static int ArrayLikeLength(object current)
	{
		if (current is Array managed)
			return managed.Length;
		var lengthProp = current?.GetType().GetProperty("Length", BindingFlags.Public | BindingFlags.Instance);
		if (lengthProp == null)
			return -1;
		try
		{
			return Convert.ToInt32(lengthProp.GetValue(current));
		}
		catch
		{
			return -1;
		}
	}

	private static bool TryFindHeroSoundArrayAccessor(Type ownerType, bool instanceOnly, out FieldInfo field, out PropertyInfo property)
	{
		field = null;
		property = null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var t = ownerType; t != null; t = t.BaseType)
		{
			foreach (var candidate in t.GetProperties(flags))
			{
				if (instanceOnly && (candidate.GetMethod == null || candidate.GetMethod.IsStatic))
					continue;
				if (candidate.GetIndexParameters().Length != 0 || !candidate.CanRead || !candidate.CanWrite)
					continue;
				if (!LooksLikeHeroSoundTileCodeArrayType(candidate.PropertyType))
					continue;
				property = candidate;
				return true;
			}
			foreach (var candidate in t.GetFields(flags))
			{
				if (instanceOnly && candidate.IsStatic)
					continue;
				if (!LooksLikeHeroSoundTileCodeArrayType(candidate.FieldType))
					continue;
				field = candidate;
				return true;
			}
		}
		return false;
	}

	private static bool LooksLikeHeroSoundTileCodeArrayType(Type type)
	{
		if (type == null)
			return false;
		var name = type.FullName ?? type.Name;
		return name.IndexOf("EHeroSoundType", StringComparison.Ordinal) >= 0
		       && name.IndexOf("Array", StringComparison.Ordinal) >= 0;
	}

	private static PropertyInfo FindProperty(Type ownerType, GameSymbols.FieldSymbol symbol)
	{
		return FindProperty(ownerType, symbol.FieldName);
	}

	private static PropertyInfo FindProperty(Type ownerType, string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = ownerType; t != null; t = t.BaseType)
		{
			var property = t.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0 && property.CanRead)
				return property;
		}
		return null;
	}

	private static void InvokeRendererNoArg(object renderer, Type rendererType, GameSymbols.MethodSymbol symbol)
	{
		var method = GameMember.FindFirstMethod(rendererType, typeof(void), Type.EmptyTypes, symbol);
		if (method == null)
			throw new MissingMethodException("Could not resolve " + symbol.Id + " for custom biome registration.");
		try
		{
			method.Invoke(renderer, Array.Empty<object>());
		}
		catch (TargetInvocationException ex)
		{
			throw new InvalidOperationException("Custom biome registration failed while invoking " + symbol.Id + ".", ex.InnerException ?? ex);
		}
	}

	private static bool RendererHasTileCode(object renderer, Type rendererType, int tileCode)
	{
		var materialLookup = FindMaterialLookupDictionary(renderer, rendererType);
		return materialLookup.Value != null && materialLookup.Value.ContainsKey(tileCode);
	}

	private static string DescribeRendererDictionaries(object renderer, Type rendererType)
	{
		return string.Join(
			"; ",
			FindRendererLookupDictionaries(renderer, rendererType)
				.Select(DescribeRendererDictionary)
				.ToArray());
	}

	private static string DescribeRendererDictionary(RendererLookupDictionary dictionary)
	{
		var keys = Definitions
			.SelectMany(definition => new[] { definition.MaterialDonorTileCode, definition.TileCode })
			.Distinct()
			.ToArray();
		var parts = keys
			.Select(key => dictionary.Value.ContainsKey(key) ? key + "->" + dictionary.Value[key] : key + "->missing")
			.ToArray();
		return dictionary.Name + "[" + dictionary.Source + ",count=" + dictionary.Value.Count + "," + string.Join(",", parts) + "]";
	}

	private static RendererLookupDictionary[] FindRendererLookupDictionaries(object renderer, Type rendererType)
	{
		var dictionaries = new List<RendererLookupDictionary>();
		foreach (var field in FindRendererLookupFields(rendererType))
		{
			if (TryGetDictionary(renderer, field, out var dictionary))
				dictionaries.Add(new RendererLookupDictionary(field.Name, "managed", dictionary));
		}

		foreach (var property in FindRendererLookupProperties(rendererType))
		{
			if (dictionaries.Any(existing => string.Equals(existing.Name, property.Name, StringComparison.Ordinal)))
				continue;
			if (TryGetDictionary(renderer, property, out var dictionary))
				dictionaries.Add(new RendererLookupDictionary(property.Name, "managed-property", dictionary));
		}

		var typeKey = rendererType?.FullName ?? "?";
		IEnumerable<GameSymbols.FieldSymbol> symbolsToProbe = GameSymbols.TerrainMaterial.RendererMaterialLookups;
		if (ResolvedNativeLookupSymbolsByType.TryGetValue(typeKey, out var resolved)
		    && resolved != null
		    && resolved.Count > 0)
			symbolsToProbe = resolved;

		foreach (var symbol in symbolsToProbe)
		{
			var symbolNames = new[]
			{
				symbol.FieldName,
				symbol.NativeFieldInfoName?.Replace("NativeFieldInfoPtr_", string.Empty)
			};
			if (symbolNames.Any(name => !string.IsNullOrWhiteSpace(name)
			                            && dictionaries.Any(existing => string.Equals(existing.Name, name, StringComparison.Ordinal))))
				continue;
			if (TryGetNativeDictionary(renderer, rendererType, symbol, out var dictionary))
			{
				var name = symbol.FieldName
				           ?? symbol.NativeFieldInfoName?.Replace("NativeFieldInfoPtr_", string.Empty)
				           ?? "unknown";
				dictionaries.Add(new RendererLookupDictionary(name, "native", dictionary));
				RememberResolvedNativeLookupSymbol(typeKey, symbol);
			}
		}
		return dictionaries.ToArray();
	}

	private static void RememberResolvedNativeLookupSymbol(string typeKey, GameSymbols.FieldSymbol symbol)
	{
		if (string.IsNullOrEmpty(typeKey))
			return;
		if (!ResolvedNativeLookupSymbolsByType.TryGetValue(typeKey, out var list) || list == null)
		{
			list = new List<GameSymbols.FieldSymbol>();
			ResolvedNativeLookupSymbolsByType[typeKey] = list;
		}
		for (var i = 0; i < list.Count; i++)
		{
			var existing = list[i];
			if (string.Equals(existing.FieldName, symbol.FieldName, StringComparison.Ordinal)
			    && string.Equals(existing.NativeFieldInfoName, symbol.NativeFieldInfoName, StringComparison.Ordinal))
				return;
		}
		list.Add(symbol);
	}

	private static FieldInfo[] FindRendererLookupFields(Type rendererType)
	{
		if (rendererType == null)
			return Array.Empty<FieldInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		var names = new HashSet<string>(
			GameSymbols.TerrainMaterial.RendererMaterialLookups
				.SelectMany(symbol => new[] { symbol.FieldName, symbol.NativeFieldInfoName?.Replace("NativeFieldInfoPtr_", string.Empty) })
				.Where(name => !string.IsNullOrWhiteSpace(name)),
			StringComparer.Ordinal);
		try
		{
			return rendererType.GetFields(flags)
				.Where(field => names.Contains(field.Name))
				.ToArray();
		}
		catch
		{
			return Array.Empty<FieldInfo>();
		}
	}

	private static PropertyInfo[] FindRendererLookupProperties(Type rendererType)
	{
		if (rendererType == null)
			return Array.Empty<PropertyInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		var names = new HashSet<string>(
			GameSymbols.TerrainMaterial.RendererMaterialLookups
				.SelectMany(symbol => new[] { symbol.FieldName, symbol.NativeFieldInfoName?.Replace("NativeFieldInfoPtr_", string.Empty) })
				.Where(name => !string.IsNullOrWhiteSpace(name)),
			StringComparer.Ordinal);
		try
		{
			return rendererType.GetProperties(flags)
				.Where(property => property.GetIndexParameters().Length == 0 && names.Contains(property.Name))
				.ToArray();
		}
		catch
		{
			return Array.Empty<PropertyInfo>();
		}
	}

	private static bool TryGetDictionary(object renderer, FieldInfo field, out Il2CppIntDictionary dictionary)
	{
		dictionary = null;
		if (renderer == null || field == null)
			return false;
		try
		{
			dictionary = field.GetValue(renderer) as Il2CppIntDictionary;
			return dictionary != null;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Swamp Autumn tint proof could not inspect renderer dictionary " + field.Name + ": " + ex.Message);
			return false;
		}
	}

	private static bool TryGetDictionary(object renderer, PropertyInfo property, out Il2CppIntDictionary dictionary)
	{
		dictionary = null;
		if (renderer == null || property == null)
			return false;
		try
		{
			dictionary = property.GetValue(renderer) as Il2CppIntDictionary;
			return dictionary != null;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Swamp Autumn tint proof could not inspect renderer dictionary property " + property.Name + ": " + ex.Message);
			return false;
		}
	}

	private static bool TryGetNativeDictionary(object renderer, Type rendererType, GameSymbols.FieldSymbol symbol, out Il2CppIntDictionary dictionary)
	{
		dictionary = null;
		if (renderer is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;
		var classPtr = GetRendererClassPtr(rendererType);
		if (classPtr == IntPtr.Zero)
			return false;
		var failKey = (rendererType?.FullName ?? "?") + "::" + (symbol.FieldName ?? symbol.NativeFieldInfoName ?? "?");
		if (FailedNativeLookupKeys.Contains(failKey))
			return false;
		try
		{
			var field = TryGetGeneratedNativeFieldInfoPtr(rendererType, symbol.NativeFieldInfoName)
			            ?? IL2CPP.GetIl2CppField(classPtr, symbol.FieldName);
			if (field == IntPtr.Zero)
			{
				FailedNativeLookupKeys.Add(failKey);
				return false;
			}
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(field)));
			if (valuePtr == IntPtr.Zero)
				return false;
			dictionary = Il2CppObjectPool.Get<Il2CppIntDictionary>(valuePtr);
			return dictionary != null;
		}
		catch (Exception ex)
		{
			FailedNativeLookupKeys.Add(failKey);
			_log?.LogWarning("HoMM3 Swamp Autumn tint proof could not inspect native renderer dictionary " + symbol.FieldName + ": " + ex.Message);
			return false;
		}
	}

	private static IntPtr GetRendererClassPtr(Type rendererType)
	{
		try
		{
			var field = rendererType?.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null && field.FieldType == typeof(IntPtr))
				return (IntPtr)field.GetValue(null);
		}
		catch
		{
		}
		return IntPtr.Zero;
	}

	private static IntPtr? TryGetGeneratedNativeFieldInfoPtr(Type managedType, string fieldInfoName)
	{
		if (managedType == null || string.IsNullOrEmpty(fieldInfoName))
			return null;
		try
		{
			var field = managedType.GetField(fieldInfoName, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field == null || field.FieldType != typeof(IntPtr))
				return null;
			var value = (IntPtr)field.GetValue(null);
			return value == IntPtr.Zero ? null : value;
		}
		catch
		{
			return null;
		}
	}

	private static string DescribeRendererType(object renderer, Type rendererType)
	{
		var pointer = renderer is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero
			? "@0x" + il2Cpp.Pointer.ToString("x")
			: string.Empty;
		return (rendererType?.FullName ?? "(null)") + pointer + " classPtr=0x" + GetRendererClassPtr(rendererType).ToString("x");
	}

	private static string DescribeVisibleRendererFields(Type rendererType)
	{
		if (rendererType == null)
			return "(null)";
		try
		{
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
			var fields = rendererType.GetFields(flags)
				.Take(32)
				.Select(field => field.Name + ":" + field.FieldType.Name)
				.ToArray();
			return fields.Length == 0 ? "(none)" : string.Join(",", fields);
		}
		catch (Exception ex)
		{
			return "(unreadable:" + ex.GetType().Name + ")";
		}
	}

	private static SoTerrainMaterial.Biome FindBiome(List<SoTerrainMaterial.Biome> biomes, string name, int tileCode)
	{
		foreach (var biome in biomes)
		{
			if (biome == null)
				continue;
			if (biome.tileCode == tileCode || string.Equals(biome.name, name, StringComparison.OrdinalIgnoreCase))
				return biome;
		}
		return null;
	}

	private static SoTerrainMaterial.Biome CloneBiome(CustomBiomeDefinition definition, SoTerrainMaterial.Biome donor)
	{
		var custom = new SoTerrainMaterial.Biome
		{
			name = definition.Name,
			tileCode = definition.TileCode,
			splatmap = donor.splatmap,
			splatmapTiling = donor.splatmapTiling,
			blendDepth = donor.blendDepth,
			texturesCount = donor.texturesCount,
			mode = donor.mode,
			tiling0 = donor.tiling0,
			heightmapScale0 = donor.heightmapScale0,
			tiling1 = donor.tiling1,
			heightmapScale1 = donor.heightmapScale1,
			tiling2 = donor.tiling2,
			heightmapScale2 = donor.heightmapScale2,
			texture3 = donor.texture3,
			tiling3 = donor.tiling3,
			heightmapScale3 = donor.heightmapScale3
		};
		ApplyDefinition(custom, definition);
		return custom;
	}

	private static void ApplyDefinition(SoTerrainMaterial.Biome biome, CustomBiomeDefinition definition)
	{
		biome.name = definition.Name;
		biome.tileCode = definition.TileCode;
		ApplyTextures(biome, definition.TextureAssetDir, definition.TextureNamePrefix, definition.TextureFiles);
		ApplyMaterialParameters(biome, definition);
	}

	private static void ApplyMaterialParameters(SoTerrainMaterial.Biome biome, CustomBiomeDefinition definition)
	{
		if (biome == null || definition == null)
			return;
		if (!string.IsNullOrWhiteSpace(definition.TexturesCount))
		{
			if (!Enum.TryParse<SoTerrainMaterial.Biome.TexturesCount>(definition.TexturesCount, true, out var texturesCount))
				throw new InvalidOperationException("Custom biome definition '" + definition.Id + "' has invalid texturesCount '" + definition.TexturesCount + "'.");
			biome.texturesCount = texturesCount;
		}
		if (!string.IsNullOrWhiteSpace(definition.Mode))
		{
			if (!Enum.TryParse<SoTerrainMaterial.Biome.Mode>(definition.Mode, true, out var mode))
				throw new InvalidOperationException("Custom biome definition '" + definition.Id + "' has invalid mode '" + definition.Mode + "'.");
			biome.mode = mode;
		}
		if (definition.BlendDepth.HasValue)
			biome.blendDepth = definition.BlendDepth.Value;
		if (definition.Tiling0.HasValue)
			biome.tiling0 = definition.Tiling0.Value;
		if (definition.HeightmapScale0.HasValue)
			biome.heightmapScale0 = definition.HeightmapScale0.Value;
		if (definition.Tiling1.HasValue)
			biome.tiling1 = definition.Tiling1.Value;
		if (definition.HeightmapScale1.HasValue)
			biome.heightmapScale1 = definition.HeightmapScale1.Value;
		if (definition.Tiling2.HasValue)
			biome.tiling2 = definition.Tiling2.Value;
		if (definition.HeightmapScale2.HasValue)
			biome.heightmapScale2 = definition.HeightmapScale2.Value;
	}

	private static void ApplyTextures(SoTerrainMaterial.Biome biome, string assetDir, string namePrefix, string[] files)
	{
		if (biome == null || string.IsNullOrWhiteSpace(assetDir))
			return;
		var textures = EnsureReplacementTextures(assetDir, namePrefix, files);
		if (textures.Length > 0)
			biome.texture0 = textures[0];
		if (textures.Length > 1)
			biome.texture1 = textures[1];
		if (textures.Length > 2)
			biome.texture2 = textures[2];
	}

	private static Texture2D[] EnsureReplacementTextures(string assetDir, string namePrefix, string[] files)
	{
		var cacheKey = assetDir + "|" + namePrefix + "|" + string.Join("|", files ?? Array.Empty<string>());
		if (TextureCache.TryGetValue(cacheKey, out var cached))
			return cached;
		var textures = new Texture2D[files.Length];
		for (var i = 0; i < files.Length; i++)
			textures[i] = LoadTexture(assetDir, files[i], namePrefix);
		TextureCache[cacheKey] = textures;
		return textures;
	}

	private static Texture2D LoadTexture(string assetDir, string fileName, string namePrefix)
	{
		var path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", assetDir, fileName);
		if (!File.Exists(path))
			throw new FileNotFoundException("Missing custom biome texture.", path);

		var texture = new Texture2D(2, 2, TextureFormat.RGBA32, true)
		{
			name = "HOMM3_" + namePrefix + "_" + Path.GetFileNameWithoutExtension(fileName),
			filterMode = FilterMode.Bilinear,
			wrapMode = TextureWrapMode.Repeat
		};
		if (!TryLoadTextureImage(texture, File.ReadAllBytes(path)))
		{
			UnityEngine.Object.Destroy(texture);
			throw new InvalidOperationException("Failed to load custom biome texture: " + path);
		}
		texture.Apply(true, false);
		_log?.LogWarning(
			"HoMM3 custom biome registration loaded terrain texture "
			+ texture.name
			+ " from "
			+ path
			+ " ("
			+ texture.width
			+ "x"
			+ texture.height
			+ ").");
		return texture;
	}

	internal static bool TryLoadTextureImage(Texture2D texture, byte[] bytes)
	{
		if (!texture || bytes == null || bytes.Length == 0)
			return false;
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.Length);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		return ImageConversion.LoadImage(texture, il2cppBytes);
	}

	internal sealed class CustomBiomeDefinition
	{
		internal string Id;
		internal string Name;
		internal int TileCode;
		internal string MaterialDonorName;
		internal int MaterialDonorTileCode;
		internal int SoundDonorTileCode;
		internal bool MaterialAliasOnly;
		internal string TextureAssetDir;
		internal string MarkerBiomeName;
		internal int MarkerTileCode;
		internal string MarkerTextureAssetDir;
		internal string[] TextureFiles;
		internal string TexturesCount;
		internal string Mode;
		internal float? BlendDepth;
		internal float? Tiling0;
		internal float? HeightmapScale0;
		internal float? Tiling1;
		internal float? HeightmapScale1;
		internal float? Tiling2;
		internal float? HeightmapScale2;

		internal string TextureNamePrefix => string.IsNullOrWhiteSpace(Id) ? Name.ToLowerInvariant() : Id;
		internal string MarkerTextureNamePrefix => TextureNamePrefix + "_donor_marker";

		internal void Validate(string sourcePath)
		{
			if (string.IsNullOrWhiteSpace(Id))
				throw new InvalidOperationException(sourcePath + ": custom biome definition is missing id.");
			if (string.IsNullOrWhiteSpace(Name))
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' is missing name.");
			if (TileCode < 0)
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' has invalid tileCode.");
			if (string.IsNullOrWhiteSpace(MaterialDonorName) && MaterialDonorTileCode < 0)
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' needs materialDonorName or materialDonorTileCode.");
			if (SoundDonorTileCode < 0)
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' has invalid soundDonorTileCode.");
			if (!MaterialAliasOnly && string.IsNullOrWhiteSpace(TextureAssetDir))
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' is missing textureAssetDir.");
			if (!MaterialAliasOnly && (TextureFiles == null || TextureFiles.Length == 0))
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' is missing textureFiles.");
			if (TextureFiles != null && TextureFiles.Length > 3)
				throw new InvalidOperationException(sourcePath + ": custom biome definition '" + Id + "' has more than three textureFiles; extend the material copier deliberately before using texture3.");
			if (MarkerTileCode < 0)
				MarkerTileCode = MaterialDonorTileCode;
			if (string.IsNullOrWhiteSpace(MarkerBiomeName))
				MarkerBiomeName = MaterialDonorName;
		}
	}

	private readonly struct RendererLookupDictionary
	{
		internal RendererLookupDictionary(string name, string source, Il2CppIntDictionary value)
		{
			Name = name;
			Source = source;
			Value = value;
		}

		internal string Name { get; }
		internal string Source { get; }
		internal Il2CppIntDictionary Value { get; }
	}
}
