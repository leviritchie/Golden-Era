using System;
using System.Globalization;
using System.Text;
using UnityEngine;

/// <summary>Live yaw flip for upright Meshy Tower city meshes that face the wrong way.</summary>
public static class TowerCityMeshYawFlip20260803
{
	private const string MeshPrefix = "homm3_custom_city_mesh_";

	public static string Run(string requestJson)
	{
		try
		{
			var sb = new StringBuilder();
			sb.Append("{\"ok\":true,\"meshes\":[");
			var first = true;
			var all = Resources.FindObjectsOfTypeAll<GameObject>();
			for (var i = 0; i < all.Length; i++)
			{
				var go = all[i];
				if (!go || string.IsNullOrEmpty(go.name) || !go.name.StartsWith(MeshPrefix, StringComparison.Ordinal))
					continue;
				if (!go.scene.IsValid() || !go.scene.isLoaded)
					continue;

				var before = go.transform.localRotation.eulerAngles;
				go.transform.localRotation = go.transform.localRotation * Quaternion.Euler(0f, 180f, 0f);
				var after = go.transform.localRotation.eulerAngles;

				if (!first) sb.Append(',');
				first = false;
				sb.Append("{");
				sb.Append("\"path\":").Append(Json(BuildPath(go.transform)));
				sb.Append(",\"beforeEuler\":").Append(V3(before));
				sb.Append(",\"afterEuler\":").Append(V3(after));
				sb.Append(",\"activeInHierarchy\":").Append(go.activeInHierarchy ? "true" : "false");
				sb.Append("}");
			}
			sb.Append("],\"note\":\"applied +180 yaw in local space\"}");
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":" + Json(ex.GetType().Name + ": " + ex.Message) + "}";
		}
	}

	private static string BuildPath(Transform t)
	{
		if (!t) return "";
		var path = t.name;
		var cur = t.parent;
		while (cur != null)
		{
			path = cur.name + "/" + path;
			cur = cur.parent;
		}
		return path;
	}

	private static string V3(Vector3 v)
	{
		return "{\"x\":" + F(v.x) + ",\"y\":" + F(v.y) + ",\"z\":" + F(v.z) + "}";
	}

	private static string F(float v)
	{
		return v.ToString("0.###", CultureInfo.InvariantCulture);
	}

	private static string Json(string value)
	{
		if (value == null) return "null";
		return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}
}
