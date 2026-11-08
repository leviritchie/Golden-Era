using System;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Rendering;

public static class PathMarkerXRayProbe20260706
{
	private const int OverlayRenderQueue = 4000;
	private const int ZTestAlways = (int)CompareFunction.Always;

	private static readonly Dictionary<int, Material> OriginalMaterials = new();
	private static readonly Dictionary<int, int> OriginalRenderQueues = new();

	public static string Run(string requestJson)
	{
		var action = ReadString(requestJson, "action") ?? ReadNestedString(requestJson, "payload", "action") ?? "dump";
		var sb = new StringBuilder();
		try
		{
			sb.Append("scene=").Append(UnityEngine.SceneManagement.SceneManager.GetActiveScene().name ?? "?");
			if (string.Equals(action, "revert", StringComparison.OrdinalIgnoreCase))
				Revert(sb);
			else if (string.Equals(action, "apply", StringComparison.OrdinalIgnoreCase))
				Apply(sb, requestJson);
			else
				Dump(sb);

			return "{\"ok\":true,\"action\":\"" + Escape(action) + "\",\"text\":\"" + Escape(sb.ToString()) + "\"}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"action\":\"" + Escape(action) + "\",\"exception\":\"" + Escape(ex.GetType().Name) + "\",\"message\":\"" + Escape(ex.Message) + "\",\"stack\":\"" + Escape(ex.StackTrace ?? "") + "\"}";
		}
	}

	private static void Dump(StringBuilder sb)
	{
		var targets = FindPathPreviewRenderers();
		sb.Append("\ntargetCount=").Append(targets.Count);
		foreach (var entry in targets)
		{
			AppendRenderer(sb, entry.Renderer, entry.Path, entry.Kind, "dump");
			AppendMaterialProperties(sb, entry.Renderer != null ? entry.Renderer.sharedMaterial : null, entry.Path + "/props");
		}
	}

	private static void Apply(StringBuilder sb, string requestJson)
	{
		var allMarkers = string.Equals(
			ReadString(requestJson, "allMarkers") ?? ReadNestedString(requestJson, "payload", "allMarkers"),
			"true",
			StringComparison.OrdinalIgnoreCase);
		var segmentShaderSwap = string.Equals(
			ReadString(requestJson, "segmentShaderSwap") ?? ReadNestedString(requestJson, "payload", "segmentShaderSwap"),
			"true",
			StringComparison.OrdinalIgnoreCase);
		var targets = FindPathPreviewRenderers();
		var applied = 0;
		sb.Append("\ntargetCount=").Append(targets.Count)
			.Append(" allMarkers=").Append(allMarkers)
			.Append(" segmentShaderSwap=").Append(segmentShaderSwap);
		foreach (var entry in targets)
		{
			var renderer = entry.Renderer;
			if (!renderer)
				continue;
			if (entry.Kind == "marker" && !allMarkers && renderer.transform.position.y >= 0f)
			{
				sb.Append("\nskip ").Append(entry.Path).Append(" y=").Append(renderer.transform.position.y.ToString("0.###"));
				continue;
			}

			if (entry.Kind == "segment" && segmentShaderSwap)
			{
				if (ApplySegmentShaderSwap(renderer, entry.Path, sb))
					applied++;
				continue;
			}

			if (ApplyXRay(renderer, entry.Path, entry.Kind, sb))
				applied++;
		}
		sb.Append("\napplied=").Append(applied);
	}

	private static bool ApplySegmentShaderSwap(Renderer renderer, string path, StringBuilder sb)
	{
		var id = renderer.GetInstanceID();
		if (!OriginalMaterials.ContainsKey(id))
		{
			OriginalMaterials[id] = renderer.sharedMaterial;
			OriginalRenderQueues[id] = renderer.sharedMaterial != null ? renderer.sharedMaterial.renderQueue : 0;
		}

		var source = renderer.sharedMaterial;
		if (!source)
		{
			sb.Append("\nnoMaterial ").Append(path);
			return false;
		}

		var overlayShader = Shader.Find("Hex/Particles");
		if (!overlayShader)
		{
			sb.Append("\nshaderMissing Hex/Particles ").Append(path);
			return false;
		}

		var instance = UnityEngine.Object.Instantiate(source);
		instance.name = source.name + "_XRaySegmentProbe";
		instance.shader = overlayShader;
		instance.renderQueue = OverlayRenderQueue;
		CopySharedColor(source, instance, sb, path);
		TrySetOverlayDepthState(instance, sb, path);

		var block = new MaterialPropertyBlock();
		renderer.GetPropertyBlock(block);
		TrySetOverlayDepthState(block, sb, path + "/mpb");
		renderer.SetPropertyBlock(block);
		renderer.sharedMaterial = instance;
		AppendRenderer(sb, renderer, path, "segment", "shaderSwap");
		AppendMaterialProperties(sb, instance, path + "/props");
		return true;
	}

	private static void CopySharedColor(Material source, Material target, StringBuilder sb, string path)
	{
		foreach (var property in new[] { "_Color", "_TintColor", "_BaseColor", "_MainColor" })
		{
			if (!source.HasProperty(property) || !target.HasProperty(property))
				continue;
			if (source.HasColor(property) && target.HasColor(property))
			{
				target.SetColor(property, source.GetColor(property));
				sb.Append("\n").Append(path).Append(" copy ").Append(property);
			}
		}
	}

	private static void AppendMaterialProperties(StringBuilder sb, Material material, string label)
	{
		if (!material)
			return;
		sb.Append("\n").Append(label).Append(" props=");
		var count = material.shader ? material.shader.GetPropertyCount() : 0;
		for (var i = 0; i < count && i < 24; i++)
		{
			var name = material.shader.GetPropertyName(i);
			sb.Append(' ').Append(name);
		}
	}

	private static bool ApplyXRay(Renderer renderer, string path, string kind, StringBuilder sb)
	{
		var id = renderer.GetInstanceID();
		if (!OriginalMaterials.ContainsKey(id))
		{
			OriginalMaterials[id] = renderer.sharedMaterial;
			OriginalRenderQueues[id] = renderer.sharedMaterial != null ? renderer.sharedMaterial.renderQueue : 0;
		}

		var source = renderer.sharedMaterial;
		if (!source)
		{
			sb.Append("\nnoMaterial ").Append(path);
			return false;
		}

		var instance = UnityEngine.Object.Instantiate(source);
		instance.name = source.name + "_XRayProbe";
		instance.renderQueue = OverlayRenderQueue;
		TrySetOverlayDepthState(instance, sb, path);

		var block = new MaterialPropertyBlock();
		renderer.GetPropertyBlock(block);
		TrySetOverlayDepthState(block, sb, path + "/mpb");
		renderer.SetPropertyBlock(block);
		renderer.sharedMaterial = instance;
		AppendRenderer(sb, renderer, path, kind, "applied");
		return true;
	}

	private static void Revert(StringBuilder sb)
	{
		var reverted = 0;
		foreach (var pair in new List<KeyValuePair<int, Material>>(OriginalMaterials))
		{
			var renderer = FindRendererByInstanceId(pair.Key);
			if (!renderer)
				continue;
			renderer.sharedMaterial = pair.Value;
			renderer.SetPropertyBlock(null);
			if (pair.Value)
				pair.Value.renderQueue = OriginalRenderQueues.TryGetValue(pair.Key, out var queue) ? queue : pair.Value.renderQueue;
			reverted++;
		}
		OriginalMaterials.Clear();
		OriginalRenderQueues.Clear();
		sb.Append("\nreverted=").Append(reverted);
	}

	private static void TrySetOverlayDepthState(Material material, StringBuilder sb, string label)
	{
		if (!material)
			return;
		TrySetInt(material, sb, label, "_ZTest", ZTestAlways);
		TrySetInt(material, sb, label, "_ZWrite", 0);
		TrySetFloat(material, sb, label, "_ZTest", ZTestAlways);
	}

	private static void TrySetOverlayDepthState(MaterialPropertyBlock block, StringBuilder sb, string label)
	{
		if (block == null)
			return;
		block.SetInt("_ZTest", ZTestAlways);
		block.SetInt("_ZWrite", 0);
		sb.Append("\n").Append(label).Append(" mpbZTest=").Append(ZTestAlways);
	}

	private static void TrySetInt(Material material, StringBuilder sb, string label, string property, int value)
	{
		if (!material.HasProperty(property))
			return;
		material.SetInt(property, value);
		sb.Append("\n").Append(label).Append(" ").Append(property).Append("=").Append(value);
	}

	private static void TrySetFloat(Material material, StringBuilder sb, string label, string property, float value)
	{
		if (!material.HasProperty(property))
			return;
		material.SetFloat(property, value);
		sb.Append("\n").Append(label).Append(" ").Append(property).Append("=").Append(value.ToString("0.###"));
	}

	private static void AppendRenderer(StringBuilder sb, Renderer renderer, string path, string kind, string phase)
	{
		if (!renderer)
			return;
		var mat = renderer.sharedMaterial;
		sb.Append("\n[").Append(phase).Append("][").Append(kind).Append("] ").Append(path)
			.Append(" id=").Append(renderer.GetInstanceID())
			.Append(" type=").Append(renderer.GetType().Name)
			.Append(" y=").Append(renderer.transform.position.y.ToString("0.###"))
			.Append(" enabled=").Append(renderer.enabled)
			.Append(" queue=").Append(mat ? mat.renderQueue.ToString() : "null")
			.Append(" shader=").Append(mat && mat.shader ? mat.shader.name : "null");
		if (mat)
		{
			TryAppendProperty(sb, mat, "_ZTest");
			TryAppendProperty(sb, mat, "_ZWrite");
			TryAppendProperty(sb, mat, "_Cull");
		}
	}

	private static void TryAppendProperty(StringBuilder sb, Material material, string property)
	{
		if (!material.HasProperty(property))
			return;
		if (material.HasInt(property))
			sb.Append(' ').Append(property).Append('=').Append(material.GetInt(property));
		else if (material.HasFloat(property))
			sb.Append(' ').Append(property).Append('=').Append(material.GetFloat(property).ToString("0.###"));
	}

	private sealed class PreviewEntry
	{
		internal Renderer Renderer;
		internal string Path;
		internal string Kind;
	}

	private static List<PreviewEntry> FindPathPreviewRenderers()
	{
		var results = new List<PreviewEntry>();
		var seen = new HashSet<int>();
		foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
		{
			if (!go || !go.activeInHierarchy)
				continue;
			var path = BuildPath(go.transform);
			if (path.IndexOf("Ref Path Drawer", StringComparison.OrdinalIgnoreCase) < 0)
				continue;

			Renderer renderer = null;
			string kind = null;
			if (path.IndexOf("PathMarker", StringComparison.OrdinalIgnoreCase) >= 0
			    && string.Equals(go.name, "Quad", StringComparison.OrdinalIgnoreCase))
			{
				renderer = go.GetComponent<Renderer>();
				kind = "marker";
			}
			else if (string.Equals(go.name, "Path Segment", StringComparison.OrdinalIgnoreCase))
			{
				renderer = go.GetComponent<Renderer>();
				kind = "segment";
			}

			if (!renderer || kind == null)
				continue;
			var id = renderer.GetInstanceID();
			if (!seen.Add(id))
				continue;
			results.Add(new PreviewEntry { Renderer = renderer, Path = path, Kind = kind });
		}
		return results;
	}

	private static Renderer FindRendererByInstanceId(int instanceId)
	{
		foreach (var renderer in Resources.FindObjectsOfTypeAll<Renderer>())
		{
			if (renderer && renderer.GetInstanceID() == instanceId)
				return renderer;
		}
		return null;
	}

	private static string BuildPath(Transform transform)
	{
		if (!transform)
			return "";
		var parts = new List<string>();
		for (var node = transform; node; node = node.parent)
			parts.Add(node.name);
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static string ReadNestedString(string json, string objectKey, string fieldKey)
	{
		var nested = ReadString(json, objectKey);
		return string.IsNullOrEmpty(nested) ? null : ReadString(nested, fieldKey);
	}

	private static string ReadString(string json, string key)
	{
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return null;
		var match = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\"(?<v>(?:\\\\.|[^\\\"])*)\\\"");
		if (!match.Success)
			return null;
		return match.Groups["v"].Value.Replace("\\\"", "\"").Replace("\\\\", "\\");
	}

	private static string Escape(string value)
	{
		if (value == null)
			return "";
		return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
	}
}
