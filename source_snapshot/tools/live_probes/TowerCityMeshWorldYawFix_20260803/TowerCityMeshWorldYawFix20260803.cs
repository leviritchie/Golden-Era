using System;
using System.Globalization;
using System.Text;
using UnityEngine;

/// <summary>
/// Undo the bad local-Y*180 flip (upside-down) and apply parent/world yaw 180
/// so the upright Meshy Tower faces the opposite compass direction without tipping.
/// </summary>
public static class TowerCityMeshWorldYawFix20260803
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

				var mr = go.GetComponent<MeshRenderer>();
				var before = go.transform.localRotation.eulerAngles;
				var beforeMinY = mr ? (mr.bounds.center.y - mr.bounds.extents.y) : 0f;
				var beforeMaxY = mr ? (mr.bounds.center.y + mr.bounds.extents.y) : 0f;

				// 1) Undo previous local-space *Euler(0,180,0) that tipped the mesh.
				go.transform.localRotation = go.transform.localRotation * Quaternion.Euler(0f, 180f, 0f);
				var afterUndo = go.transform.localRotation.eulerAngles;

				// 2) Parent/world yaw 180 around vertical: left-multiply so Y is parent up.
				go.transform.localRotation = Quaternion.Euler(0f, 180f, 0f) * go.transform.localRotation;
				var after = go.transform.localRotation.eulerAngles;

				// 3) Reseat bottom to ground if tip/undo shifted bounds.
				if (mr && go.transform.parent)
				{
					var bounds = mr.bounds;
					var minY = bounds.center.y - bounds.extents.y;
					var worldBottom = new Vector3(bounds.center.x, minY, bounds.center.z);
					var localBottom = go.transform.parent.InverseTransformPoint(worldBottom);
					var lp = go.transform.localPosition;
					go.transform.localPosition = new Vector3(lp.x, lp.y - localBottom.y, lp.z);
				}

				var afterBounds = mr ? mr.bounds : default;
				if (!first) sb.Append(',');
				first = false;
				sb.Append("{");
				sb.Append("\"path\":").Append(Json(BuildPath(go.transform)));
				sb.Append(",\"beforeEuler\":").Append(V3(before));
				sb.Append(",\"afterUndoEuler\":").Append(V3(afterUndo));
				sb.Append(",\"afterWorldYawEuler\":").Append(V3(after));
				sb.Append(",\"beforeHeight\":").Append(F(beforeMaxY - beforeMinY));
				sb.Append(",\"afterHeight\":").Append(F(afterBounds.size.y));
				sb.Append(",\"afterMinY\":").Append(F(afterBounds.center.y - afterBounds.extents.y));
				sb.Append(",\"afterMaxY\":").Append(F(afterBounds.center.y + afterBounds.extents.y));
				sb.Append(",\"activeInHierarchy\":").Append(go.activeInHierarchy ? "true" : "false");
				sb.Append("}");
			}
			sb.Append("],\"note\":\"undo local yaw tip; apply parent-space yaw 180\"}");
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
