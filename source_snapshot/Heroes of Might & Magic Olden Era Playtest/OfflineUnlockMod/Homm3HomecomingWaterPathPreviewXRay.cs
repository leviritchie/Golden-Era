using System;
using System.Collections.Generic;
using System.Globalization;
using BepInEx.Logging;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Applies depth-xray material overrides to native BhPathDrawer preview renderers on
/// Homecoming maps. Markers keep Hex/Particles with ZTest Always; path segments swap
/// to Hex/Particles because Hex/Misc/Path has no _ZTest property.
/// </summary>
internal static class Homm3HomecomingWaterPathPreviewXRay
{
	internal const string ActiveArchitecture = "path_preview_depth_xray_on_drawer_refresh";
	internal const string OverlayMaterialSuffix = "_HomecomingPathXRay";
	private const string LogPrefix = "HOMM3_HOMECOMING_WATER_PRESENTATION";
	private const int OverlayRenderQueue = 4000;
	private const int ZTestAlways = (int)CompareFunction.Always;
	private const float SegmentColorAlphaScale = 0.55f;

	private static readonly Dictionary<int, OverlayState> OverlayByRendererId = new();
	private static ManualLogSource _log;
	private static Shader _particlesShader;
	private static int _loggedApply;

	private sealed class OverlayState
	{
		internal Material SourceMaterial;
		internal Material OverlayMaterial;
	}

	internal static void SetLog(ManualLogSource log) => _log = log;

	internal static int ComputeFingerprint(Transform drawerRoot)
	{
		if (!drawerRoot)
			return 0;
		unchecked
		{
			var hash = 17;
			foreach (var renderer in drawerRoot.GetComponentsInChildren<Renderer>(includeInactive: false))
			{
				if (!renderer || !renderer.enabled || !renderer.gameObject.activeInHierarchy)
					continue;
				if (!IsPathPreviewRenderer(renderer))
					continue;
				hash = (hash * 31) + renderer.GetInstanceID();
				var material = renderer.sharedMaterial;
				hash = (hash * 31) + StableMaterialHash(material);
			}
			return hash;
		}
	}

	internal static void ApplyForDrawer(Transform drawerRoot)
	{
		if (!drawerRoot)
			return;
		foreach (var renderer in drawerRoot.GetComponentsInChildren<Renderer>(includeInactive: false))
		{
			if (!renderer || !renderer.enabled || !renderer.gameObject.activeInHierarchy)
				continue;
			if (!IsPathPreviewRenderer(renderer))
				continue;
			if (IsMarkerRenderer(renderer))
				ApplyMarkerXRay(renderer);
			else if (IsSegmentRenderer(renderer))
				ApplySegmentXRay(renderer);
		}
	}

	internal static void ReleaseForDrawer(Transform drawerRoot)
	{
		if (!drawerRoot)
			return;
		foreach (var renderer in drawerRoot.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer)
				continue;
			var rendererId = renderer.GetInstanceID();
			if (!OverlayByRendererId.TryGetValue(rendererId, out var state))
				continue;
			renderer.sharedMaterial = state.SourceMaterial;
			renderer.SetPropertyBlock(null);
			if (state.OverlayMaterial)
				UnityEngine.Object.Destroy(state.OverlayMaterial);
			OverlayByRendererId.Remove(rendererId);
		}
	}

	private static int StableMaterialHash(Material material)
	{
		if (!material)
			return 0;
		unchecked
		{
			var hash = 23;
			hash = (hash * 31) + (material.name ?? string.Empty).GetHashCode(StringComparison.Ordinal);
			hash = (hash * 31) + (material.shader ? material.shader.name.GetHashCode(StringComparison.Ordinal) : 0);
			return hash;
		}
	}

	private static bool IsPathPreviewRenderer(Renderer renderer)
		=> IsMarkerRenderer(renderer) || IsSegmentRenderer(renderer);

	private static bool IsMarkerRenderer(Renderer renderer)
	{
		if (!renderer || !string.Equals(renderer.gameObject.name, "Quad", StringComparison.OrdinalIgnoreCase))
			return false;
		for (var node = renderer.transform.parent; node; node = node.parent)
		{
			var name = node.name ?? string.Empty;
			if (name.IndexOf("PathMarker", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	private static bool IsSegmentRenderer(Renderer renderer)
		=> renderer
		   && string.Equals(renderer.gameObject.name, "Path Segment", StringComparison.OrdinalIgnoreCase);

	private static bool AlreadyHasXRay(Renderer renderer)
	{
		var material = renderer ? renderer.sharedMaterial : null;
		return material && (material.name ?? string.Empty).EndsWith(OverlayMaterialSuffix, StringComparison.Ordinal);
	}

	private static void ApplyMarkerXRay(Renderer renderer)
	{
		var source = renderer.sharedMaterial;
		if (!source || source.shader == null)
			return;
		if (!string.Equals(source.shader.name, "Hex/Particles", StringComparison.Ordinal))
			return;
		if (AlreadyHasXRay(renderer))
			return;

		var overlay = GetOrCreateOverlay(renderer, source);
		overlay.renderQueue = OverlayRenderQueue;
		TrySetInt(overlay, "_ZTest", ZTestAlways);
		TrySetInt(overlay, "_ZWrite", 0);
		renderer.sharedMaterial = overlay;
		renderer.SetPropertyBlock(null);
		LogApply("marker", renderer);
	}

	private static void ApplySegmentXRay(Renderer renderer)
	{
		var source = renderer.sharedMaterial;
		if (!source || source.shader == null)
			return;
		if (!string.Equals(source.shader.name, "Hex/Misc/Path", StringComparison.Ordinal))
			return;
		if (AlreadyHasXRay(renderer))
			return;

		var particlesShader = ResolveParticlesShader();
		if (!particlesShader)
			return;

		var overlay = GetOrCreateOverlay(renderer, source);
		overlay.shader = particlesShader;
		overlay.renderQueue = OverlayRenderQueue;
		CopyTexture(source, overlay, "_MainTex");
		CopyScaledColor(source, overlay, "_Color", SegmentColorAlphaScale);
		TrySetInt(overlay, "_ZTest", ZTestAlways);
		TrySetInt(overlay, "_ZWrite", 0);
		TrySetInt(overlay, "_RenderMode", 1);
		renderer.sharedMaterial = overlay;
		renderer.SetPropertyBlock(null);
		LogApply("segment", renderer);
	}

	private static Material GetOrCreateOverlay(Renderer renderer, Material source)
	{
		var rendererId = renderer.GetInstanceID();
		if (OverlayByRendererId.TryGetValue(rendererId, out var state)
		    && state.OverlayMaterial)
		{
			state.SourceMaterial = source;
			return state.OverlayMaterial;
		}

		var overlay = UnityEngine.Object.Instantiate(source);
		overlay.name = source.name + OverlayMaterialSuffix;
		OverlayByRendererId[rendererId] = new OverlayState
		{
			SourceMaterial = source,
			OverlayMaterial = overlay,
		};
		return overlay;
	}

	private static Shader ResolveParticlesShader()
	{
		if (_particlesShader)
			return _particlesShader;
		_particlesShader = Shader.Find("Hex/Particles");
		return _particlesShader;
	}

	private static void CopyTexture(Material source, Material target, string property)
	{
		if (!source.HasProperty(property) || !target.HasProperty(property))
			return;
		target.SetTexture(property, source.GetTexture(property));
	}

	private static void CopyScaledColor(Material source, Material target, string property, float alphaScale)
	{
		if (!source.HasProperty(property) || !target.HasProperty(property))
			return;
		var color = source.GetColor(property);
		color.a *= alphaScale;
		target.SetColor(property, color);
	}

	private static void TrySetInt(Material material, string property, int value)
	{
		if (material != null && material.HasProperty(property))
			material.SetInt(property, value);
	}

	private static void LogApply(string kind, Renderer renderer)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(Homm3HomecomingWaterPresentationBridge.DiagnosticFlag) && _loggedApply >= 12)
			return;
		_loggedApply++;
		_log?.LogInfo(LogPrefix + " path_preview_xray kind=" + kind
			+ " rendererId=" + renderer.GetInstanceID().ToString(CultureInfo.InvariantCulture)
			+ " y=" + renderer.transform.position.y.ToString("0.###", CultureInfo.InvariantCulture)
			+ " material=" + (renderer.sharedMaterial ? renderer.sharedMaterial.name : "?")
			+ ".");
	}
}
