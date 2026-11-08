using System;
using System.Collections.Generic;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 map flip-books animate by assigning material assets every frame. Rebinding only the renderer's current
/// slot is undone by the next animation tick, so this map-only component replaces each animated source material
/// with a cached Hex/Lit clone after the animator runs.
/// </summary>
public sealed class Homm3MapBillboardMaterialSync : MonoBehaviour
{
	private const int GlobalRuntimeSwapDiagLimit = 8;
	private const int GlobalRuntimeTreeDiagLimit = 12;
	private const int GlobalRuntimeClassificationDiagLimit = 12;
	private static int _globalRuntimeSwapDiagFrames;
	private static int _globalRuntimeTreeDiagFrames;
	private static int _globalRuntimeClassificationDiagFrames;

	private enum MaterialClassification
	{
		None,
		Homm3Frame,
		HexLit,
		FallbackTexturedBillboard
	}

	private sealed class MaterialClassificationCacheEntry
	{
		internal Material Material;
		internal Shader Shader;
		internal Texture MainTexture;
		internal string Name;
		internal int RenderQueue;
		internal MaterialClassification Classification;
	}

	private Dictionary<int, Material> _hexLitClonesBySourceId = new();
	private Dictionary<int, MaterialClassificationCacheEntry> _materialClassificationsBySourceId = new();

	private Renderer[] _renderers;
	private int[][] _lastSharedMaterialIdsByRenderer;
	private Material _donor;
	private int _diagFrames;
	private int _treeDiagFrames;
	private int _classificationDiagFrames;

	internal void ConfigureHexLitDonor(Material donor)
	{
		if (!donor)
			return;
		_donor = donor;
	}

	private void Awake()
	{
		_renderers = GetComponentsInChildren<Renderer>(true);
		LogRuntimeRenderTree("Awake");
	}

	private void LateUpdate()
	{
		if (!_donor)
			return;
		if (_renderers == null || _renderers.Length == 0)
		{
			_renderers = GetComponentsInChildren<Renderer>(true);
			_lastSharedMaterialIdsByRenderer = null;
		}
		LogRuntimeRenderTree("LateUpdate");

		if (_lastSharedMaterialIdsByRenderer == null || _lastSharedMaterialIdsByRenderer.Length != _renderers.Length)
			_lastSharedMaterialIdsByRenderer = new int[_renderers.Length][];

		var sawFrameMaterial = false;
		var sawReplaceCandidate = false;
		var sawHexLitMaterial = false;
		var replacedAny = false;
		for (var ri = 0; ri < _renderers.Length; ri++)
		{
			var r = _renderers[ri];
			if (!r)
				continue;

			var mats = r.sharedMaterials;
			if (mats == null || mats.Length == 0)
				continue;

			if (MaterialIdsMatchSnapshot(ri, mats))
				continue;

			var changed = false;
			var copy = mats;
			for (var mi = 0; mi < mats.Length; mi++)
			{
				var source = mats[mi];
				var classification = ClassifyMaterial(source);
				if (classification == MaterialClassification.Homm3Frame)
					sawFrameMaterial = true;
				if (classification == MaterialClassification.HexLit)
				{
					sawHexLitMaterial = true;
					continue;
				}
				if (classification != MaterialClassification.Homm3Frame
				    && classification != MaterialClassification.FallbackTexturedBillboard)
					continue;
				sawReplaceCandidate = true;

				var replacement = GetOrCreateHexLitClone(source);
				if (!replacement)
					continue;
				if (!changed)
				{
					copy = new Material[mats.Length];
					Array.Copy(mats, copy, mats.Length);
					changed = true;
				}

				copy[mi] = replacement;
			}

			if (changed)
			{
				r.sharedMaterials = copy;
				replacedAny = true;
				StoreMaterialIdSnapshot(ri, copy);
				LogFirstFewFrameSwaps(mats, copy);
			}
			else
				StoreMaterialIdSnapshot(ri, mats);
		}
		LogRuntimeClassification(sawFrameMaterial, sawReplaceCandidate, sawHexLitMaterial, replacedAny);
	}

	private bool MaterialIdsMatchSnapshot(int rendererIndex, Material[] mats)
	{
		var snapshot = _lastSharedMaterialIdsByRenderer[rendererIndex];
		if (snapshot == null || snapshot.Length != mats.Length)
			return false;
		for (var i = 0; i < mats.Length; i++)
		{
			var id = mats[i] ? mats[i].GetInstanceID() : 0;
			if (snapshot[i] != id)
				return false;
		}
		return true;
	}

	private void StoreMaterialIdSnapshot(int rendererIndex, Material[] mats)
	{
		var snapshot = _lastSharedMaterialIdsByRenderer[rendererIndex];
		if (snapshot == null || snapshot.Length != mats.Length)
		{
			snapshot = new int[mats.Length];
			_lastSharedMaterialIdsByRenderer[rendererIndex] = snapshot;
		}
		for (var i = 0; i < mats.Length; i++)
			snapshot[i] = mats[i] ? mats[i].GetInstanceID() : 0;
	}

	private MaterialClassification ClassifyMaterial(Material source)
	{
		if (!source)
			return MaterialClassification.None;
		var id = source.GetInstanceID();
		var shader = source.shader;
		var mainTexture = TryGetMainTexture(source);
		var name = source.name ?? string.Empty;
		var renderQueue = source.renderQueue;
		_materialClassificationsBySourceId ??= new Dictionary<int, MaterialClassificationCacheEntry>();
		if (_materialClassificationsBySourceId.TryGetValue(id, out var cached)
			&& cached != null
			&& cached.Material == source
			&& cached.Shader == shader
			&& cached.MainTexture == mainTexture
			&& cached.RenderQueue == renderQueue
			&& string.Equals(cached.Name, name, StringComparison.Ordinal))
		{
			return cached.Classification;
		}

		var classification = MaterialClassification.None;
		if (EsquirePikemanVisuals.IsHomm3MapFrameMaterialForRuntimeSync(source))
			classification = MaterialClassification.Homm3Frame;
		else if (EsquirePikemanVisuals.IsHexLitMaterialForRuntimeSync(source))
			classification = MaterialClassification.HexLit;
		else if (IsFallbackTexturedBillboardMaterial(source, mainTexture))
			classification = MaterialClassification.FallbackTexturedBillboard;

		_materialClassificationsBySourceId[id] = new MaterialClassificationCacheEntry
		{
			Material = source,
			Shader = shader,
			MainTexture = mainTexture,
			Name = name,
			RenderQueue = renderQueue,
			Classification = classification
		};
		return classification;
	}

	private Material GetOrCreateHexLitClone(Material source)
	{
		if (!source || !_donor)
			return null;
		var id = source.GetInstanceID();
		_hexLitClonesBySourceId ??= new Dictionary<int, Material>();
		if (_hexLitClonesBySourceId.TryGetValue(id, out var existing) && existing)
			return existing;

		var clone = EsquirePikemanVisuals.CloneHomm3MapFrameMaterialForRuntimeSync(source, _donor);
		if (clone)
			_hexLitClonesBySourceId[id] = clone;
		return clone;
	}

	private static bool IsFallbackTexturedBillboardMaterial(Material m, Texture mainTexture)
	{
		if (!m || !m.shader)
			return false;
		var shaderName = m.shader.name ?? string.Empty;
		if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		if (!mainTexture)
			return false;
		if (shaderName.IndexOf("Sprite", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (shaderName.IndexOf("Unlit", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (m.renderQueue >= 2500)
			return true;
		var name = m.name ?? string.Empty;
		return name.IndexOf("frame", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("sprite", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("billboard", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("homm3", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static Texture TryGetMainTexture(Material m)
	{
		if (!m)
			return null;
		try
		{
			if (m.HasProperty("_MainTex") && m.GetTexture("_MainTex"))
				return m.GetTexture("_MainTex");
		}
		catch { }
		return m.mainTexture;
	}

	private void LogFirstFewFrameSwaps(Material[] source, Material[] replacement)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks
		    || _diagFrames >= 2
		    || _globalRuntimeSwapDiagFrames >= GlobalRuntimeSwapDiagLimit)
			return;
		_diagFrames++;
		_globalRuntimeSwapDiagFrames++;
		var firstSource = FirstChangedMaterial(source, replacement, wantReplacement: false);
		var firstReplacement = FirstChangedMaterial(source, replacement, wantReplacement: true);
		Plugin.LogSource?.LogInfo(
			"Homm3Import: runtime map frame Hex/Lit sync applied source=["
			+ EsquirePikemanVisuals.DescribeMaterialForRuntimeSync(firstSource)
			+ "] replacement=["
			+ EsquirePikemanVisuals.DescribeMaterialForRuntimeSync(firstReplacement)
			+ "].");
	}

	private static Material FirstChangedMaterial(Material[] source, Material[] replacement, bool wantReplacement)
	{
		if (source == null || replacement == null)
			return null;
		var n = Math.Min(source.Length, replacement.Length);
		for (var i = 0; i < n; i++)
		{
			if (ReferenceEquals(source[i], replacement[i]))
				continue;
			return wantReplacement ? replacement[i] : source[i];
		}

		return null;
	}

	private void LogRuntimeRenderTree(string phase)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks
		    || _treeDiagFrames >= 2
		    || _globalRuntimeTreeDiagFrames >= GlobalRuntimeTreeDiagLimit)
			return;
		_treeDiagFrames++;
		_globalRuntimeTreeDiagFrames++;

		var wa = _renderers ?? Array.Empty<Renderer>();
		var msg = "Homm3Import: runtime map billboard tree "
		          + phase
		          + " root='"
		          + (gameObject ? gameObject.name : "?")
		          + "' donor=["
		          + EsquirePikemanVisuals.DescribeMaterialForRuntimeSync(_donor)
		          + "] rendererCount="
		          + wa.Length;
		for (var ri = 0; ri < wa.Length && ri < 8; ri++)
		{
			var r = wa[ri];
			if (!r)
			{
				msg += " | r" + ri + "=(null)";
				continue;
			}

			msg += " | r"
			       + ri
			       + " type="
			       + r.GetType().Name
			       + " path="
			       + BuildPath(r.transform, transform)
			       + " enabled="
			       + r.enabled
			       + " layer="
			       + r.gameObject.layer
			       + " sorting="
			       + r.sortingLayerID
			       + "/"
			       + r.sortingOrder
			       + " flags="
			       + r.shadowCastingMode
			       + "/"
			       + r.receiveShadows;
			var mats = r.sharedMaterials;
			if (mats == null || mats.Length == 0)
			{
				msg += " mats=(none)";
				continue;
			}
			for (var mi = 0; mi < mats.Length && mi < 4; mi++)
			{
				var m = mats[mi];
				msg += " m"
				       + mi
				       + "=["
				       + EsquirePikemanVisuals.DescribeMaterialForRuntimeSync(m)
				       + " homm3Frame="
				       + EsquirePikemanVisuals.IsHomm3MapFrameMaterialForRuntimeSync(m)
				       + " hexLit="
				       + EsquirePikemanVisuals.IsHexLitMaterialForRuntimeSync(m)
				       + "]";
			}
		}
		Plugin.LogSource?.LogInfo(msg);
	}

	private void LogRuntimeClassification(bool sawFrameMaterial, bool sawReplaceCandidate, bool sawHexLitMaterial, bool replacedAny)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks
		    || _classificationDiagFrames >= 3
		    || _globalRuntimeClassificationDiagFrames >= GlobalRuntimeClassificationDiagLimit)
			return;
		if (sawReplaceCandidate || replacedAny || !sawFrameMaterial)
		{
			_classificationDiagFrames++;
			_globalRuntimeClassificationDiagFrames++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import: runtime map material classification root='"
				+ (gameObject ? gameObject.name : "?")
				+ "' renderers="
				+ (_renderers?.Length ?? 0)
				+ " sawFrameMaterial="
				+ sawFrameMaterial
				+ " sawFallbackCandidate="
				+ sawReplaceCandidate
				+ " sawHexLit="
				+ sawHexLitMaterial
				+ " replacedAny="
				+ replacedAny
				+ ".");
		}
	}

	private static string BuildPath(Transform t, Transform root)
	{
		if (!t)
			return "(null)";
		var parts = new List<string>();
		for (var cur = t; cur != null && cur != root; cur = cur.parent)
			parts.Add(cur.name ?? "?");
		parts.Reverse();
		return parts.Count == 0 ? "." : string.Join("/", parts);
	}
}
