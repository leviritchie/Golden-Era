using System;
using System.Globalization;
using System.Text;
using UnityEngine;

/// <summary>
/// Live-correct Meshy Tower city meshes that imported Z-up and landed on their side.
/// Tries upright orientations, keeps the one with max world-space height, then seats
/// the mesh so its bottom sits near y=0 local to the city root.
/// </summary>
public static class TowerCityMeshUprightFix20260803
{
	private const string MeshPrefix = "homm3_custom_city_mesh_";
	private const float TargetHeight = 5.15f;

	public static string Run(string requestJson)
	{
		try
		{
			var candidates = new[]
			{
				Quaternion.identity,
				Quaternion.Euler(-90f, 0f, 0f),
				Quaternion.Euler(90f, 0f, 0f),
				Quaternion.Euler(0f, 0f, -90f),
				Quaternion.Euler(0f, 0f, 90f),
				Quaternion.Euler(-90f, 180f, 0f),
				Quaternion.Euler(90f, 180f, 0f)
			};

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

				var mf = go.GetComponent<MeshFilter>();
				var mr = go.GetComponent<MeshRenderer>();
				if (!mf || !mf.sharedMesh || !mr)
					continue;

				var beforeRot = go.transform.localRotation.eulerAngles;
				var beforeScale = go.transform.localScale;
				var beforePos = go.transform.localPosition;

				// Preserve current yaw from placement if any, then pick upright pitch/roll.
				var bestRot = go.transform.localRotation;
				var bestHeight = -1f;
				var bestLabel = "unchanged";
				for (var c = 0; c < candidates.Length; c++)
				{
					go.transform.localRotation = candidates[c];
					go.transform.localScale = new Vector3(1f, 1f, 1f);
					var b = mr.bounds;
					var h = b.size.y;
					if (h > bestHeight)
					{
						bestHeight = h;
						bestRot = candidates[c];
						bestLabel = "euler=" + candidates[c].eulerAngles.ToString("0.#");
					}
				}

				go.transform.localRotation = bestRot;
				// Scale so world height ~= TargetHeight.
				go.transform.localScale = new Vector3(1f, 1f, 1f);
				var unscaled = mr.bounds.size.y;
				if (unscaled < 0.0001f) unscaled = 0.0001f;
				var scale = TargetHeight / unscaled;
				go.transform.localScale = new Vector3(scale, scale, scale);

				// Seat bottom on local y=0 of parent (city root ground).
				var bounds = mr.bounds;
				var parent = go.transform.parent;
				if (parent)
				{
					var minY = bounds.center.y - bounds.extents.y;
					var worldBottom = new Vector3(bounds.center.x, minY, bounds.center.z);
					var localBottom = parent.InverseTransformPoint(worldBottom);
					var lp = go.transform.localPosition;
					// Keep authored XZ anchor; only correct Y so the mesh sits on the ground plane.
					go.transform.localPosition = new Vector3(lp.x, lp.y - localBottom.y, lp.z);
				}

				var afterBounds = mr.bounds;
				if (!first) sb.Append(',');
				first = false;
				sb.Append("{");
				sb.Append("\"path\":").Append(Json(BuildPath(go.transform)));
				sb.Append(",\"chosen\":").Append(Json(bestLabel));
				sb.Append(",\"beforeEuler\":").Append(V3(beforeRot));
				sb.Append(",\"afterEuler\":").Append(V3(go.transform.localRotation.eulerAngles));
				sb.Append(",\"beforeScale\":").Append(V3(beforeScale));
				sb.Append(",\"afterScale\":").Append(V3(go.transform.localScale));
				sb.Append(",\"beforeLocalPos\":").Append(V3(beforePos));
				sb.Append(",\"afterLocalPos\":").Append(V3(go.transform.localPosition));
				sb.Append(",\"worldBoundsSize\":").Append(V3(afterBounds.size));
				sb.Append(",\"worldBoundsMinY\":").Append(F(afterBounds.center.y - afterBounds.extents.y));
				sb.Append(",\"worldBoundsMaxY\":").Append(F(afterBounds.center.y + afterBounds.extents.y));
				sb.Append(",\"activeInHierarchy\":").Append(go.activeInHierarchy ? "true" : "false");
				sb.Append("}");
			}
			sb.Append("]}");
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
