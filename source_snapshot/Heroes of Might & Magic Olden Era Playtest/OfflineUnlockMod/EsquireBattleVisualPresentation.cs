using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Stock battle visuals rely on a root + child layout: e.g. <c>UiModelsSpawner</c> adjusts the
/// <b>first child's</b> <c>localScale</c> from <c>UnitViewConfig</c>. Replacing the whole prefab
/// with a custom bundle root can leave layers/sprite sorting unlike vanilla, so the unit
/// looks "invisible" (wrong layer, or 2D sort order) even though meshes exist.
/// </summary>
/// <remarks>
/// Do <b>not</b> copy full localPosition/localRotation/localScale trees from vanilla to a freshly
/// instantiated unparented object: vanilla locals are relative to the battle rig parent; copying
/// them onto a root with no parent corrupts transforms and can break the whole battle view.
/// Also do <b>not</b> copy vanilla’s <b>first child</b> transform onto a custom <c>billboard</c> → <c>quad</c>
/// bundle: the engine overwrites first-child scale with <c>UnitViewConfig.scale</c>; authored size must live on
/// the nested <c>quad</c> (see <c>ESQUIRE_STOCK_VISUAL_CONTRACT.md</c>, prefab commit <c>44051fa</c>).
/// <para>
/// Adventure-map swaps (<c>UnitViewConfig.rtd()</c>) must do the same <b>layer + renderer sorting</b> pass using
/// stock <c>esquire_map</c> as reference; otherwise the bundle prefab keeps authored layers/orders meant for battle
/// or defaults and stacks read as invisible on the world map.
/// </para>
/// </remarks>
internal static class EsquireBattleVisualPresentation
{
	/// <summary>
	/// Copy <see cref="GameObject.layer"/> for the root and each index-matched child only.
	/// </summary>
	internal static void SyncLayersOnlyFromVanilla(GameObject vanilla, GameObject custom)
	{
		if (vanilla == null || custom == null)
			return;
		SyncLayersNode(vanilla.transform, custom.transform);
	}

	private static void SyncLayersNode(Transform v, Transform c)
	{
		c.gameObject.layer = v.gameObject.layer;
		int n = Math.Min(v.childCount, c.childCount);
		for (var i = 0; i < n; i++)
			SyncLayersNode(v.GetChild(i), c.GetChild(i));
	}

	internal static void SyncSpriteRenderersDepthFirst(GameObject vanilla, GameObject custom)
	{
		var vs = vanilla.GetComponentsInChildren<SpriteRenderer>(true);
		var cs = custom.GetComponentsInChildren<SpriteRenderer>(true);
		var n = Math.Min(vs.Length, cs.Length);
		for (var i = 0; i < n; i++)
		{
			cs[i].sortingLayerID = vs[i].sortingLayerID;
			cs[i].sortingOrder = vs[i].sortingOrder;
			cs[i].maskInteraction = vs[i].maskInteraction;
		}
	}

	/// <summary>
	/// Depth-first pairing of mesh renderers only. Use this instead of
	/// <see cref="SyncMapRenderersSortingDepthFirstFallback"/> when swapping a billboards/quad for a vanilla subtree
	/// that mixes <see cref="MeshRenderer"/>, <see cref="SkinnedMeshRenderer"/>, and unrelated renderers —
	/// a single quad must not inherit a shadow/helper renderer’s sorting from a combined Renderer list.
	/// </summary>
	internal static void SyncMeshRenderersSortingDepthFirst(GameObject vanilla, GameObject custom)
	{
		if (vanilla == null || custom == null)
			return;
		var vs = vanilla.GetComponentsInChildren<MeshRenderer>(true);
		var cs = custom.GetComponentsInChildren<MeshRenderer>(true);
		var n = Math.Min(vs.Length, cs.Length);
		for (var i = 0; i < n; i++)
		{
			cs[i].sortingLayerID = vs[i].sortingLayerID;
			cs[i].sortingOrder = vs[i].sortingOrder;
		}
	}

	/// <summary>
	/// When vanilla and custom mesh counts differ (typical preview: many vanilla meshes vs one HOMM3 quad),
	/// copy sorting from the dominant visible mesh subtree on vanilla to every mesh on custom — avoids assigning
	/// the quad invisible UI sorting from vanilla’s depth-first [<c>i=0</c>] helper meshes.
	/// </summary>
	internal static void SyncMeshSortingFromDominantVanillaMesh(GameObject vanilla, GameObject custom)
	{
		if (vanilla == null || custom == null)
			return;
		var crs = custom.GetComponentsInChildren<MeshRenderer>(true);
		if (crs == null || crs.Length == 0)
			return;
		var vanillaDonor = TryFindDominantRenderable(vanilla);
		if (vanillaDonor == null)
			return;
		for (var i = 0; i < crs.Length; i++)
		{
			var cr = crs[i];
			if (cr == null)
				continue;
			cr.sortingLayerID = vanillaDonor.sortingLayerID;
			cr.sortingOrder = vanillaDonor.sortingOrder;
		}
	}

	/// <summary>
	/// Largest enabled <see cref="MeshRenderer"/> or <see cref="SkinnedMeshRenderer"/> on vanilla (by world bounds size).
	/// Used when preview/battle needs a single “hero” mesh to copy masking / render-layer fields from.
	/// </summary>
	internal static Renderer TryFindDominantRenderable(GameObject vanilla)
	{
		if (vanilla == null)
			return null;
		var bestScale = -1f;
		Renderer pick = null;
		foreach (var r in vanilla.GetComponentsInChildren<Renderer>(true))
		{
			if (r == null || !r.enabled)
				continue;
			if (r is not MeshRenderer && r is not SkinnedMeshRenderer)
				continue;
			var sqr = r.bounds.size.sqrMagnitude;
			if (sqr <= bestScale)
				continue;
			bestScale = sqr;
			pick = r;
		}
		return pick;
	}

	/// <summary>URP-compatible render layer mask; matches every custom renderer to the donor (preview camera visibility).</summary>
	internal static void ApplyRenderingLayerMaskFromDonor(Renderer donor, GameObject customRoot)
	{
		if (donor == null || customRoot == null)
			return;
		var mask = donor.renderingLayerMask;
		foreach (var r in customRoot.GetComponentsInChildren<Renderer>(true))
			if (r)
				r.renderingLayerMask = mask;
	}

	/// <summary>Copy renderer-side map-pass flags that affect layer culling, sorting, shadows, outline, and fog participation.</summary>
	internal static void ApplyMapRendererFlagsFromDonor(Renderer donor, GameObject customRoot)
	{
		if (donor == null || customRoot == null)
			return;

		var donorLayer = donor.gameObject != null ? donor.gameObject.layer : customRoot.layer;
		customRoot.layer = donorLayer;
		foreach (var r in customRoot.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			// Source-prepared June 23: adventure-map billboard visibility follows the selected
			// donor renderer, not the donor prefab root. Runtime smoke still pending.
			r.gameObject.layer = donorLayer;
			r.sortingLayerID = donor.sortingLayerID;
			r.sortingOrder = donor.sortingOrder;
			r.renderingLayerMask = donor.renderingLayerMask;
			r.shadowCastingMode = donor.shadowCastingMode;
			r.receiveShadows = donor.receiveShadows;
			r.lightProbeUsage = donor.lightProbeUsage;
			r.reflectionProbeUsage = donor.reflectionProbeUsage;
			r.motionVectorGenerationMode = donor.motionVectorGenerationMode;
			r.allowOcclusionWhenDynamic = donor.allowOcclusionWhenDynamic;
		}
	}

	/// <summary>Compact description of every <see cref="Renderer"/> for logs (shaders, layers, enabled).</summary>
	internal static string DescribeRenderTree(string label, GameObject go)
	{
		if (go == null)
			return label + ": (null GameObject)";
		var sb = new StringBuilder();
		sb.Append(label).Append(" name=").Append(go.name)
			.Append(" rootLayer=").Append(go.layer)
			.Append(" activeSelf=").Append(go.activeSelf)
			.Append(" children=").Append(go.transform.childCount);
		foreach (var r in go.GetComponentsInChildren<Renderer>(true))
		{
			sb.Append(" | ");
			sb.Append(r.GetType().Name);
			sb.Append(" path=").Append(BuildPath(r.transform, go.transform));
			sb.Append(" en=").Append(r.enabled);
			sb.Append(" active=").Append(r.gameObject.activeInHierarchy);
			sb.Append(" visible=").Append(r.isVisible);
			sb.Append(" lyr=").Append(r.gameObject.layer);
			sb.Append(" localPos=").Append(FormatVector3(r.transform.localPosition));
			sb.Append(" localEuler=").Append(FormatVector3(r.transform.localEulerAngles));
			sb.Append(" localScale=").Append(FormatVector3(r.transform.localScale));
			sb.Append(" boundsCenter=").Append(FormatVector3(r.bounds.center));
			sb.Append(" boundsSize=").Append(FormatVector3(r.bounds.size));
			sb.Append(" sort=").Append(r.sortingLayerName).Append('/').Append(r.sortingOrder);
			var m = r.sharedMaterial;
			if (!m)
				sb.Append(" mat=(null)");
			else
			{
				var zj = m.shader;
				var tex = GetDiagnosticTexture(m);
				sb.Append(" mat=").Append(m.name)
					.Append(" zj=").Append(zj ? zj.name : "(null shader)")
					.Append(" rq=").Append(m.renderQueue)
					.Append(" tex=").Append(tex ? tex.name : "(null)");
				AppendCullDiagnostic(sb, m);
				AppendDepthDiagnostic(sb, m);
			}
			if (r is SpriteRenderer sr)
				sb.Append(" spriteMask=").Append(sr.maskInteraction);
		}
		var spriteRendererCount = go.GetComponentsInChildren<SpriteRenderer>(true).Length;
		if (spriteRendererCount > 0)
		{
			sb.Append(" | WARN:")
				.Append(spriteRendererCount)
				.Append(" SpriteRenderer — battle prefab should use MeshRenderer+quad + Hex/Lit or Sprites/Default");
		}
		return sb.ToString();
	}

	private static Texture GetDiagnosticTexture(Material m)
	{
		if (!m)
			return null;
		if (m.mainTexture)
			return m.mainTexture;
		if (m.HasProperty("_BaseMap"))
		{
			var t = m.GetTexture("_BaseMap");
			if (t)
				return t;
		}
		if (m.HasProperty("_BaseColorMap"))
		{
			var t = m.GetTexture("_BaseColorMap");
			if (t)
				return t;
		}
		return null;
	}

	private static void AppendCullDiagnostic(StringBuilder sb, Material m)
	{
		if (!m)
			return;
		if (m.HasProperty("_Cull"))
			sb.Append(" cull=").Append(m.GetFloat("_Cull").ToString("0.###"));
		else if (m.HasProperty("_CullMode"))
			sb.Append(" cullMode=").Append(m.GetFloat("_CullMode").ToString("0.###"));
		else if (m.HasProperty("_CullModeForward"))
			sb.Append(" cullForward=").Append(m.GetFloat("_CullModeForward").ToString("0.###"));
	}

	private static void AppendDepthDiagnostic(StringBuilder sb, Material m)
	{
		if (!m)
			return;
		if (m.HasProperty("_ZWrite"))
			sb.Append(" zwrite=").Append(m.GetFloat("_ZWrite").ToString("0.###"));
		if (m.HasProperty("_ZTest"))
			sb.Append(" ztest=").Append(m.GetFloat("_ZTest").ToString("0.###"));
	}

	private static string FormatVector3(Vector3 v)
	{
		return "("
		       + v.x.ToString("0.###") + ", "
		       + v.y.ToString("0.###") + ", "
		       + v.z.ToString("0.###") + ")";
	}

	internal static string BuildRelativePath(Transform t, Transform stopAt)
	{
		if (t == null)
			return string.Empty;
		var parts = new List<string>();
		for (var x = t; x != null && x != stopAt; x = x.parent)
			parts.Add(x.name);
		parts.Reverse();
		return string.Join("/", parts);
	}

	/// <summary>
	/// Match transforms by hierarchy path (e.g. <c>billboard/quad</c>) and copy layer + every <see cref="Renderer"/>'s
	/// sorting fields from stock map prefab to the custom bundle prefab. Same idea as battle <c>bath</c> sync, but
	/// <c>rtd()</c> returns prefab assets — we mutate the bundle template so instances pick up correct map visibility.
	/// </summary>
	/// <returns>Number of renderers on the custom prefab that received sorting from a path-matched vanilla renderer.</returns>
	internal static int SyncAdventureMapPrefabPresentationFromVanilla(GameObject vanillaMapPrefab, GameObject customMapPrefab)
	{
		if (vanillaMapPrefab == null || customMapPrefab == null)
			return 0;
		var vRoot = vanillaMapPrefab.transform;
		var cRoot = customMapPrefab.transform;
		foreach (var vt in vanillaMapPrefab.GetComponentsInChildren<Transform>(true))
		{
			var rel = BuildRelativePath(vt, vRoot);
			var ct = FindDescendantByRelativePath(cRoot, rel);
			if (ct == null)
				continue;
			ct.gameObject.layer = vt.gameObject.layer;
		}

		var matchedRenderers = 0;
		foreach (var xn in vanillaMapPrefab.GetComponentsInChildren<Renderer>(true))
		{
			var rel = BuildRelativePath(xn.transform, vRoot);
			var ct = FindDescendantByRelativePath(cRoot, rel);
			if (ct == null)
				continue;
			var cr = ct.GetComponent<Renderer>();
			if (cr == null)
				continue;
			cr.sortingLayerID = xn.sortingLayerID;
			cr.sortingOrder = xn.sortingOrder;
			if (cr is SpriteRenderer csr && xn is SpriteRenderer vsr)
				csr.maskInteraction = vsr.maskInteraction;
			matchedRenderers++;
		}

		return matchedRenderers;
	}

	/// <summary>When map prefab node names differ from stock <c>esquire_map</c>, depth-first renderer order often still aligns.</summary>
	internal static void SyncMapRenderersSortingDepthFirstFallback(GameObject vanillaMapPrefab, GameObject customMapPrefab)
	{
		if (vanillaMapPrefab == null || customMapPrefab == null)
			return;
		var vs = vanillaMapPrefab.GetComponentsInChildren<Renderer>(true);
		var cs = customMapPrefab.GetComponentsInChildren<Renderer>(true);
		var n = Math.Min(vs.Length, cs.Length);
		for (var i = 0; i < n; i++)
		{
			cs[i].sortingLayerID = vs[i].sortingLayerID;
			cs[i].sortingOrder = vs[i].sortingOrder;
			if (cs[i] is SpriteRenderer csr && vs[i] is SpriteRenderer vsr)
				csr.maskInteraction = vsr.maskInteraction;
		}
	}

	private static Transform FindDescendantByRelativePath(Transform root, string relativePath)
	{
		if (root == null)
			return null;
		if (string.IsNullOrEmpty(relativePath))
			return root;
		return root.Find(relativePath);
	}

	private static string BuildPath(Transform t, Transform stopAt) => BuildRelativePath(t, stopAt);

	/// <summary>
	/// World-space AABB that contains every enabled <see cref="Renderer"/> on <paramref name="go"/> (battle meshes + billboards).
	/// </summary>
	internal static bool TryEncapsulateWorldRenderBounds(GameObject go, out Bounds merged)
	{
		merged = default;
		if (go == null)
			return false;
		var renderers = go.GetComponentsInChildren<Renderer>(true);
		if (renderers == null || renderers.Length == 0)
			return false;
		var any = false;
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (r == null || !r.enabled || !r.gameObject.activeInHierarchy)
				continue;
			if (!any)
			{
				merged = r.bounds;
				any = true;
			}
			else
				merged.Encapsulate(r.bounds);
		}

		return any;
	}
}
