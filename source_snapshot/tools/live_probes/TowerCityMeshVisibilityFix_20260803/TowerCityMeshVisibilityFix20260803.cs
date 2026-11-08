using System;
using System.Globalization;
using System.Text;
using UnityEngine;

/// <summary>Live diagnose + force-visible Tower city map meshes.</summary>
public static class TowerCityMeshVisibilityFix20260803
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
			var fixedCount = 0;
			for (var i = 0; i < all.Length; i++)
			{
				var go = all[i];
				if (!go || string.IsNullOrEmpty(go.name) || !go.name.StartsWith(MeshPrefix, StringComparison.Ordinal))
					continue;
				if (!go.scene.IsValid() || !go.scene.isLoaded)
					continue;

				var mf = go.GetComponent<MeshFilter>();
				var mr = go.GetComponent<MeshRenderer>();
				var mesh = mf ? mf.sharedMesh : null;
				var mat = mr ? mr.sharedMaterial : null;
				var tex = mat
					? (mat.HasProperty("_MainTex") ? mat.GetTexture("_MainTex") : mat.mainTexture)
					: null;

				// Force visibility knobs that commonly hide Hex/Lit custom meshes.
				if (mr)
				{
					mr.enabled = true;
					mr.forceRenderingOff = false;
					mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
					mr.receiveShadows = false;
					mr.allowOcclusionWhenDynamic = false;
					if (mat)
					{
						if (mat.HasProperty("_HexFade"))
							mat.SetFloat("_HexFade", 0f);
						if (mat.HasProperty("_Cutoff"))
							mat.SetFloat("_Cutoff", 0.01f);
						DisableKeyword(mat, "HEX_DITHER_FADE_ENABLED");
						DisableKeyword(mat, "HEX_ALPHA_CLIP_ENABLED");
						DisableKeyword(mat, "HEX_BLEND_INTO_TERRAIN_POSITION");
						DisableKeyword(mat, "HEX_BLEND_INTO_TERRAIN_COLOR");
						DisableKeyword(mat, "HEX_VERTEX_DISPLACEMENT_FLAG");
						if (mat.HasProperty("_Color"))
							mat.SetColor("_Color", Color.white);
						mr.sharedMaterial = mat;
					}
				}

				// If authored scale somehow collapsed, boost to readable town height.
				var lossy = go.transform.lossyScale;
				var local = go.transform.localScale;
				var meshSize = mesh ? mesh.bounds.size : Vector3.zero;
				var worldHeight = meshSize.y * Mathf.Abs(lossy.y);
				var boosted = false;
				if (worldHeight < 1.5f || worldHeight > 40f || Mathf.Abs(lossy.x) < 0.01f)
				{
					var target = 5.15f;
					var baseH = meshSize.y > 0.0001f ? meshSize.y : 1f;
					var parentLossyY = go.transform.parent ? Mathf.Abs(go.transform.parent.lossyScale.y) : 1f;
					if (parentLossyY < 0.0001f) parentLossyY = 1f;
					var needed = target / (baseH * parentLossyY);
					go.transform.localScale = new Vector3(needed, needed, needed);
					boosted = true;
					fixedCount++;
				}

				// Ensure parents active so activeInHierarchy can be true.
				var t = go.transform;
				while (t != null)
				{
					if (!t.gameObject.activeSelf)
						t.gameObject.SetActive(true);
					t = t.parent;
				}

				if (!first) sb.Append(',');
				first = false;
				sb.Append("{");
				sb.Append("\"path\":").Append(Json(BuildPath(go.transform)));
				sb.Append(",\"activeSelf\":").Append(go.activeSelf ? "true" : "false");
				sb.Append(",\"activeInHierarchy\":").Append(go.activeInHierarchy ? "true" : "false");
				sb.Append(",\"layer\":").Append(go.layer.ToString(CultureInfo.InvariantCulture));
				sb.Append(",\"localScale\":").Append(V3(go.transform.localScale));
				sb.Append(",\"lossyScale\":").Append(V3(go.transform.lossyScale));
				sb.Append(",\"worldPos\":").Append(V3(go.transform.position));
				sb.Append(",\"meshBoundsSize\":").Append(V3(meshSize));
				sb.Append(",\"worldHeightApprox\":").Append(F(meshSize.y * Mathf.Abs(go.transform.lossyScale.y)));
				sb.Append(",\"rendererEnabled\":").Append(mr && mr.enabled ? "true" : "false");
				sb.Append(",\"forceRenderingOff\":").Append(mr && mr.forceRenderingOff ? "true" : "false");
				sb.Append(",\"material\":").Append(Json(mat ? mat.name : null));
				sb.Append(",\"shader\":").Append(Json(mat && mat.shader ? mat.shader.name : null));
				sb.Append(",\"mainTex\":").Append(Json(tex ? tex.name : null));
				sb.Append(",\"mainTexW\":").Append(tex ? tex.width.ToString(CultureInfo.InvariantCulture) : "0");
				sb.Append(",\"mainTexH\":").Append(tex ? tex.height.ToString(CultureInfo.InvariantCulture) : "0");
				sb.Append(",\"keywords\":").Append(Json(mat && mat.shaderKeywords != null ? string.Join(",", mat.shaderKeywords) : ""));
				sb.Append(",\"boosted\":").Append(boosted ? "true" : "false");
				sb.Append("}");
			}
			sb.Append("],\"fixedCount\":").Append(fixedCount.ToString(CultureInfo.InvariantCulture));
			sb.Append(",\"note\":\"forced Hex/Lit visibility knobs + optional scale boost\"}");
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":" + Json(ex.GetType().Name + ": " + ex.Message) + "}";
		}
	}

	private static void DisableKeyword(Material mat, string keyword)
	{
		if (!mat || string.IsNullOrEmpty(keyword))
			return;
		try { mat.DisableKeyword(keyword); } catch { }
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
