using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

/// <summary>
/// Live fix: early PropCity can parent wrong-city billboard/mesh markers directly under
/// Section Root. Durable city children later get the correct art, but the stale section
/// markers stay visible (Tower showing Conflux capitol, etc.). Destroy those leftovers.
/// </summary>
public static class TowerConfluxTownMarkerSwapFix20260803
{
	private const string BillboardPrefix = "homm3_custom_city_billboard_";
	private const string MeshPrefix = "homm3_custom_city_mesh_";

	public static string Run(string requestJson)
	{
		try
		{
			var destroyed = new List<string>();
			var kept = new List<string>();
			var all = Resources.FindObjectsOfTypeAll<GameObject>();
			var markers = new List<Transform>();
			for (var i = 0; i < all.Length; i++)
			{
				var go = all[i];
				if (!go || string.IsNullOrEmpty(go.name))
					continue;
				if (!go.name.StartsWith(BillboardPrefix, StringComparison.Ordinal)
				    && !go.name.StartsWith(MeshPrefix, StringComparison.Ordinal))
					continue;
				if (!go.scene.IsValid() || !go.scene.isLoaded)
					continue;
				markers.Add(go.transform);
			}

			for (var i = 0; i < markers.Count; i++)
			{
				var marker = markers[i];
				if (!marker || !marker.gameObject)
					continue;
				var path = BuildPath(marker);
				var reason = ClassifyStale(marker);
				if (reason == null)
				{
					kept.Add(path);
					continue;
				}
				marker.gameObject.SetActive(false);
				UnityEngine.Object.Destroy(marker.gameObject);
				destroyed.Add(path + " [" + reason + "]");
			}

			var sb = new StringBuilder();
			sb.Append("{\"ok\":true");
			sb.Append(",\"scanned\":").Append(markers.Count.ToString(CultureInfo.InvariantCulture));
			sb.Append(",\"destroyed\":").Append(destroyed.Count.ToString(CultureInfo.InvariantCulture));
			sb.Append(",\"kept\":").Append(kept.Count.ToString(CultureInfo.InvariantCulture));
			sb.Append(",\"destroyedPaths\":[");
			for (var i = 0; i < destroyed.Count; i++)
			{
				if (i > 0) sb.Append(',');
				sb.Append(Json(destroyed[i]));
			}
			sb.Append("],\"keptPaths\":[");
			for (var i = 0; i < kept.Count; i++)
			{
				if (i > 0) sb.Append(',');
				sb.Append(Json(kept[i]));
			}
			sb.Append("],\"note\":\"volatile live cleanup only; source soft-skip + section cleanup still needed on next restart\"}");
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":" + Json(ex.GetType().Name + ": " + ex.Message) + "}";
		}
	}

	/// <summary>Returns stale reason, or null if marker should stay.</summary>
	private static string ClassifyStale(Transform marker)
	{
		if (!marker || !marker.parent)
			return "no-parent";

		var markerCitySid = ExtractCitySid(marker.name);
		if (string.IsNullOrEmpty(markerCitySid))
			return "bad-marker-name";

		var parent = marker.parent;
		var parentName = parent.name ?? string.Empty;

		// Early PropCity paints markers directly onto Section Root. Durable cities own
		// markers under homm3_*_city. Any section-direct marker is leftover.
		if (parentName.StartsWith("Section Root:", StringComparison.OrdinalIgnoreCase))
			return "section-direct-prop-city-leftover";

		// Marker under a durable city root must match that city SID.
		if (LooksLikeCityRoot(parentName))
		{
			if (!CityNamesMatch(parentName, markerCitySid))
				return "foreign-marker-under-city-root parent=" + parentName;
			return null;
		}

		// Marker under city-spawner / random-city is also early/transient.
		if (string.Equals(parentName, "city-spawner", StringComparison.OrdinalIgnoreCase)
		    || string.Equals(parentName, "random-city", StringComparison.OrdinalIgnoreCase))
			return "generic-city-parent-leftover";

		// Marker elsewhere under a section that already has a different live city root
		// matching this footprint: if section has exact city child and marker SID is absent,
		// destroy.
		var section = FindSectionRoot(marker);
		if (section != null)
		{
			var liveCities = ListDirectCityRoots(section);
			var markerLive = false;
			for (var i = 0; i < liveCities.Count; i++)
			{
				if (CityNamesMatch(liveCities[i], markerCitySid))
				{
					markerLive = true;
					break;
				}
			}
			if (liveCities.Count > 0 && !markerLive)
				return "section-has-other-live-cities-only";
		}

		return null;
	}

	private static string ExtractCitySid(string markerName)
	{
		if (string.IsNullOrEmpty(markerName))
			return null;
		if (markerName.StartsWith(BillboardPrefix, StringComparison.Ordinal))
			return markerName.Substring(BillboardPrefix.Length);
		if (markerName.StartsWith(MeshPrefix, StringComparison.Ordinal))
			return markerName.Substring(MeshPrefix.Length);
		return null;
	}

	private static bool LooksLikeCityRoot(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		if (name.StartsWith("homm3_", StringComparison.OrdinalIgnoreCase)
		    && name.IndexOf("_city", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (name.StartsWith("homm3_landon_", StringComparison.OrdinalIgnoreCase))
			return true;
		return false;
	}

	private static bool CityNamesMatch(string rootName, string citySid)
	{
		if (string.IsNullOrEmpty(rootName) || string.IsNullOrEmpty(citySid))
			return false;
		if (string.Equals(rootName, citySid, StringComparison.OrdinalIgnoreCase))
			return true;
		// land-on aliases: homm3_landon_tower_city <-> homm3_tower_city
		if (rootName.StartsWith("homm3_landon_", StringComparison.OrdinalIgnoreCase))
		{
			var stripped = "homm3_" + rootName.Substring("homm3_landon_".Length);
			if (string.Equals(stripped, citySid, StringComparison.OrdinalIgnoreCase))
				return true;
		}
		return rootName.IndexOf(citySid, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static Transform FindSectionRoot(Transform t)
	{
		for (var cur = t; cur != null; cur = cur.parent)
		{
			if ((cur.name ?? string.Empty).StartsWith("Section Root:", StringComparison.OrdinalIgnoreCase))
				return cur;
		}
		return null;
	}

	private static List<string> ListDirectCityRoots(Transform section)
	{
		var list = new List<string>();
		if (!section)
			return list;
		for (var i = 0; i < section.childCount; i++)
		{
			var child = section.GetChild(i);
			if (!child || !LooksLikeCityRoot(child.name))
				continue;
			list.Add(child.name);
		}
		return list;
	}

	private static string BuildPath(Transform t)
	{
		if (!t)
			return "";
		var path = t.name;
		var cur = t.parent;
		while (cur != null)
		{
			path = cur.name + "/" + path;
			cur = cur.parent;
		}
		return path;
	}

	private static string Json(string value)
	{
		if (value == null)
			return "null";
		return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}
}
