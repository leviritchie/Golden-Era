using System;
using System.Collections.Generic;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Copies animated HoMM3 map materials/meshes from hidden <c>homm3_map_visual</c> onto a shell-local
/// flat <see cref="MeshRenderer"/> (or a native flat mesh slot when one exists) so fog/shroud uses the
/// same enabled state as stock map units.
/// Does not mirror visibility or poll fog — the engine owns <c>Renderer.enabled</c> on the draw slot.
/// This is the map-frame fallback/transplant path, not the preferred RIFE Texture2DArray Hex/Lit path.
/// Skinned donor slots (e.g. Troglodyte) must not be the draw target: billboard quads are invisible there.
/// If unit billboards disappear after deploy, check bundle provenance and <c>map_array.mat</c> availability
/// before changing this component's visibility state.
/// </summary>
public sealed class Homm3NativeShellRendererTransplantSync : MonoBehaviour
{
	private const string VisualRootName = "homm3_map_visual";
	private static int _diagRemaining = 12;
	private static int _meshCopyFailDiagRemaining = 8;

	private Renderer _targetRenderer;
	private Renderer _sourceRenderer;
	private MeshFilter _targetMeshFilter;
	private MeshFilter _sourceMeshFilter;
	private Material _donorMaterial;
	private Material _nativeSlotMaterialForFog;
	private Dictionary<int, Material> _hexLitClonesBySourceId;
	private int _lastSourceMaterialId;
	private int _lastSourceMeshId;
	private int _lastSyncedSourcePosHash;
	private int _lastSyncedSourceRotHash;
	private int _lastSyncedSourceScaleHash;
	private int _lastSyncedParentScaleHash;
	private bool _forceNextTransformSync;
	private MaterialPropertyBlock _transplantMpb;
	private bool _controllerVisible = true;
	private bool _rawArrayMaterialRejected;
	private static int _rawArrayMaterialRejectDiagRemaining = 8;

	public Homm3NativeShellRendererTransplantSync(IntPtr ptr)
		: base(ptr)
	{
	}

	internal void Configure(Material donorMaterial)
	{
		if (donorMaterial)
			_donorMaterial = donorMaterial;
	}

	internal void ApplyControllerVisibility(bool visible)
	{
		_controllerVisible = visible;
		if (_targetRenderer)
		{
			if (_rawArrayMaterialRejected || IsCurrentSourceRawMapArrayMaterial())
			{
				_rawArrayMaterialRejected = true;
				_targetRenderer.enabled = false;
				_targetRenderer.forceRenderingOff = true;
			}
			else
			{
				_targetRenderer.enabled = visible;
				_targetRenderer.forceRenderingOff = !visible;
			}
		}
		if (_sourceRenderer)
		{
			_sourceRenderer.enabled = false;
			_sourceRenderer.forceRenderingOff = true;
		}
	}

	private void Awake()
	{
		Refresh();
		ApplyTransplant(force: true);
	}

	private void LateUpdate()
	{
		if (!_targetRenderer || !_sourceRenderer)
			Refresh();
		ApplyTransplant(force: false);
	}

	private void Refresh()
	{
		var visual = FindVisualRoot();
		_sourceRenderer = FindBestHoMm3SourceRenderer(visual);
		_sourceMeshFilter = Homm3ImportVisuals.TryGetMeshFilter(_sourceRenderer);
		var nativeTarget = Homm3ImportVisuals.FindBestNativeMapTransplantRenderer(gameObject, visual, preferFlatMeshSlot: true);
		// Skinned donor shells (e.g. troglodyte_upg2_mesh) cannot draw HoMM3 billboard quads.
		_targetRenderer = Homm3ImportVisuals.EnsureSyntheticFlatMapTransplantTarget(
			gameObject,
			nativeTarget,
			_sourceRenderer,
			labSid: null);
		_targetMeshFilter = Homm3ImportVisuals.TryGetMeshFilter(_targetRenderer);
		if (_targetRenderer && !_nativeSlotMaterialForFog && _targetRenderer.sharedMaterial)
			_nativeSlotMaterialForFog = _targetRenderer.sharedMaterial;
		_rawArrayMaterialRejected = IsCurrentSourceRawMapArrayMaterial();

		foreach (var r in GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			if (visual && IsUnder(r.transform, visual))
			{
				r.enabled = false;
				r.forceRenderingOff = true;
				r.shadowCastingMode = ShadowCastingMode.Off;
				r.receiveShadows = false;
			}
			else if (r != _targetRenderer)
				Homm3ImportVisuals.PrepareNativeShellDriverRenderer(r);
		}
	}

	private void ApplyTransplant(bool force)
	{
		if (!_targetRenderer || !_sourceRenderer)
			return;

		if (IsCurrentSourceRawMapArrayMaterial())
		{
			RejectRawMapArrayTransplant();
			return;
		}
		_rawArrayMaterialRejected = false;

		var meshCopied = TryCopyMeshFromSourceToTarget(force);
		if (!meshCopied && _meshCopyFailDiagRemaining > 0)
		{
			_meshCopyFailDiagRemaining--;
			Plugin.LogSource?.LogWarning(
				"Homm3Import: native-shell mesh transplant failed root='"
				+ (gameObject ? gameObject.name : "?")
				+ "' targetType="
				+ Homm3ImportVisuals.DescribeMapRenderer(_targetRenderer)
				+ " sourceType="
				+ Homm3ImportVisuals.DescribeMapRenderer(_sourceRenderer)
				+ " srcMesh="
				+ (_sourceMeshFilter && _sourceMeshFilter.sharedMesh ? _sourceMeshFilter.sharedMesh.name : "(null)")
				+ "; material/MPB sync still runs.");
		}

		_forceNextTransformSync = force;
		SyncBillboardTransformFromSourceToTarget();

		_targetRenderer.enabled = _controllerVisible;
		_targetRenderer.forceRenderingOff = !_controllerVisible;
		if (_sourceRenderer)
		{
			_sourceRenderer.enabled = false;
			_sourceRenderer.forceRenderingOff = true;
		}
		// Never copy enabled from the hidden HoMM3 child — stock map fog toggles the native renderer only.

		var sourceMaterial = ResolveSourceMaterial(_sourceRenderer.sharedMaterial);
		var sourceId = sourceMaterial ? sourceMaterial.GetInstanceID() : 0;
		var materialChanged = force || sourceId != _lastSourceMaterialId;
		if (materialChanged)
		{
			_lastSourceMaterialId = sourceId;
			if (sourceMaterial)
				_targetRenderer.sharedMaterial = sourceMaterial;
		}

		if (materialChanged)
			CopyPropertyBlockFromSourceToTarget();

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3Import: native-shell renderer transplant root='"
				+ (gameObject ? gameObject.name : "?")
				+ "' target='"
				+ (_targetRenderer ? BuildPath(_targetRenderer.transform, transform) : "(null)")
				+ "' targetType="
				+ (_targetRenderer ? _targetRenderer.GetType().Name : "(null)")
				+ " source='"
				+ (_sourceRenderer ? BuildPath(_sourceRenderer.transform, transform) : "(null)")
				+ "' sourceMat='"
				+ (sourceMaterial ? sourceMaterial.name : "(null)")
				+ "' sourceShader="
				+ (sourceMaterial && sourceMaterial.shader ? sourceMaterial.shader.name : "(null)")
				+ ".");
		}
	}

	private bool IsCurrentSourceRawMapArrayMaterial()
	{
		return _sourceRenderer
		       && Homm3ImportVisuals.IsHomm3MapArrayBillboardMaterial(_sourceRenderer.sharedMaterial);
	}

	private void RejectRawMapArrayTransplant()
	{
		_rawArrayMaterialRejected = true;
		if (_targetRenderer)
		{
			_targetRenderer.enabled = false;
			_targetRenderer.forceRenderingOff = true;
		}
		if (_sourceRenderer)
		{
			_sourceRenderer.enabled = false;
			_sourceRenderer.forceRenderingOff = true;
		}
		if (_rawArrayMaterialRejectDiagRemaining > 0)
		{
			_rawArrayMaterialRejectDiagRemaining--;
			Plugin.LogSource?.LogWarning(
				"Homm3Import: native-shell renderer transplant rejected raw map_array material on '"
				+ (gameObject ? gameObject.name : "?")
				+ "'; map-array units must attach through Homm3MapArraySliceHexLitBridge.");
		}
	}

	private bool TryCopyMeshFromSourceToTarget(bool force)
	{
		var srcMesh = _sourceMeshFilter ? _sourceMeshFilter.sharedMesh : null;
		if (!srcMesh)
		{
			var srcSkinned = Homm3ImportVisuals.TryAsSkinnedMeshRenderer(_sourceRenderer);
			if (srcSkinned)
				srcMesh = srcSkinned.sharedMesh;
		}
		if (!srcMesh)
			return false;

		var srcMeshId = srcMesh.GetInstanceID();
		if (!force && srcMeshId == _lastSourceMeshId)
			return true;
		_lastSourceMeshId = srcMeshId;

		var srcSkinnedOnly = Homm3ImportVisuals.TryAsSkinnedMeshRenderer(_sourceRenderer);
		var tgtSkinned = Homm3ImportVisuals.TryAsSkinnedMeshRenderer(_targetRenderer);
		if (srcSkinnedOnly && tgtSkinned)
		{
			if (!srcSkinnedOnly.sharedMesh)
				return false;
			tgtSkinned.sharedMesh = srcSkinnedOnly.sharedMesh;
			return true;
		}

		if (tgtSkinned)
		{
			tgtSkinned.sharedMesh = srcMesh;
			return true;
		}

		if (_targetMeshFilter)
		{
			_targetMeshFilter.sharedMesh = srcMesh;
			return true;
		}

		return false;
	}

	private void SyncBillboardTransformFromSourceToTarget()
	{
		if (!_sourceRenderer || !_targetRenderer)
			return;
		var src = _sourceRenderer.transform;
		var tgt = _targetRenderer.transform;
		var force = _forceNextTransformSync;
		_forceNextTransformSync = false;
		var posHash = HashVector3(src.position);
		var rotHash = HashQuaternion(src.rotation);
		var scaleHash = HashVector3(src.lossyScale);
		var parentScaleHash = HashVector3(tgt.parent ? tgt.parent.lossyScale : Vector3.one);
		if (!force
		    && posHash == _lastSyncedSourcePosHash
		    && rotHash == _lastSyncedSourceRotHash
		    && scaleHash == _lastSyncedSourceScaleHash
		    && parentScaleHash == _lastSyncedParentScaleHash)
			return;

		_lastSyncedSourcePosHash = posHash;
		_lastSyncedSourceRotHash = rotHash;
		_lastSyncedSourceScaleHash = scaleHash;
		_lastSyncedParentScaleHash = parentScaleHash;
		tgt.position = src.position;
		tgt.rotation = src.rotation;
		tgt.localScale = Homm3ImportVisuals.ResolveLocalScaleForParent(src.lossyScale, tgt.parent);
		Homm3ImportVisuals.AlignMapBillboardRendererBottomToShellAnchor(_targetRenderer, transform);
	}

	private static int HashVector3(Vector3 v)
	{
		unchecked
		{
			var x = (int)(v.x * 1000f);
			var y = (int)(v.y * 1000f);
			var z = (int)(v.z * 1000f);
			return (x * 73856093) ^ (y * 19349663) ^ (z * 83492791);
		}
	}

	private static int HashQuaternion(Quaternion q)
	{
		unchecked
		{
			var x = (int)(q.x * 1000f);
			var y = (int)(q.y * 1000f);
			var z = (int)(q.z * 1000f);
			var w = (int)(q.w * 1000f);
			return (x * 73856093) ^ (y * 19349663) ^ (z * 83492791) ^ (w * 137);
		}
	}

	private static Renderer FindBestHoMm3SourceRenderer(Transform visual)
	{
		if (!visual)
			return null;
		Renderer best = null;
		var bestScore = -1f;
		foreach (var r in visual.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			if (!Homm3ImportVisuals.IsCandidateNativeMapTransplantRenderer(r))
				continue;
			var score = r.bounds.size.sqrMagnitude;
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = r;
		}
		return best;
	}

	private Transform FindVisualRoot()
	{
		var trs = GetComponentsInChildren<Transform>(true);
		for (var i = 0; trs != null && i < trs.Length; i++)
		{
			var t = trs[i];
			if (t && string.Equals(t.name, VisualRootName, StringComparison.Ordinal))
				return t;
		}
		return null;
	}

	private void CopyPropertyBlockFromSourceToTarget()
	{
		_transplantMpb ??= new MaterialPropertyBlock();
		_sourceRenderer.GetPropertyBlock(_transplantMpb);
		_targetRenderer.SetPropertyBlock(_transplantMpb);
	}

	private Material ResolveSourceMaterial(Material source)
	{
		if (!source)
			return source;
		if (EsquirePikemanVisuals.IsHexLitMaterialForRuntimeSync(source))
			return source;
		if (Homm3ImportVisuals.IsHomm3MapArrayBillboardMaterial(source))
			return source;
		if (!EsquirePikemanVisuals.IsHomm3MapFrameMaterialForRuntimeSync(source) || !_donorMaterial)
			return source;
		var id = source.GetInstanceID();
		_hexLitClonesBySourceId ??= new Dictionary<int, Material>();
		if (_hexLitClonesBySourceId.TryGetValue(id, out var existing) && existing)
			return existing;
		var clone = EsquirePikemanVisuals.CloneHomm3MapFrameMaterialForRuntimeSync(source, _donorMaterial);
		if (clone)
			_hexLitClonesBySourceId[id] = clone;
		return clone ? clone : source;
	}

	private static bool IsUnder(Transform t, Transform parent)
	{
		if (!t || !parent)
			return false;
		for (var cur = t; cur != null; cur = cur.parent)
			if (cur == parent)
				return true;
		return false;
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
