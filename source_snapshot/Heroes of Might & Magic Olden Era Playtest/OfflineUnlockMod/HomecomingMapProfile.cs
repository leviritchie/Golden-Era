using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using Hex.Map;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace OfflineUnlockMod;

internal sealed class HomecomingMapProfile
{
	internal const int ViewSectionSize = 16;

	internal static readonly string[] CampaignWaterLaneSuffixes =
	{
		"_raw_translation",
		"_layered_atlas",
		"_approach_cell",
	};

	internal static readonly HomecomingMapProfile SingleLayer = new(
		GameSymbols.HomecomingBoatTravel.MapSid,
		"single_layer",
		false,
		0,
		0,
		0,
		0,
		0,
		0);

	internal static readonly HomecomingMapProfile LayeredAtlas = new(
		GameSymbols.HomecomingBoatTravel.LayeredAtlasMapSid,
		"layered_atlas_surface",
		true,
		160,
		80,
		0,
		0,
		80,
		80);

	/// <summary>
	/// Parallel approach_cell atlas: same 160x80 side-by-side layout as layered atlas.
	/// Required so water traversal / boat visual / native water mesh bridges resolve this SID.
	/// </summary>
	internal static readonly HomecomingMapProfile ApproachCell = new(
		GameSymbols.HomecomingBoatTravel.ApproachCellMapSid,
		"approach_cell_surface",
		true,
		160,
		80,
		0,
		0,
		80,
		80);

	/// <summary>
	/// Parallel raw_translation atlas: same 160x80 side-by-side layout as layered atlas.
	/// Required so water traversal / boat visual / native water mesh bridges resolve this SID.
	/// </summary>
	internal static readonly HomecomingMapProfile RawTranslation = new(
		GameSymbols.HomecomingBoatTravel.RawTranslationMapSid,
		"raw_translation_surface",
		true,
		160,
		80,
		0,
		0,
		80,
		80);

	private static readonly Dictionary<string, HomecomingMapProfile> DynamicProfileCache = new();

	private HomecomingMapProfile(
		string mapSid,
		string id,
		bool restrictToSurfaceRectangle,
		int mapWidth,
		int mapHeight,
		int surfaceMinX,
		int surfaceMinY,
		int surfaceWidth,
		int surfaceHeight)
	{
		MapSid = mapSid;
		Id = id;
		RestrictToSurfaceRectangle = restrictToSurfaceRectangle;
		MapWidth = mapWidth;
		MapHeight = mapHeight;
		SurfaceMinX = surfaceMinX;
		SurfaceMinY = surfaceMinY;
		SurfaceWidth = surfaceWidth;
		SurfaceHeight = surfaceHeight;
	}

	internal string MapSid { get; }
	internal string Id { get; }
	internal bool RestrictToSurfaceRectangle { get; }
	internal int MapWidth { get; }
	internal int MapHeight { get; }
	internal int SurfaceMinX { get; }
	internal int SurfaceMinY { get; }
	internal int SurfaceWidth { get; }
	internal int SurfaceHeight { get; }

	internal bool ContainsRuntimeWaterNode(int node)
	{
		if (!RestrictToSurfaceRectangle)
			return true;
		if (node < 0 || MapWidth <= 0 || MapHeight <= 0 || node >= MapWidth * MapHeight)
			return false;
		var x = node % MapWidth;
		var y = node / MapWidth;
		return x >= SurfaceMinX
		       && x < SurfaceMinX + SurfaceWidth
		       && y >= SurfaceMinY
		       && y < SurfaceMinY + SurfaceHeight;
	}

	internal static bool TryResolve(string fileMapName, out HomecomingMapProfile profile)
	{
		if (string.Equals(fileMapName, SingleLayer.MapSid, StringComparison.Ordinal))
		{
			profile = SingleLayer;
			return true;
		}
		if (string.Equals(fileMapName, LayeredAtlas.MapSid, StringComparison.Ordinal))
		{
			profile = LayeredAtlas;
			return true;
		}
		if (string.Equals(fileMapName, ApproachCell.MapSid, StringComparison.Ordinal))
		{
			profile = ApproachCell;
			return true;
		}
		if (string.Equals(fileMapName, RawTranslation.MapSid, StringComparison.Ordinal))
		{
			profile = RawTranslation;
			return true;
		}
		profile = null;
		return false;
	}

	internal static bool TryResolve(string fileMapName, object mapData, out HomecomingMapProfile profile)
	{
		if (TryResolve(fileMapName, out profile))
			return true;
		if (!IsCampaignWaterLaneMapSid(fileMapName) || mapData == null)
		{
			profile = null;
			return false;
		}
		if (DynamicProfileCache.TryGetValue(fileMapName, out profile))
			return true;
		if (!TryBuildCampaignSurfaceProfile(fileMapName, mapData, out profile))
		{
			profile = null;
			return false;
		}
		DynamicProfileCache[fileMapName] = profile;
		return true;
	}

	internal static bool IsCampaignWaterLaneMapSid(string fileMapName)
	{
		if (string.IsNullOrWhiteSpace(fileMapName))
			return false;
		if (string.Equals(fileMapName, GameSymbols.HomecomingBoatTravel.Exact72ProbeMapSid, StringComparison.Ordinal))
			return false;
		if (!fileMapName.StartsWith("h3_", StringComparison.Ordinal))
			return false;
		foreach (var suffix in CampaignWaterLaneSuffixes)
		{
			if (fileMapName.EndsWith(suffix, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool TryBuildCampaignSurfaceProfile(string fileMapName, object mapData, out HomecomingMapProfile profile)
	{
		profile = null;
		if (!TryReadMapDimensions(mapData, out var mapWidth, out var mapHeight))
			return false;
		if (!TryCopyViews(mapData, out var views) || views == null || views.Length == 0)
			return false;

		MapViewData surfaceView = null;
		for (var i = 0; i < views.Length; i++)
		{
			var view = views[i];
			if (view != null && !view.isUnderground)
			{
				surfaceView = view;
				break;
			}
		}
		surfaceView ??= views[0];
		if (surfaceView == null || surfaceView.secSizeX <= 0 || surfaceView.secSizeZ <= 0)
			return false;

		var surfaceMinX = surfaceView.minSecX * ViewSectionSize;
		var surfaceMinY = surfaceView.minSecZ * ViewSectionSize;
		var surfaceWidth = surfaceView.secSizeX * ViewSectionSize;
		var surfaceHeight = surfaceView.secSizeZ * ViewSectionSize;
		if (surfaceMinX < 0 || surfaceMinY < 0 || surfaceWidth <= 0 || surfaceHeight <= 0)
			return false;
		if (surfaceMinX + surfaceWidth > mapWidth || surfaceMinY + surfaceHeight > mapHeight)
			return false;

		var profileId = fileMapName.EndsWith("_raw_translation", StringComparison.Ordinal)
			? "raw_translation_surface"
			: fileMapName.EndsWith("_layered_atlas", StringComparison.Ordinal)
				? "layered_atlas_surface"
				: "approach_cell_surface";
		profile = new HomecomingMapProfile(
			fileMapName,
			profileId,
			true,
			mapWidth,
			mapHeight,
			surfaceMinX,
			surfaceMinY,
			surfaceWidth,
			surfaceHeight);
		return true;
	}

	private static bool TryReadMapDimensions(object mapData, out int width, out int height)
	{
		width = 0;
		height = 0;
		if (!TryReadPositiveIntMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeXMembers, out width))
			return false;
		return TryReadPositiveIntMember(mapData, GameSymbols.HomecomingBoatTravel.MapDataSizeZMembers, out height);
	}

	private static bool TryReadPositiveIntMember(object value, string[] memberNames, out int result)
	{
		result = 0;
		if (value == null || memberNames == null)
			return false;
		foreach (var name in memberNames)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			object raw = null;
			try
			{
				var property = value.GetType().GetProperty(name);
				if (property != null)
					raw = property.GetValue(value);
				else
				{
					var field = value.GetType().GetField(name);
					if (field != null)
						raw = field.GetValue(value);
				}
			}
			catch
			{
				continue;
			}
			if (raw == null)
				continue;
			try
			{
				result = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
				return result > 0;
			}
			catch
			{
				continue;
			}
		}
		return false;
	}

	private static bool TryCopyViews(object mapData, out MapViewData[] views)
	{
		views = null;
		if (mapData == null)
			return false;
		var viewsValue = TryReadFirstMember(mapData, GameSymbols.HomecomingLayerViewToggle.MapDataViewsMembers);
		if (viewsValue == null)
			return false;
		if (viewsValue is MapViewData[] managedViews)
		{
			views = managedViews;
			return true;
		}
		if (viewsValue is Il2CppReferenceArray<MapViewData> il2CppViews)
		{
			views = new MapViewData[il2CppViews.Length];
			for (var i = 0; i < il2CppViews.Length; i++)
				views[i] = il2CppViews[i];
			return true;
		}
		if (viewsValue is IEnumerable enumerable && viewsValue is not string)
		{
			var list = new List<MapViewData>();
			foreach (var item in enumerable)
			{
				if (item is not MapViewData view)
					return false;
				list.Add(view);
			}
			views = list.ToArray();
			return true;
		}
		return false;
	}

	private static object TryReadFirstMember(object value, string[] memberNames)
	{
		if (value == null || memberNames == null)
			return null;
		foreach (var name in memberNames)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = value.GetType().GetProperty(name);
				if (property != null)
				{
					var propertyValue = property.GetValue(value);
					if (propertyValue != null)
						return propertyValue;
				}
				var field = value.GetType().GetField(name);
				if (field != null)
				{
					var fieldValue = field.GetValue(value);
					if (fieldValue != null)
						return fieldValue;
				}
			}
			catch
			{
				// keep scanning
			}
		}
		return null;
	}
}
