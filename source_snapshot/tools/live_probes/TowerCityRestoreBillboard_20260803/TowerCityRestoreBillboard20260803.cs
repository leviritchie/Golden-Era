using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// End Tower Meshy mesh pilot live: destroy mesh markers and restore Tower PNG capitol billboards.
/// </summary>
public static class TowerCityRestoreBillboard20260803
{
	private const string MeshPrefix = "homm3_custom_city_mesh_";
	private const string BillboardPrefix = "homm3_custom_city_billboard_";
	private const string TowerCitySid = "homm3_tower_city";
	private const float BillboardHeight = 5.15f;
	private const int BottomPad = 96;

	public static string Run(string requestJson)
	{
		try
		{
			var destroyedMeshes = new List<string>();
			var restored = new List<string>();
			var all = Resources.FindObjectsOfTypeAll<GameObject>();

			// 1) Destroy mesh markers.
			for (var i = 0; i < all.Length; i++)
			{
				var go = all[i];
				if (!go || string.IsNullOrEmpty(go.name))
					continue;
				if (!go.name.StartsWith(MeshPrefix, StringComparison.Ordinal))
					continue;
				if (!go.scene.IsValid() || !go.scene.isLoaded)
					continue;
				destroyedMeshes.Add(BuildPath(go.transform));
				go.SetActive(false);
				UnityEngine.Object.Destroy(go);
			}

			// 2) Restore Tower billboards on durable city roots.
			var tex = LoadTowerCapitolTexture();
			if (!tex)
				return Fail("missing Tower capitol PNG under plugin homm3_runtime_assets");

			all = Resources.FindObjectsOfTypeAll<GameObject>();
			for (var i = 0; i < all.Length; i++)
			{
				var city = all[i];
				if (!city || !string.Equals(city.name, TowerCitySid, StringComparison.OrdinalIgnoreCase))
					continue;
				if (!city.scene.IsValid() || !city.scene.isLoaded)
					continue;
				if (!city.activeInHierarchy && (city.transform.parent == null
				    || !(city.transform.parent.name ?? "").StartsWith("Section Root:", StringComparison.OrdinalIgnoreCase)))
					continue;

				var path = RestoreBillboard(city, tex);
				if (path != null)
					restored.Add(path);
			}

			var sb = new StringBuilder();
			sb.Append("{\"ok\":true");
			sb.Append(",\"destroyedMeshes\":").Append(destroyedMeshes.Count.ToString(CultureInfo.InvariantCulture));
			sb.Append(",\"restoredBillboards\":").Append(restored.Count.ToString(CultureInfo.InvariantCulture));
			sb.Append(",\"destroyedPaths\":[");
			for (var i = 0; i < destroyedMeshes.Count; i++)
			{
				if (i > 0) sb.Append(',');
				sb.Append(Json(destroyedMeshes[i]));
			}
			sb.Append("],\"restoredPaths\":[");
			for (var i = 0; i < restored.Count; i++)
			{
				if (i > 0) sb.Append(',');
				sb.Append(Json(restored[i]));
			}
			sb.Append("],\"note\":\"config homm3TowerCityMapMesh=false; meshes removed; Tower capitol PNG billboards restored\"}");
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static string RestoreBillboard(GameObject cityRoot, Texture2D tex)
	{
		var billboardName = BillboardPrefix + TowerCitySid;
		var existing = cityRoot.transform.Find(billboardName);
		if (existing)
			UnityEngine.Object.Destroy(existing.gameObject);

		var donor = FindHexLitDonor(cityRoot);
		var mapLayer = donor ? donor.gameObject.layer : cityRoot.layer;

		var root = new GameObject(billboardName);
		root.transform.SetParent(cityRoot.transform, false);
		root.layer = mapLayer;

		var visibleH = Math.Max(1, tex.height - BottomPad);
		var scaleX = BillboardHeight * tex.width / (float)visibleH;
		var scaleY = BillboardHeight * tex.height / (float)visibleH;
		var liftY = scaleY * 0.5f - (BillboardHeight * BottomPad / (float)visibleH) + 0.05f;

		root.transform.localPosition = new Vector3(0f, liftY, 0.2f);
		root.transform.localRotation = Quaternion.identity;
		root.transform.localScale = new Vector3(1f, 1f, 1f);

		var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
		quad.name = "quad";
		var col = quad.GetComponent("Collider");
		if (col)
			UnityEngine.Object.Destroy(col);
		quad.transform.SetParent(root.transform, false);
		quad.layer = mapLayer;
		quad.transform.localPosition = new Vector3(0f, 0f, -0.02f);
		quad.transform.localRotation = Quaternion.identity;
		quad.transform.localScale = new Vector3(scaleX, scaleY, 1f);
		var mr = quad.GetComponent<MeshRenderer>();
		var mat = CreateBillboardMaterial(donor, tex);
		mr.sharedMaterial = mat;
		mr.enabled = true;
		mr.forceRenderingOff = false;
		mr.shadowCastingMode = ShadowCastingMode.On;
		mr.receiveShadows = false;
		mr.allowOcclusionWhenDynamic = false;

		// Hide donor city renderers under this root (not under our billboard).
		var renderers = cityRoot.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r || r.transform.IsChildOf(root.transform))
				continue;
			r.enabled = false;
			r.forceRenderingOff = true;
		}

		root.SetActive(true);
		return BuildPath(root.transform);
	}

	private static Material CreateBillboardMaterial(Renderer donor, Texture2D tex)
	{
		Material mat;
		if (donor && donor.sharedMaterial && donor.sharedMaterial.shader
		    && (donor.sharedMaterial.shader.name ?? "").IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			mat = new Material(donor.sharedMaterial);
		}
		else
		{
			var shader = Shader.Find("Hex/Lit") ?? Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Transparent");
			mat = new Material(shader);
		}
		mat.name = "HOMM3_tower_city_billboard_restore";
		if (mat.HasProperty("_MainTex"))
			mat.SetTexture("_MainTex", tex);
		else
			mat.mainTexture = tex;
		if (mat.HasProperty("_Color"))
			mat.SetColor("_Color", Color.white);
		try { mat.DisableKeyword("HEX_BLEND_INTO_TERRAIN_POSITION"); } catch { }
		try { mat.DisableKeyword("HEX_BLEND_INTO_TERRAIN_COLOR"); } catch { }
		try { mat.DisableKeyword("HEX_VERTEX_DISPLACEMENT_FLAG"); } catch { }
		return mat;
	}

	private static Renderer FindHexLitDonor(GameObject root)
	{
		Renderer best = null;
		var bestScore = int.MinValue;
		var section = root.transform.parent;
		var search = section ? section.gameObject : root;
		var renderers = search.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r || !r.sharedMaterial || !r.sharedMaterial.shader)
				continue;
			var name = r.sharedMaterial.shader.name ?? "";
			var score = 0;
			if (name.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
				score += 1000;
			if (r.enabled)
				score += 10;
			if (score > bestScore)
			{
				bestScore = score;
				best = r;
			}
		}
		return best;
	}

	private static Texture2D LoadTowerCapitolTexture()
	{
		var plugin = FindPluginRoot();
		if (plugin == null)
			return null;
		var path = Path.Combine(plugin,
			"homm3_runtime_assets", "map_object_refs", "homm3_tower_city", "capitol.dir", "00_00.png");
		if (!File.Exists(path))
			return null;
		var bytes = File.ReadAllBytes(path);
		var src = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		if (!ImageConversion.LoadImage(src, bytes, false))
			return null;

		// Match production bottom pad so feet clear terrain blend.
		var padded = new Texture2D(src.width, src.height + BottomPad, TextureFormat.RGBA32, false);
		padded.filterMode = FilterMode.Bilinear;
		padded.wrapMode = TextureWrapMode.Clamp;
		var clear = new Color(0f, 0f, 0f, 0f);
		for (var y = 0; y < BottomPad; y++)
			for (var x = 0; x < padded.width; x++)
				padded.SetPixel(x, y, clear);
		for (var y = 0; y < src.height; y++)
			for (var x = 0; x < src.width; x++)
				padded.SetPixel(x, y + BottomPad, src.GetPixel(x, y));
		padded.Apply(false, false);
		padded.name = "HOMM3_tower_capitol_restore";
		UnityEngine.Object.Destroy(src);
		return padded;
	}

	private static string FindPluginRoot()
	{
		try
		{
			// Assembly.Load(byte[]) probes have empty Location — resolve from game data path.
			var dataPath = Application.dataPath; // .../HeroesOldenEra_Data
			var gameRoot = Directory.GetParent(dataPath);
			if (gameRoot == null)
				return null;
			var plugin = Path.Combine(gameRoot.FullName, "BepInEx", "plugins", "OfflineUnlockMod");
			return Directory.Exists(plugin) ? plugin : null;
		}
		catch
		{
			return null;
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

	private static string Json(string value)
	{
		if (value == null) return "null";
		return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}

	private static string Fail(string msg)
	{
		return "{\"ok\":false,\"error\":" + Json(msg) + "}";
	}
}
