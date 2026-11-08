using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.World;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Extends <see cref="SoMinimapConfig.bioms"/> with one tiling texture per custom tile code,
/// using the first terrain texture file declared in custom_biomes.json.
/// </summary>
internal static class Homm3CustomBiomeMinimapHook
{
	private const int MinimapTextureSize = 64;

	private static ManualLogSource _log;
	private static readonly Dictionary<string, Texture2D> _textureCache = new(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<int> _loggedBoundsProbeMapDataIds = new();
	private static readonly HashSet<int> _loggedRectClampMapDataIds = new();
	/// <summary>SoMinimapConfig instance id → last sealed bioms length. Re-seal when a later map needs more slots.</summary>
	private static readonly Dictionary<int, int> _sealedBiomsLengthByConfigId = new();
	private static bool _registered;
	private static bool _applying;

	internal static void Register(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony is required for custom biome minimap registration.");
		_log = log;

		PrewarmMinimapTextures();

		var rendererType = ResolveMinimapRendererType();
		if (rendererType == null)
			throw new MissingMethodException("Could not resolve minimap renderer type for custom biome minimap registration.");

		var renderMethods = ResolveMinimapRenderMethods(rendererType);
		if (renderMethods.Length == 0)
			throw new MissingMethodException("Could not resolve exact minimap render-map-data method for custom biome minimap registration.");

		var renderPrefix = new HarmonyMethod(typeof(Homm3CustomBiomeMinimapHook), nameof(PrefixMinimapRender));
		foreach (var renderMethod in renderMethods)
			harmony.Patch(renderMethod, prefix: renderPrefix);
		_registered = true;
		_log?.LogWarning(
			"HoMM3 custom biome minimap registration patched render-map-data surface(s) "
			+ string.Join(", ", renderMethods.Select(method => method.Name))
			+ " on "
			+ rendererType.FullName
			+ ".");
	}

	private static MethodInfo[] ResolveMinimapRenderMethods(Type rendererType)
	{
		var current = FindNamedMinimapRenderMethods(rendererType, GameSymbols.Minimap.RendererRenderMapData);
		return current.Length > 0 ? current : Array.Empty<MethodInfo>();
	}

	private static MethodInfo[] FindNamedMinimapRenderMethods(Type rendererType, GameSymbols.MethodSymbol symbol)
	{
		if (rendererType == null || symbol.NameHints == null || symbol.NameHints.Length == 0)
			return Array.Empty<MethodInfo>();
		var hints = new HashSet<string>(
			symbol.NameHints.Where(name => !string.IsNullOrWhiteSpace(name)),
			StringComparer.Ordinal);
		if (hints.Count == 0)
			return Array.Empty<MethodInfo>();
		return FindMinimapRenderShapeMethods(rendererType)
			.Where(method => hints.Contains(method.Name))
			.OrderBy(method => Array.IndexOf(symbol.NameHints, method.Name))
			.Take(1)
			.ToArray();
	}

	private static IEnumerable<MethodInfo> FindMinimapRenderShapeMethods(Type rendererType)
	{
		if (rendererType == null)
			yield break;
		MethodInfo[] methods;
		try
		{
			methods = rendererType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
		}
		catch
		{
			yield break;
		}
		foreach (var method in methods)
		{
			if (method == null || method.ReturnType != typeof(void))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 5)
				continue;
			if (!TypesEquivalent(ps[0].ParameterType, typeof(RenderTexture)))
				continue;
			if (!TypesEquivalent(ps[2].ParameterType, typeof(RectInt)))
				continue;
			if (!TypesEquivalent(ps[3].ParameterType, typeof(SoMinimapConfig)))
				continue;
			if (ps[4].ParameterType != typeof(bool))
				continue;
			yield return method;
		}
	}

	private static bool TypesEquivalent(Type actual, Type expected)
	{
		if (actual == null || expected == null)
			return false;
		if (actual == expected)
			return true;
		if (string.Equals(actual.FullName, expected.FullName, StringComparison.Ordinal))
			return true;
		return string.Equals(actual.Name, expected.Name, StringComparison.Ordinal)
		       && string.Equals(actual.Namespace, expected.Namespace, StringComparison.Ordinal);
	}

	private static Type ResolveMinimapRendererType()
	{
		return GameMember.FindTypeFromHints(
			GameSymbols.Minimap.RendererTypeId,
			GameSymbols.Minimap.RendererTypeHints,
			hint => GetHexType(hint));
	}

	private static Type GetHexType(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return null;
		var assembly = typeof(SoMinimapConfig).Assembly;
		return assembly.GetType(name)
		       ?? assembly.GetType("Hex.Render." + name)
		       ?? assembly.GetType("Hex.Map." + name)
		       ?? assembly.GetType("Hex.Session.World." + name);
	}

	private static void PrewarmMinimapTextures()
	{
		var definitions = Homm3SwampAutumnTintProof.EnabledBiomeDefinitions;
		if (definitions == null || definitions.Length == 0)
			return;

		foreach (var definition in definitions)
		{
			if (definition.MaterialAliasOnly)
				continue;
			if (definition.TextureFiles == null || definition.TextureFiles.Length == 0 || string.IsNullOrWhiteSpace(definition.TextureAssetDir))
				continue;
			LoadMinimapTexture(definition, definition.TextureFiles[0]);
		}
	}

	// Harmony binds prefix parameters by name; deobf render-map-data uses (a, b, c, d, e).
	// RectInt must be ref so native bcv.klu sees the clamped walk window.
	private static bool PrefixMinimapRender(object a, object b, ref RectInt c, SoMinimapConfig d, bool e)
	{
		HandleMinimapConfig(b, d);
		// Native builds RectInt from MapView sectors (16 tiles). Exact-72 maps keep secSize=5
		// (80x80 window) while sizeX_/sizeZ_ are 72; without an intersect, bcv.klu indexes
		// past tilesMap/waterMap. Clamp before the original body runs.
		ClampRectToMapBounds(b, ref c);
		// Always probe once per MapData: native bcv.klu throws IndexOutOfRange without saying which array.
		LogBoundsProbeOnce(b, c, d);
		return true;
	}

	/// <summary>
	/// Intersect the minimap walk rect with MapData size so sector-aligned MapView overhang
	/// cannot index past tilesMap/waterMap. Logs once per MapData when a clip occurs.
	/// </summary>
	private static void ClampRectToMapBounds(object mapData, ref RectInt rect)
	{
		if (mapData == null)
			return;
		var sizeX = ReadIntMember(mapData, "sizeX_");
		var sizeZ = ReadIntMember(mapData, "sizeZ_");
		if (sizeX <= 0 || sizeZ <= 0)
			return;

		var original = rect;
		var xMin = Math.Max(rect.xMin, 0);
		var yMin = Math.Max(rect.yMin, 0);
		var xMaxExclusive = Math.Min(rect.xMin + Math.Max(rect.width, 0), sizeX);
		var yMaxExclusive = Math.Min(rect.yMin + Math.Max(rect.height, 0), sizeZ);
		if (xMaxExclusive < xMin)
			xMaxExclusive = xMin;
		if (yMaxExclusive < yMin)
			yMaxExclusive = yMin;

		rect = new RectInt(xMin, yMin, xMaxExclusive - xMin, yMaxExclusive - yMin);
		if (rect.xMin == original.xMin
		    && rect.yMin == original.yMin
		    && rect.width == original.width
		    && rect.height == original.height)
			return;

		var mapId = RuntimeHelpers.GetHashCode(mapData);
		if (!_loggedRectClampMapDataIds.Add(mapId))
			return;

		var mapSid = ReadMapSid(mapData);
		if (string.IsNullOrWhiteSpace(mapSid))
			mapSid = "unknown";
		_log?.LogWarning(
			"HoMM3 custom biome minimap RectInt clamp: mapSid="
			+ mapSid
			+ " size="
			+ sizeX
			+ "x"
			+ sizeZ
			+ " from=("
			+ original.xMin
			+ ","
			+ original.yMin
			+ ","
			+ original.width
			+ ","
			+ original.height
			+ ") to=("
			+ rect.xMin
			+ ","
			+ rect.yMin
			+ ","
			+ rect.width
			+ ","
			+ rect.height
			+ ")");
	}

	private static void HandleMinimapConfig(object mapData, SoMinimapConfig config)
	{
		if (ReferenceEquals(config, null))
			return;
		if (_applying)
			return;

		_applying = true;
		try
		{
			// Always seal bioms to cover every tile id present on this map. Custom biome
			// injection alone is gated too tightly: Homecoming water uses tiles 18-22 while
			// stock SoMinimapConfig.bioms is only length 7, and MapUsesCustomBiomeTile stays
			// false when the map has no swamp/void/etc custom definitions.
			EnsureApplied(config, mapData);
		}
		finally
		{
			_applying = false;
		}
	}

	/// <summary>
	/// Fail-closed diagnostic for bcv.klu IndexOutOfRange: native walks RectInt cells via
	/// node = y * sizeX_ + x into tilesMap/waterMap, and indexes bioms by array slot while
	/// matching BiomSettings.tileID. Log the first mismatch instead of guessing.
	/// </summary>
	private static void LogBoundsProbeOnce(object mapData, RectInt rect, SoMinimapConfig config)
	{
		if (mapData == null)
			return;
		var mapId = RuntimeHelpers.GetHashCode(mapData);
		if (!_loggedBoundsProbeMapDataIds.Add(mapId))
			return;

		try
		{
			var sizeX = ReadIntMember(mapData, "sizeX_");
			var sizeZ = ReadIntMember(mapData, "sizeZ_");
			var tiles = ReadMapTilesArray(mapData);
			var water = ReadMapArray(mapData, "waterMap");
			var tilesLen = ArrayLikeLength(tiles);
			var waterLen = ArrayLikeLength(water);
			var biomsLen = ReferenceEquals(config, null) || ReferenceEquals(config.bioms, null) ? -1 : config.bioms.Length;

			var minX = rect.xMin;
			var minZ = rect.yMin;
			var maxX = rect.xMin + Math.Max(rect.width, 0) - 1;
			var maxZ = rect.yMin + Math.Max(rect.height, 0) - 1;
			var maxNode = sizeX > 0 && rect.width > 0 && rect.height > 0
				? maxZ * sizeX + maxX
				: -1;
			var expectedCells = sizeX > 0 && sizeZ > 0 ? sizeX * sizeZ : -1;

			var maxTileInRect = -1;
			if (tiles != null && sizeX > 0 && rect.width > 0 && rect.height > 0)
			{
				for (var z = minZ; z <= maxZ; z++)
				{
					if (z < 0 || (sizeZ > 0 && z >= sizeZ))
						continue;
					for (var x = minX; x <= maxX; x++)
					{
						if (x < 0 || x >= sizeX)
							continue;
						var node = z * sizeX + x;
						if (node < 0 || node >= tilesLen)
							continue;
						maxTileInRect = Math.Max(maxTileInRect, ReadArrayByte(tiles, node));
					}
				}
			}

			var mapSid = ReadMapSid(mapData);
			if (string.IsNullOrWhiteSpace(mapSid))
				mapSid = "unknown";

			var issues = new List<string>();
			if (sizeX <= 0 || sizeZ <= 0)
				issues.Add("sizeX_/sizeZ_ invalid");
			if (expectedCells > 0 && tilesLen >= 0 && tilesLen != expectedCells)
				issues.Add("tilesMap length " + tilesLen + " != sizeX_*sizeZ_ " + expectedCells);
			if (expectedCells > 0 && waterLen >= 0 && waterLen != expectedCells)
				issues.Add("waterMap length " + waterLen + " != sizeX_*sizeZ_ " + expectedCells);
			if (maxNode >= 0 && tilesLen >= 0 && maxNode >= tilesLen)
				issues.Add("RectInt max node " + maxNode + " >= tilesMap length " + tilesLen);
			if (maxNode >= 0 && waterLen >= 0 && maxNode >= waterLen)
				issues.Add("RectInt max node " + maxNode + " >= waterMap length " + waterLen);
			if (rect.xMin < 0 || rect.yMin < 0 || (sizeX > 0 && maxX >= sizeX) || (sizeZ > 0 && maxZ >= sizeZ))
				issues.Add("RectInt extends outside map bounds");
			if (maxTileInRect >= 0 && biomsLen >= 0 && maxTileInRect >= biomsLen)
				issues.Add("max tile in rect " + maxTileInRect + " >= bioms length " + biomsLen);

			var summary =
				"HoMM3 custom biome minimap bounds probe: mapSid="
				+ mapSid
				+ " size="
				+ sizeX
				+ "x"
				+ sizeZ
				+ " rect=("
				+ rect.xMin
				+ ","
				+ rect.yMin
				+ ","
				+ rect.width
				+ ","
				+ rect.height
				+ ") maxNode="
				+ maxNode
				+ " tilesLen="
				+ tilesLen
				+ " waterLen="
				+ waterLen
				+ " biomsLen="
				+ biomsLen
				+ " maxTileInRect="
				+ maxTileInRect;

			if (issues.Count > 0)
			{
				_log?.LogError(summary + " FAIL: " + string.Join("; ", issues));
				return;
			}

			_log?.LogWarning(summary + " OK");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 custom biome minimap bounds probe failed: " + ex);
		}
	}

	private static int ReadIntMember(object mapData, string name)
	{
		try
		{
			var type = mapData.GetType();
			var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null)
				return Convert.ToInt32(field.GetValue(mapData));
			var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (property != null && property.CanRead)
				return Convert.ToInt32(property.GetValue(mapData));
		}
		catch
		{
			// Probe only.
		}
		return -1;
	}

	private static string ReadMapSid(object mapData)
	{
		if (mapData == null)
			return null;
		try
		{
			foreach (var name in GameSymbols.HomecomingBoatTravel.MapDataFileNameMembers)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var type = mapData.GetType();
				var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null)
				{
					var value = field.GetValue(mapData) as string;
					if (!string.IsNullOrWhiteSpace(value))
						return value;
				}
				var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (property != null && property.CanRead)
				{
					var value = property.GetValue(mapData) as string;
					if (!string.IsNullOrWhiteSpace(value))
						return value;
				}
				if (name.StartsWith("get_", StringComparison.Ordinal))
				{
					var method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType == typeof(string))
					{
						var value = method.Invoke(mapData, null) as string;
						if (!string.IsNullOrWhiteSpace(value))
							return value;
					}
				}
			}
		}
		catch
		{
			// Probe only; unresolved identity becomes mapSid=unknown in the log line.
		}
		return null;
	}

	private static object ReadMapArray(object mapData, string name)
	{
		try
		{
			var type = mapData.GetType();
			var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null)
				return field.GetValue(mapData);
			var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return property != null && property.CanRead ? property.GetValue(mapData) : null;
		}
		catch
		{
			return null;
		}
	}

	private static int ArrayLikeLength(object array)
	{
		if (array == null)
			return -1;
		if (array is Array managed)
			return managed.Length;
		if (array is Il2CppStructArray<byte> bytes)
			return bytes.Length;
		try
		{
			var prop = array.GetType().GetProperty("Length", BindingFlags.Instance | BindingFlags.Public);
			if (prop != null && prop.CanRead)
				return Convert.ToInt32(prop.GetValue(array));
		}
		catch
		{
			// Probe only.
		}
		return -1;
	}

	private static int ReadArrayByte(object array, int index)
	{
		if (array is byte[] managedBytes)
			return managedBytes[index];
		if (array is Il2CppStructArray<byte> il2CppBytes)
			return il2CppBytes[index];
		if (array is Array boxed)
			return Convert.ToInt32(boxed.GetValue(index));
		return -1;
	}

	private static object ReadMapTilesArray(object mapData)
	{
		try
		{
			var type = mapData.GetType();
			var field = type.GetField("tilesMap", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null)
				return field.GetValue(mapData);
			var property = type.GetProperty("tilesMap", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return property != null && property.CanRead ? property.GetValue(mapData) : null;
		}
		catch
		{
			return null;
		}
	}
	internal static void EnsureApplied(SoMinimapConfig config)
	{
		EnsureApplied(config, mapData: null);
	}

	internal static void EnsureApplied(SoMinimapConfig config, object mapData)
	{
		if (ReferenceEquals(config, null))
			return;

		var definitions = Homm3SwampAutumnTintProof.EnabledBiomeDefinitions ?? Array.Empty<Homm3SwampAutumnTintProof.CustomBiomeDefinition>();
		try
		{
			var sourceBioms = config.bioms;
			var maxTileCode = -1;
			if (!ReferenceEquals(sourceBioms, null))
			{
				for (var i = 0; i < sourceBioms.Length; i++)
				{
					var biom = sourceBioms[i];
					if (ReferenceEquals(biom, null))
						continue;
					maxTileCode = Math.Max(maxTileCode, Math.Max(i, biom.tileID));
				}
			}
			foreach (var definition in definitions)
			{
				if (definition != null && definition.TileCode >= 0)
					maxTileCode = Math.Max(maxTileCode, definition.TileCode);
			}
			if (maxTileCode < 0)
				return;

			var requiredLength = maxTileCode + 1;
			var configId = config.GetInstanceID();
			// Fail-closed seal cache: skip full tilesMap scan once bioms+definitions
			// already satisfy the sealed length (Homecoming water tiles live in defs).
			if (_sealedBiomsLengthByConfigId.TryGetValue(configId, out var sealedLength)
			    && sealedLength >= requiredLength
			    && !ReferenceEquals(sourceBioms, null)
			    && sourceBioms.Length >= requiredLength)
				return;

			var mapMaxTile = MaxTileCodeInMap(mapData);
			if (mapMaxTile >= 0)
			{
				maxTileCode = Math.Max(maxTileCode, mapMaxTile);
				requiredLength = maxTileCode + 1;
			}
			if (maxTileCode < 0)
				return;

			if (_sealedBiomsLengthByConfigId.TryGetValue(configId, out sealedLength)
			    && sealedLength >= requiredLength
			    && !ReferenceEquals(sourceBioms, null)
			    && sourceBioms.Length >= requiredLength)
				return;

			var indexed = new SoMinimapConfig.BiomSettings[requiredLength];
			if (!ReferenceEquals(sourceBioms, null))
			{
				for (var i = 0; i < sourceBioms.Length; i++)
				{
					var biom = sourceBioms[i];
					if (ReferenceEquals(biom, null))
						continue;
					if (i >= 0 && i < indexed.Length && ReferenceEquals(indexed[i], null))
						indexed[i] = biom;
					if (biom.tileID >= 0 && biom.tileID < indexed.Length)
						indexed[biom.tileID] = biom;
				}
			}

			var added = 0;
			var addedTileCodes = new List<int>();
			foreach (var definition in definitions)
			{
				if (definition == null || definition.TileCode < 0 || definition.TileCode >= indexed.Length)
					continue;
				if (!ReferenceEquals(indexed[definition.TileCode], null))
					continue;

				if (definition.MaterialAliasOnly)
				{
					var donorTileCode = definition.MaterialDonorTileCode;
					if (donorTileCode < 0 || donorTileCode >= indexed.Length || ReferenceEquals(indexed[donorTileCode], null))
						donorTileCode = definition.SoundDonorTileCode;
					if (donorTileCode < 0 || donorTileCode >= indexed.Length)
						continue;
					var donorBiom = indexed[donorTileCode];
					if (ReferenceEquals(donorBiom, null) || ReferenceEquals(donorBiom.texture, null))
						continue;
					indexed[definition.TileCode] = new SoMinimapConfig.BiomSettings
					{
						tileID = definition.TileCode,
						texture = donorBiom.texture,
						textureScale = donorBiom.textureScale
					};
					addedTileCodes.Add(definition.TileCode);
					added++;
					continue;
				}

				if (definition.TextureFiles == null || definition.TextureFiles.Length == 0 || string.IsNullOrWhiteSpace(definition.TextureAssetDir))
					continue;

				var texture = LoadMinimapTexture(definition, definition.TextureFiles[0]);
				if (ReferenceEquals(texture, null))
					continue;

				var biom = new SoMinimapConfig.BiomSettings
				{
					tileID = definition.TileCode,
					texture = texture,
					textureScale = definition.MaterialDonorTileCode == 6 ? 2f : 1f
				};
				indexed[definition.TileCode] = biom;
				addedTileCodes.Add(definition.TileCode);
				added++;
			}

			// Prefer stock waterTexture for native display-water tile codes when sealing holes.
			Texture2D waterTexture = null;
			try { waterTexture = config.waterTexture; }
			catch { waterTexture = null; }
			if (!ReferenceEquals(waterTexture, null))
			{
				foreach (var waterTile in GameSymbols.HomecomingBoatTravel.RetiredGoldenEraWaterTileCodes)
				{
					if (waterTile < 0 || waterTile >= indexed.Length)
						continue;
					if (!ReferenceEquals(indexed[waterTile], null) && !ReferenceEquals(indexed[waterTile].texture, null))
						continue;
					indexed[waterTile] = new SoMinimapConfig.BiomSettings
					{
						tileID = waterTile,
						texture = waterTexture,
						textureScale = config.waterTextureScale > 0f ? config.waterTextureScale : 1f
					};
					if (!addedTileCodes.Contains(waterTile))
						addedTileCodes.Add(waterTile);
					added++;
				}
			}

			// Native bcv.klu indexes bioms by tile id and dereferences .texture with no null
			// check. Expanding to requiredLength leaves holes for unused ids (e.g. water 18-22
			// when Void forces length 24). Fill every slot with a real BiomSettings.
			SoMinimapConfig.BiomSettings fallback = null;
			for (var i = 0; i < indexed.Length; i++)
			{
				var biom = indexed[i];
				if (ReferenceEquals(biom, null) || ReferenceEquals(biom.texture, null))
					continue;
				fallback = biom;
				break;
			}
			if (ReferenceEquals(fallback, null))
			{
				_log?.LogError("HoMM3 custom biome minimap: cannot seal bioms array; no non-null donor texture.");
				return;
			}
			for (var i = 0; i < indexed.Length; i++)
			{
				var biom = indexed[i];
				if (!ReferenceEquals(biom, null) && !ReferenceEquals(biom.texture, null))
					continue;
				indexed[i] = new SoMinimapConfig.BiomSettings
				{
					tileID = i,
					texture = fallback.texture,
					textureScale = fallback.textureScale
				};
			}

			var extended = new Il2CppReferenceArray<SoMinimapConfig.BiomSettings>(indexed.Length);
			for (var i = 0; i < indexed.Length; i++)
				extended[i] = indexed[i];
			config.bioms = extended;
			_sealedBiomsLengthByConfigId[configId] = indexed.Length;
			_log?.LogWarning(
				"HoMM3 custom biome minimap: sealed SoMinimapConfig.bioms len="
				+ indexed.Length
				+ " mapMaxTile="
				+ mapMaxTile
				+ " customSlotsAdded="
				+ added
				+ " tileCodes="
				+ string.Join(", ", addedTileCodes)
				+ ".");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 custom biome minimap: failed to extend SoMinimapConfig.bioms: " + ex);
		}
	}

	private static int MaxTileCodeInMap(object mapData)
	{
		if (mapData == null)
			return -1;
		var tiles = ReadMapTilesArray(mapData);
		if (tiles == null)
			return -1;
		var maxTile = -1;
		if (tiles is byte[] managedBytes)
		{
			for (var i = 0; i < managedBytes.Length; i++)
				maxTile = Math.Max(maxTile, managedBytes[i]);
			return maxTile;
		}
		if (tiles is Il2CppStructArray<byte> il2CppBytes)
		{
			for (var i = 0; i < il2CppBytes.Length; i++)
				maxTile = Math.Max(maxTile, il2CppBytes[i]);
			return maxTile;
		}
		if (tiles is Array array)
		{
			for (var i = 0; i < array.Length; i++)
			{
				var value = array.GetValue(i);
				if (value != null)
					maxTile = Math.Max(maxTile, Convert.ToInt32(value));
			}
		}
		return maxTile;
	}

	private static Texture2D LoadMinimapTexture(Homm3SwampAutumnTintProof.CustomBiomeDefinition definition, string fileName)
	{
		var cacheKey = definition.TextureAssetDir + "|" + fileName;
		if (_textureCache.TryGetValue(cacheKey, out var cached) && !ReferenceEquals(cached, null))
			return cached;

		var path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", definition.TextureAssetDir, fileName);
		if (!File.Exists(path))
		{
			_log?.LogWarning("HoMM3 custom biome minimap: missing texture for " + definition.Name + ": " + path);
			return null;
		}

		var source = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		if (!Homm3SwampAutumnTintProof.TryLoadTextureImage(source, File.ReadAllBytes(path)))
		{
			UnityEngine.Object.Destroy(source);
			_log?.LogWarning("HoMM3 custom biome minimap: failed to decode texture for " + definition.Name + ": " + path);
			return null;
		}

		var texture = DownscaleForMinimap(source, definition.Id);
		UnityEngine.Object.Destroy(source);
		if (ReferenceEquals(texture, null))
			return null;

		_textureCache[cacheKey] = texture;
		_log?.LogInfo(
			"HoMM3 custom biome minimap: loaded "
			+ definition.Name
			+ " tileCode="
			+ definition.TileCode
			+ " from "
			+ fileName
			+ " ("
			+ texture.width
			+ "x"
			+ texture.height
			+ ").");
		return texture;
	}

	private static Texture2D DownscaleForMinimap(Texture2D source, string definitionId)
	{
		if (ReferenceEquals(source, null))
			return null;
		if (source.width <= MinimapTextureSize && source.height <= MinimapTextureSize)
		{
			source.filterMode = FilterMode.Point;
			source.wrapMode = TextureWrapMode.Repeat;
			source.Apply(false, false);
			return source;
		}

		var rt = RenderTexture.GetTemporary(MinimapTextureSize, MinimapTextureSize, 0, GraphicsFormat.R8G8B8A8_UNorm);
		rt.filterMode = FilterMode.Point;
		rt.wrapMode = TextureWrapMode.Repeat;
		var previous = RenderTexture.active;
		try
		{
			Graphics.Blit(source, rt);
			var texture = new Texture2D(MinimapTextureSize, MinimapTextureSize, TextureFormat.RGBA32, false)
			{
				name = "HOMM3_minimap_" + definitionId,
				filterMode = FilterMode.Point,
				wrapMode = TextureWrapMode.Repeat
			};
			RenderTexture.active = rt;
			texture.ReadPixels(new Rect(0, 0, MinimapTextureSize, MinimapTextureSize), 0, 0, false);
			texture.Apply(false, false);
			return texture;
		}
		finally
		{
			RenderTexture.active = previous;
			RenderTexture.ReleaseTemporary(rt);
		}
	}
}
