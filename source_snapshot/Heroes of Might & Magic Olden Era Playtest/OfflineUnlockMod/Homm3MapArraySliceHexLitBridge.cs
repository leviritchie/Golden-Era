using System;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Texture2DArray frame selection on <c>homm3_map_visual</c>, with an optional copied 2D slice on a
/// native shell <see cref="Renderer"/> once the first slice is available.
/// </summary>
public sealed class Homm3MapArraySliceHexLitBridge : MonoBehaviour
{
	const string VisualRootName = "homm3_map_visual";
	const string CloneRehydrateEnabledFlag = "homm3_map_array_clone_rehydrate_enabled.flag";
	const string CloneConfigMarkerPrefix = "homm3_map_array_clone_config__";
	internal const string SyntheticFlatTargetName = "homm3_map_array_hexlit_quad";
	const string SyntheticFlatTargetSidSeparator = "__sid__";
	static readonly int MainTexArrayId = Shader.PropertyToID("_MainTexArray");
	static readonly int MainTexArray1Id = Shader.PropertyToID("_MainTexArray1");
	static readonly int MainTexArray2Id = Shader.PropertyToID("_MainTexArray2");
	static readonly int MainTexArray3Id = Shader.PropertyToID("_MainTexArray3");
	static readonly string[] HexLitBillboardTextureSlots =
	{
		"_MainTex",
		"_BaseMap",
		"_BaseColorMap",
		"_AlbedoMap",
		"_DiffuseMap",
		"_MainTexture",
		"_EmissionTex",
		"_EmissionMap",
	};

	static bool _typeRegistered;
	static int _attachDiagRemaining = 8;
	static int _pendingFirstCopyDiagRemaining = 16;
	static int _copyFailureDiagRemaining = 12;
	static int _sliceCopyDiagRemaining = 32;
	static int _rehydrateDiagRemaining = 8;

	Renderer _targetRenderer;
	Renderer _sourceRenderer;
	MeshFilter _targetMeshFilter;
	MeshFilter _sourceMeshFilter;
	Material _hexLitMaterial;
	Texture2D _sliceTexture;
	Material _arraySourceMaterial;
	MaterialPropertyBlock _arraySourceMpb;
	readonly Texture2DArray[] _arrayTextureCache = new Texture2DArray[4];
	int _arraySliceSize = 2048;
	Homm3BattleArrayBillboard _arrayBillboard;
	int _lastCopiedFrame = -1;
	int _lastSourceMeshId;
	int _lastSyncedSourcePosHash;
	int _lastSyncedSourceRotHash;
	int _lastSyncedSourceScaleHash;
	int _lastSyncedParentScaleHash;
	bool _presentationMaterialBound;
	bool _presentationMpbCleared;
	bool _controllerVisible = true;
	bool _allowSourceDrawWhilePending = true;
	bool _targetIsSyntheticFlatRenderer;
	string _labSid;
	bool _sliceAlphaDiagLogged;
	int _nextRehydrateFrame;

	public Homm3MapArraySliceHexLitBridge(IntPtr ptr)
		: base(ptr)
	{
	}

	internal static void EnsureIl2CppTypeRegistered(BepInEx.Logging.ManualLogSource log)
	{
		if (_typeRegistered)
			return;
		ClassInjector.RegisterTypeInIl2Cpp<Homm3MapArraySliceHexLitBridge>();
		_typeRegistered = true;
		log?.LogInfo("Homm3 map array slice bridge: registered Il2Cpp type.");
	}

	internal static bool TryAttach(
		GameObject shell,
		GameObject mapVisual,
		Renderer transplantTarget,
		Material hexLitDonor,
		string labSid,
		BepInEx.Logging.ManualLogSource log)
	{
		Homm3MapLoadFlightRecorder.MarkGameObject(
			"map-array-bridge.attach.enter",
			shell,
			"labSid=" + (labSid ?? "?")
			+ " target=" + (transplantTarget ? transplantTarget.name : "(null)")
			+ " donor=" + (hexLitDonor ? hexLitDonor.name : "(null)"));
		if (!shell || !mapVisual || !hexLitDonor)
		{
			Homm3MapLoadFlightRecorder.Mark("map-array-bridge.attach.invalid-args", "labSid=" + (labSid ?? "?"));
			return false;
		}
		try
		{
			EnsureIl2CppTypeRegistered(log);

			var bridge = shell.GetComponent<Homm3MapArraySliceHexLitBridge>();
			if (!bridge)
				bridge = shell.AddComponent<Homm3MapArraySliceHexLitBridge>();
			bridge._controllerVisible = true;
			bridge._allowSourceDrawWhilePending = true;
			if (!bridge.Configure(shell, mapVisual, transplantTarget, hexLitDonor, labSid, log))
			{
				Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.attach.configure-failed", shell, "labSid=" + (labSid ?? "?"), census: true);
				return false;
			}
			bridge.LateUpdate();
			if (bridge._lastCopiedFrame < 0)
			{
				if (IsMapArrayBridgeDiagnosticEnabled() && _pendingFirstCopyDiagRemaining > 0)
				{
					_pendingFirstCopyDiagRemaining--;
					log?.LogWarning(
						"Homm3 map array slice bridge: first slice copy pending labSid='"
						+ labSid
						+ "'; keeping bridge alive for later frame.");
				}
				Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.attach.first-copy-pending", shell, "labSid=" + (labSid ?? "?"), census: true);
			}

			if (IsMapArrayBridgeDiagnosticEnabled() && _attachDiagRemaining > 0)
			{
				_attachDiagRemaining--;
				log?.LogInfo(
					"Homm3 map array slice bridge: attached labSid='"
					+ labSid
					+ "' shell='"
					+ (shell.name ?? "?")
					+ "' target='"
					+ (bridge._targetRenderer ? bridge._targetRenderer.name : (transplantTarget.name ?? "?"))
					+ "' targetType="
					+ Homm3ImportVisuals.DescribeMapRenderer(bridge._targetRenderer ? bridge._targetRenderer : transplantTarget)
					+ (bridge._targetIsSyntheticFlatRenderer ? " syntheticFlat=true" : string.Empty)
					+ ".");
			}
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.attach.ok", shell, "labSid=" + (labSid ?? "?") + " frame=" + bridge._lastCopiedFrame, census: true);
			return true;
		}
		catch (Exception ex)
		{
			Homm3MapLoadFlightRecorder.Mark("map-array-bridge.attach.exception", "labSid=" + (labSid ?? "?") + " exception=" + ex.GetType().FullName + ": " + ex.Message, census: true);
			log?.LogWarning("Homm3 map array slice bridge: attach failed labSid='" + labSid + "': " + ex.Message);
			return false;
		}
	}

	bool Configure(
		GameObject shell,
		GameObject mapVisual,
		Renderer transplantTarget,
		Material hexLitDonor,
		string labSid,
		BepInEx.Logging.ManualLogSource log)
	{
		_labSid = labSid ?? string.Empty;
		if (CloneRehydrateEnabled())
			WriteCloneConfigMarker(shell, _labSid);
		if (!Homm3ImportVisuals.TryEnsureMapArrayMaterialTexturesForLabSid(mapVisual, _labSid, log))
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.no-array-textures", mapVisual, "labSid=" + (_labSid ?? "?"), census: true);
			return false;
		}
		Homm3BattleArrayBillboard.TryAttachForMapVisual(mapVisual, labSid, log);
		_arrayBillboard = mapVisual.GetComponent<Homm3BattleArrayBillboard>();
		if (!_arrayBillboard)
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.no-array-billboard", mapVisual, "labSid=" + (labSid ?? "?"));
			return false;
		}

		_sourceRenderer = _arrayBillboard.GetMapArraySourceRenderer();
		if (!_sourceRenderer)
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.no-source-renderer", mapVisual, "labSid=" + (labSid ?? "?"));
			return false;
		}
		_sourceMeshFilter = Homm3ImportVisuals.TryGetMeshFilter(_sourceRenderer);
		_arraySourceMaterial = _sourceRenderer.sharedMaterial;
		if (!_arraySourceMaterial || !Homm3ImportVisuals.IsHomm3MapArrayBillboardMaterial(_arraySourceMaterial))
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.bad-source-material", _sourceRenderer ? _sourceRenderer.gameObject : mapVisual, "labSid=" + (labSid ?? "?"));
			return false;
		}
		_arraySourceMpb ??= new MaterialPropertyBlock();

		_targetRenderer = EnsureFlatSliceTarget(shell, transplantTarget, _sourceRenderer, labSid, log);
		_targetMeshFilter = Homm3ImportVisuals.TryGetMeshFilter(_targetRenderer);
		if (!_targetRenderer)
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.no-target-renderer", shell, "labSid=" + (labSid ?? "?"));
			return false;
		}

		if (_arraySourceMaterial.HasProperty("_ArraySliceSize"))
			_arraySliceSize = Mathf.Max(1, Mathf.RoundToInt(_arraySourceMaterial.GetFloat("_ArraySliceSize")));

		EnsureSliceTexture(log);
		if (!_sliceTexture)
			CreateSliceTexture(2, 2, FilterMode.Point);

		_hexLitMaterial = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(
			hexLitDonor,
			_sliceTexture,
			"homm3_map_array_slice_hexlit");
		if (!_hexLitMaterial)
		{
			Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.no-hexlit-material", shell, "labSid=" + (labSid ?? "?"));
			return false;
		}

		Homm3ImportVisuals.PrepareNativeShellDriverRenderersExcept(shell, mapVisual.transform, _targetRenderer);
		enabled = true;
		_lastCopiedFrame = -1;
		_lastSourceMeshId = 0;
		_lastSyncedSourcePosHash = 0;
		_lastSyncedSourceRotHash = 0;
		_lastSyncedSourceScaleHash = 0;
		_lastSyncedParentScaleHash = 0;
		_presentationMaterialBound = false;
		_presentationMpbCleared = false;
		ApplyControllerVisibility(_controllerVisible);
		Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.configure.ok", shell, "labSid=" + (labSid ?? "?") + " targetSynthetic=" + _targetIsSyntheticFlatRenderer);
		return true;
	}

	static void WriteCloneConfigMarker(GameObject shell, string labSid)
	{
		if (!shell || string.IsNullOrEmpty(labSid))
			return;
		Transform marker = null;
		for (var i = 0; i < shell.transform.childCount; i++)
		{
			var child = shell.transform.GetChild(i);
			if (child && (child.name ?? string.Empty).StartsWith(CloneConfigMarkerPrefix, StringComparison.Ordinal))
			{
				marker = child;
				break;
			}
		}
		if (!marker)
		{
			var markerGo = new GameObject(CloneConfigMarkerPrefix + labSid);
			markerGo.transform.SetParent(shell.transform, false);
			markerGo.SetActive(false);
			return;
		}
		marker.name = CloneConfigMarkerPrefix + labSid;
		marker.gameObject.SetActive(false);
	}

	static bool TryReadCloneConfigMarker(GameObject shell, out string labSid)
	{
		labSid = null;
		if (!shell)
			return false;
		for (var i = 0; i < shell.transform.childCount; i++)
		{
			var child = shell.transform.GetChild(i);
			var name = child ? child.name : null;
			if (string.IsNullOrEmpty(name) || !name.StartsWith(CloneConfigMarkerPrefix, StringComparison.Ordinal))
				continue;
			labSid = name.Substring(CloneConfigMarkerPrefix.Length);
			return !string.IsNullOrEmpty(labSid);
		}
		return false;
	}

	static GameObject FindChildByName(GameObject root, string name)
	{
		if (!root || string.IsNullOrEmpty(name))
			return null;
		var transforms = root.GetComponentsInChildren<Transform>(true);
		for (var i = 0; transforms != null && i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (t && string.Equals(t.name, name, StringComparison.Ordinal))
				return t.gameObject;
		}
		return null;
	}

	bool TryRehydrateClone()
	{
		var frame = Time.frameCount;
		if (frame < _nextRehydrateFrame)
			return false;
		_nextRehydrateFrame = frame + 30;

		if (Homm3DiagnosticFlags.IsEnabled("homm3_map_array_bridge_disabled.flag"))
			return false;
		var shell = gameObject;
		if (!shell)
			return false;
		if (!TryResolveCloneLabSid(shell, out var labSid))
			return false;
		var mapVisual = FindChildByName(shell, VisualRootName);
		if (!mapVisual)
		{
			LogRehydrateMiss("missing-map-visual", labSid);
			return false;
		}
		if (!EsquirePikemanVisuals.TryFindLoadedUnitStyleHexLitMapDonor(Plugin.LogSource, out var donorMaterial) || !donorMaterial)
		{
			LogRehydrateMiss("missing-hexlit-donor", labSid);
			return false;
		}
		var transplantTarget = Homm3ImportVisuals.FindBestNativeMapTransplantRenderer(shell, mapVisual.transform, preferFlatMeshSlot: true);
		_controllerVisible = true;
		_allowSourceDrawWhilePending = false;
		if (!Configure(shell, mapVisual, transplantTarget, donorMaterial, labSid, Plugin.LogSource))
		{
			LogRehydrateMiss("configure-failed", labSid);
			return false;
		}
		if (_rehydrateDiagRemaining > 0)
		{
			_rehydrateDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3 map array slice bridge: rehydrated cloned shell labSid='"
				+ labSid
				+ "' shell='"
				+ (shell.name ?? "?")
				+ "' target='"
				+ (_targetRenderer ? _targetRenderer.name : "?")
				+ "'.");
		}
		Homm3MapLoadFlightRecorder.MarkGameObject("map-array-bridge.clone-rehydrate.ok", shell, "labSid=" + labSid, census: true);
		return true;
	}

	bool NeedsRehydrate()
	{
		if (!_targetRenderer || !_sourceRenderer || !_arrayBillboard || !_hexLitMaterial || !_sliceTexture)
			return true;
		if (string.IsNullOrEmpty(_labSid))
			return true;
		if (!HasLiveSourceArrayTexture())
			return true;
		return HasSyntheticTargetSidMismatch();
	}

	bool HasLiveSourceArrayTexture()
	{
		if (!_sourceRenderer)
			return false;
		_arraySourceMpb ??= new MaterialPropertyBlock();
		_sourceRenderer.GetPropertyBlock(_arraySourceMpb);
		return HasArrayTexture(_arraySourceMpb)
		       || HasArrayTexture(_arraySourceMaterial)
		       || HasCachedArrayTexture();
	}

	bool HasCachedArrayTexture()
	{
		for (var i = 0; i < _arrayTextureCache.Length; i++)
		{
			if (_arrayTextureCache[i])
				return true;
		}
		return false;
	}

	static bool HasArrayTexture(Material mat)
	{
		if (!mat)
			return false;
		return GetArrayTexture(mat, MainTexArrayId)
		       || GetArrayTexture(mat, MainTexArray1Id)
		       || GetArrayTexture(mat, MainTexArray2Id)
		       || GetArrayTexture(mat, MainTexArray3Id);
	}

	static bool HasArrayTexture(MaterialPropertyBlock mpb)
	{
		if (mpb == null)
			return false;
		return GetArrayTexture(mpb, MainTexArrayId)
		       || GetArrayTexture(mpb, MainTexArray1Id)
		       || GetArrayTexture(mpb, MainTexArray2Id)
		       || GetArrayTexture(mpb, MainTexArray3Id);
	}

	bool HasSyntheticTargetSidMismatch()
	{
		if (!gameObject || string.IsNullOrEmpty(_labSid))
			return false;
		return TryReadSyntheticTargetLabSid(gameObject, out var targetSid)
		       && !string.Equals(_labSid, targetSid, StringComparison.Ordinal);
	}

	bool TryResolveCloneLabSid(GameObject shell, out string labSid)
	{
		if (TryReadSyntheticTargetLabSid(shell, out labSid))
			return true;
		labSid = _labSid;
		if (!string.IsNullOrEmpty(labSid))
			return true;
		if (CloneRehydrateEnabled() && TryReadCloneConfigMarker(shell, out labSid))
			return true;
		labSid = null;
		return false;
	}

	static bool CloneRehydrateEnabled() => Homm3DiagnosticFlags.IsEnabled(CloneRehydrateEnabledFlag);

	static void LogRehydrateMiss(string reason, string labSid)
	{
		if (_rehydrateDiagRemaining <= 0)
			return;
		_rehydrateDiagRemaining--;
		Plugin.LogSource?.LogWarning(
			"Homm3 map array slice bridge: clone rehydrate skipped reason='"
			+ reason
			+ "' labSid='"
			+ (labSid ?? "?")
			+ "'.");
	}

	Renderer EnsureFlatSliceTarget(
		GameObject shell,
		Renderer requestedTarget,
		Renderer sourceRenderer,
		string labSid,
		BepInEx.Logging.ManualLogSource log)
	{
		_targetIsSyntheticFlatRenderer = false;
		var requestedSyntheticTarget = requestedTarget
		                               && requestedTarget.gameObject
		                               && IsSyntheticFlatTargetName(requestedTarget.gameObject.name);
		if (requestedTarget && !requestedSyntheticTarget && Homm3ImportVisuals.TryAsMeshRenderer(requestedTarget) != null)
			return requestedTarget;
		if (!shell || !sourceRenderer)
			return requestedTarget;

		var existing = requestedSyntheticTarget
			? requestedTarget.transform
			: FindSyntheticFlatTarget(shell.transform);
		GameObject targetGo;
		if (existing)
		{
			targetGo = existing.gameObject;
		}
		else
		{
			targetGo = new GameObject(SyntheticFlatTargetName);
			targetGo.transform.SetParent(shell.transform, false);
		}

		targetGo.name = BuildSyntheticFlatTargetName(labSid);
		targetGo.layer = requestedTarget ? requestedTarget.gameObject.layer : sourceRenderer.gameObject.layer;
		var mf = targetGo.GetComponent<MeshFilter>();
		if (!mf)
			mf = targetGo.AddComponent<MeshFilter>();
		var mr = targetGo.GetComponent<MeshRenderer>();
		if (!mr)
			mr = targetGo.AddComponent<MeshRenderer>();

		var sourceMesh = ResolveSourceMesh(sourceRenderer);
		if (sourceMesh)
			mf.sharedMesh = sourceMesh;
		CopyRendererFlags(requestedTarget ? requestedTarget : sourceRenderer, mr);
		mr.enabled = false;
		mr.forceRenderingOff = true;
		_targetIsSyntheticFlatRenderer = true;
		if (IsMapArrayBridgeDiagnosticEnabled() && _attachDiagRemaining > 0)
		{
			log?.LogInfo(
				"Homm3 map array slice bridge: using synthetic flat target because native target='"
				+ (requestedTarget ? requestedTarget.name : "(null)")
				+ "' type="
				+ Homm3ImportVisuals.DescribeMapRenderer(requestedTarget)
				+ ".");
		}
		return mr;
	}

	static Transform FindSyntheticFlatTarget(Transform shell)
	{
		if (!shell)
			return null;
		for (var i = 0; i < shell.childCount; i++)
		{
			var child = shell.GetChild(i);
			if (child && IsSyntheticFlatTargetName(child.name))
				return child;
		}
		return null;
	}

	internal static bool IsSyntheticFlatTargetName(string name)
	{
		return string.Equals(name, SyntheticFlatTargetName, StringComparison.Ordinal)
		       || (!string.IsNullOrEmpty(name)
		           && name.StartsWith(SyntheticFlatTargetName + SyntheticFlatTargetSidSeparator, StringComparison.Ordinal));
	}

	static string BuildSyntheticFlatTargetName(string labSid)
	{
		return string.IsNullOrEmpty(labSid)
			? SyntheticFlatTargetName
			: SyntheticFlatTargetName + SyntheticFlatTargetSidSeparator + labSid;
	}

	static bool TryReadSyntheticTargetLabSid(GameObject shell, out string labSid)
	{
		labSid = null;
		var target = shell ? FindSyntheticFlatTarget(shell.transform) : null;
		var name = target ? target.name : null;
		var prefix = SyntheticFlatTargetName + SyntheticFlatTargetSidSeparator;
		if (string.IsNullOrEmpty(name) || !name.StartsWith(prefix, StringComparison.Ordinal))
			return false;
		labSid = name.Substring(prefix.Length);
		return !string.IsNullOrEmpty(labSid);
	}

	static Mesh ResolveSourceMesh(Renderer renderer)
	{
		var meshFilter = Homm3ImportVisuals.TryGetMeshFilter(renderer);
		if (meshFilter && meshFilter.sharedMesh)
			return meshFilter.sharedMesh;
		var skinned = Homm3ImportVisuals.TryAsSkinnedMeshRenderer(renderer);
		return skinned ? skinned.sharedMesh : null;
	}

	static void CopyRendererFlags(Renderer source, Renderer target)
	{
		if (!source || !target)
			return;
		target.shadowCastingMode = source.shadowCastingMode;
		target.receiveShadows = source.receiveShadows;
		target.lightProbeUsage = source.lightProbeUsage;
		target.reflectionProbeUsage = source.reflectionProbeUsage;
		target.motionVectorGenerationMode = source.motionVectorGenerationMode;
		target.allowOcclusionWhenDynamic = source.allowOcclusionWhenDynamic;
		target.renderingLayerMask = source.renderingLayerMask;
		target.sortingLayerID = source.sortingLayerID;
		target.sortingOrder = source.sortingOrder;
	}

	internal void ApplyControllerVisibility(bool visible)
	{
		_controllerVisible = visible;
		if (_lastCopiedFrame < 0)
		{
			if (_targetRenderer)
			{
				_targetRenderer.enabled = false;
				_targetRenderer.forceRenderingOff = true;
			}
			if (_sourceRenderer)
			{
				_sourceRenderer.enabled = visible && _allowSourceDrawWhilePending;
				_sourceRenderer.forceRenderingOff = !visible || !_allowSourceDrawWhilePending;
			}
			return;
		}
		if (_targetRenderer)
		{
			_targetRenderer.enabled = visible;
			_targetRenderer.forceRenderingOff = !visible;
		}
		if (_sourceRenderer)
		{
			_sourceRenderer.enabled = false;
			_sourceRenderer.forceRenderingOff = true;
		}
	}

	void DisableAfterFailedAttach()
	{
		enabled = false;
		if (_targetIsSyntheticFlatRenderer && _targetRenderer)
		{
			_targetRenderer.enabled = false;
			_targetRenderer.forceRenderingOff = true;
		}
		if (_sourceRenderer)
		{
			_sourceRenderer.enabled = false;
			_sourceRenderer.forceRenderingOff = true;
		}
	}

	bool EnsureSliceTexture(BepInEx.Logging.ManualLogSource log)
	{
		if (!TryGetPrimaryArrayTexture(out var array) || !array)
			return false;
		var w = array.width;
		var h = array.height;
		if (w <= 0 || h <= 0)
			return false;
		CreateSliceTexture(w, h, array.filterMode, array.format);
		return _sliceTexture;
	}

	void CreateSliceTexture(int width, int height, FilterMode filterMode, TextureFormat format = TextureFormat.RGBA32)
	{
		width = Mathf.Max(1, width);
		height = Mathf.Max(1, height);
		if (_sliceTexture
		    && _sliceTexture.width == width
		    && _sliceTexture.height == height
		    && _sliceTexture.format == format)
		{
			_sliceTexture.filterMode = filterMode;
			return;
		}
		if (_sliceTexture)
			UnityEngine.Object.Destroy(_sliceTexture);
		try
		{
			_sliceTexture = new Texture2D(width, height, format, false, false)
			{
				name = "homm3_map_array_slice",
				filterMode = filterMode,
				wrapMode = TextureWrapMode.Clamp
			};
		}
		catch
		{
			_sliceTexture = new Texture2D(width, height, TextureFormat.RGBA32, false, false)
			{
				name = "homm3_map_array_slice",
				filterMode = filterMode,
				wrapMode = TextureWrapMode.Clamp
			};
		}
	}

	bool TryGetPrimaryArrayTexture(out Texture2DArray array)
	{
		array = null;
		if (_sourceRenderer)
		{
			_arraySourceMpb ??= new MaterialPropertyBlock();
			_sourceRenderer.GetPropertyBlock(_arraySourceMpb);
			array = GetArrayTexture(_arraySourceMpb, MainTexArrayId)
			        ?? GetArrayTexture(_arraySourceMpb, MainTexArray1Id)
			        ?? GetArrayTexture(_arraySourceMpb, MainTexArray2Id)
			        ?? GetArrayTexture(_arraySourceMpb, MainTexArray3Id);
		}
		if (!array)
			array = GetArrayTexture(_arraySourceMaterial, MainTexArrayId)
			        ?? GetArrayTexture(_arraySourceMaterial, MainTexArray1Id)
			        ?? GetArrayTexture(_arraySourceMaterial, MainTexArray2Id)
			        ?? GetArrayTexture(_arraySourceMaterial, MainTexArray3Id);
		return array;
	}

	void Awake()
	{
		LateUpdate();
	}

	void LateUpdate()
	{
		if (NeedsRehydrate())
		{
			if (!TryRehydrateClone() || NeedsRehydrate())
				return;
		}
		if (gameObject && gameObject.activeInHierarchy && !_controllerVisible)
			_controllerVisible = true;

		if (!_arrayBillboard.TryGetCurrentDisplayFrameIndex(out var globalIndex, out _))
		{
			LogCopyFailure("no-display-frame", -1, null, -1, null);
			return;
		}
		if (globalIndex == _lastCopiedFrame)
		{
			ApplyPresentation();
			return;
		}

		if (!TryCopySlice(globalIndex))
			return;
		_lastCopiedFrame = globalIndex;
		ApplySliceTextureToHexLitMaterial();
		ApplyPresentation();
		LogDiag(globalIndex);
	}

	bool TryCopySlice(int globalIndex)
	{
		if (!_arraySourceMaterial || !_sourceRenderer)
		{
			LogCopyFailure("missing-source", globalIndex, null, -1, null);
			return false;
		}
		if (!TryResolveArraySlice(globalIndex, out var array, out var slice))
		{
			LogCopyFailure("resolve-failed", globalIndex, null, -1, null);
			return false;
		}
		if (!array || slice < 0 || slice >= array.depth)
		{
			LogCopyFailure("invalid-slice", globalIndex, array, slice, null);
			return false;
		}
		if (!_sliceTexture
		    || _sliceTexture.width != array.width
		    || _sliceTexture.height != array.height
		    || _sliceTexture.format != array.format)
			CreateSliceTexture(array.width, array.height, array.filterMode, array.format);
		try
		{
			Graphics.CopyTexture(array, slice, 0, _sliceTexture, 0, 0);
			LogSliceAlphaDiagIfNeeded(globalIndex, array, slice);
			return true;
		}
		catch (Exception ex)
		{
			if (TryCopySliceCpu(array, slice, out var cpuMessage))
			{
				LogSliceAlphaDiagIfNeeded(globalIndex, array, slice);
				return true;
			}
			LogCopyFailure("copy-failed", globalIndex, array, slice, ex.Message + (string.IsNullOrEmpty(cpuMessage) ? string.Empty : " cpu=" + cpuMessage));
			return false;
		}
	}

	void LogSliceAlphaDiagIfNeeded(int globalIndex, Texture2DArray array, int slice)
	{
		if (_sliceAlphaDiagLogged
		    || !IsMapArrayBridgeDiagnosticEnabled()
		    || !string.Equals(_labSid, "toa_goblin_trapper", StringComparison.OrdinalIgnoreCase)
		    || !array)
			return;
		_sliceAlphaDiagLogged = true;

		try
		{
			var pixels = array.GetPixels(slice, 0);
			var nonzero = 0;
			var strong = 0;
			var alphaSum = 0f;
			var alphaMax = 0f;
			if (pixels != null)
			{
				for (var i = 0; i < pixels.Length; i++)
				{
					var a = pixels[i].a;
					if (a > 0.001f)
						nonzero++;
					if (a > 0.5f)
						strong++;
					alphaSum += a;
					if (a > alphaMax)
						alphaMax = a;
				}
			}
			Plugin.LogSource?.LogInfo(
				"Homm3 map array slice bridge: trapper alpha diag frame="
				+ globalIndex
				+ " slice="
				+ slice
				+ " pixels="
				+ (pixels == null ? 0 : pixels.Length)
				+ " alphaNonzero="
				+ nonzero
				+ " alphaStrong="
				+ strong
				+ " alphaAvg="
				+ (pixels == null || pixels.Length == 0 ? 0f : alphaSum / pixels.Length).ToString("0.###")
				+ " alphaMax="
				+ alphaMax.ToString("0.###")
				+ " materialQueue="
				+ (_hexLitMaterial ? _hexLitMaterial.renderQueue : -1)
				+ " targetEnabled="
				+ (_targetRenderer && _targetRenderer.enabled)
				+ " forceOff="
				+ (_targetRenderer && _targetRenderer.forceRenderingOff)
				+ ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("Homm3 map array slice bridge: trapper alpha diag unavailable: " + ex.Message);
		}
	}

	void ApplySliceTextureToHexLitMaterial()
	{
		if (!_hexLitMaterial || !_sliceTexture)
			return;

		for (var i = 0; i < HexLitBillboardTextureSlots.Length; i++)
			SetTextureSlot(_hexLitMaterial, HexLitBillboardTextureSlots[i], _sliceTexture);

		_hexLitMaterial.mainTexture = _sliceTexture;
		_hexLitMaterial.mainTextureScale = Vector2.one;
		_hexLitMaterial.mainTextureOffset = Vector2.zero;
		if (_hexLitMaterial.HasProperty("_Color"))
			_hexLitMaterial.SetColor("_Color", ResolveColorMultiplier());
		if (_hexLitMaterial.HasProperty("_BaseColor"))
			_hexLitMaterial.SetColor("_BaseColor", ResolveColorMultiplier());
		if (_hexLitMaterial.HasProperty("_EmissionColor"))
			_hexLitMaterial.SetColor("_EmissionColor", Color.black);
		SetFloatIfPresent(_hexLitMaterial, "_AlphaClip", 1f);
		SetFloatIfPresent(_hexLitMaterial, "_AlphaCutoff", 0.005f);
		SetFloatIfPresent(_hexLitMaterial, "_Cutoff", 0.005f);
		SetFloatIfPresent(_hexLitMaterial, "_AlphaClipThreshold", 0.005f);
		_hexLitMaterial.EnableKeyword("HEX_ALPHA_CLIP_ENABLED");
		_hexLitMaterial.EnableKeyword("_ALPHATEST_ON");
	}

	Color ResolveColorMultiplier()
	{
		if (string.Equals(_labSid, "toa_goblin_trapper", StringComparison.OrdinalIgnoreCase))
			return new Color(1.45f, 1.45f, 1.45f, 1f);
		return Color.white;
	}

	static void SetTextureSlot(Material material, string propertyName, Texture texture)
	{
		if (!material || string.IsNullOrEmpty(propertyName) || !texture)
			return;
		try
		{
			if (!material.HasProperty(propertyName))
				return;
			material.SetTexture(propertyName, texture);
			material.SetTextureScale(propertyName, Vector2.one);
			material.SetTextureOffset(propertyName, Vector2.zero);
		}
		catch
		{
			// Stripped IL2CPP shader proxies can throw for individual optional slots; the rest still matter.
		}
	}

	static void SetFloatIfPresent(Material material, string propertyName, float value)
	{
		if (!material || string.IsNullOrEmpty(propertyName))
			return;
		try
		{
			if (material.HasProperty(propertyName))
				material.SetFloat(propertyName, value);
		}
		catch
		{
		}
	}

	bool TryCopySliceCpu(Texture2DArray array, int slice, out string message)
	{
		message = null;
		if (!array || !_sliceTexture)
		{
			message = "missing-texture";
			return false;
		}
		try
		{
			if (_sliceTexture.format != TextureFormat.RGBA32)
				CreateSliceTexture(array.width, array.height, array.filterMode, TextureFormat.RGBA32);
			var pixels = array.GetPixels(slice, 0);
			if (pixels == null || pixels.Length == 0)
			{
				message = "empty-pixels";
				return false;
			}
			_sliceTexture.SetPixels(pixels);
			_sliceTexture.Apply(false, false);
			return true;
		}
		catch (Exception ex)
		{
			message = ex.Message;
			return false;
		}
	}

	bool TryResolveArraySlice(int globalIndex, out Texture2DArray array, out int slice)
	{
		array = null;
		slice = 0;
		if (globalIndex < 0)
			return false;
		_arraySourceMpb ??= new MaterialPropertyBlock();
		_sourceRenderer.GetPropertyBlock(_arraySourceMpb);

		var chunk = Mathf.Max(1, _arraySliceSize);
		if (globalIndex < chunk)
		{
			array = ResolveArrayTexture(MainTexArrayId, 0);
			slice = globalIndex;
			return array;
		}
		globalIndex -= chunk;
		if (globalIndex < chunk)
		{
			array = ResolveArrayTexture(MainTexArray1Id, 1);
			slice = globalIndex;
			return array;
		}
		globalIndex -= chunk;
		if (globalIndex < chunk)
		{
			array = ResolveArrayTexture(MainTexArray2Id, 2);
			slice = globalIndex;
			return array;
		}
		globalIndex -= chunk;
		array = ResolveArrayTexture(MainTexArray3Id, 3);
		slice = globalIndex;
		return array;
	}

	Texture2DArray ResolveArrayTexture(int propertyId, int cacheIndex)
	{
		var array = GetArrayTexture(_arraySourceMpb, propertyId) ?? GetArrayTexture(_arraySourceMaterial, propertyId);
		if (array && cacheIndex >= 0 && cacheIndex < _arrayTextureCache.Length)
			_arrayTextureCache[cacheIndex] = array;
		if (!array && cacheIndex >= 0 && cacheIndex < _arrayTextureCache.Length)
			array = _arrayTextureCache[cacheIndex];
		return array;
	}

	static Texture2DArray GetArrayTexture(Material mat, int propertyId)
	{
		if (!mat || !mat.HasProperty(propertyId))
			return null;
		return mat.GetTexture(propertyId) as Texture2DArray;
	}

	static Texture2DArray GetArrayTexture(MaterialPropertyBlock mpb, int propertyId)
	{
		if (mpb == null)
			return null;
		return mpb.GetTexture(propertyId) as Texture2DArray;
	}

	void ApplyPresentation()
	{
		TryCopyMeshFromSourceToTarget();
		SyncBillboardTransformFromSourceToTarget();
		if (!_presentationMaterialBound || _targetRenderer.sharedMaterial != _hexLitMaterial)
		{
			_targetRenderer.sharedMaterial = _hexLitMaterial;
			_presentationMaterialBound = true;
		}
		if (!_presentationMpbCleared)
		{
			_targetRenderer.SetPropertyBlock(null);
			_presentationMpbCleared = true;
		}
		_targetRenderer.enabled = _controllerVisible;
		_targetRenderer.forceRenderingOff = !_controllerVisible;
		if (_sourceRenderer)
		{
			_sourceRenderer.enabled = false;
			_sourceRenderer.forceRenderingOff = true;
		}
	}

	bool TryCopyMeshFromSourceToTarget()
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
		if (srcMeshId == _lastSourceMeshId)
			return true;
		_lastSourceMeshId = srcMeshId;

		var tgtSkinned = Homm3ImportVisuals.TryAsSkinnedMeshRenderer(_targetRenderer);
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

	void SyncBillboardTransformFromSourceToTarget()
	{
		if (!_sourceRenderer || !_targetRenderer)
			return;
		var src = _sourceRenderer.transform;
		var tgt = _targetRenderer.transform;
		var posHash = HashVector3(src.position);
		var rotHash = HashQuaternion(src.rotation);
		var scaleHash = HashVector3(src.lossyScale);
		var parentScaleHash = HashVector3(tgt.parent ? tgt.parent.lossyScale : Vector3.one);
		if (posHash == _lastSyncedSourcePosHash
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

	static int HashVector3(Vector3 v)
	{
		unchecked
		{
			var x = (int)(v.x * 1000f);
			var y = (int)(v.y * 1000f);
			var z = (int)(v.z * 1000f);
			return (x * 73856093) ^ (y * 19349663) ^ (z * 83492791);
		}
	}

	static int HashQuaternion(Quaternion q)
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

	void LogDiag(int globalIndex)
	{
		if (!IsMapArrayBridgeDiagnosticEnabled())
			return;
		if (_sliceCopyDiagRemaining <= 0)
			return;
		_sliceCopyDiagRemaining--;
		Plugin.LogSource?.LogInfo(
			"Homm3 map array slice bridge: frame="
			+ globalIndex
			+ " targetShader="
			+ (_hexLitMaterial && _hexLitMaterial.shader ? _hexLitMaterial.shader.name : "?")
			+ " sliceTex="
			+ (_sliceTexture ? _sliceTexture.width + "x" + _sliceTexture.height + " " + _sliceTexture.format : "(null)")
			+ " sourceArray="
			+ DescribePrimaryArrayForDiag()
			+ ".");
	}

	string DescribePrimaryArrayForDiag()
	{
		if (!TryResolveArraySlice(Mathf.Max(0, _lastCopiedFrame), out var array, out var slice) || !array)
			return "(null)";
		return array.width + "x" + array.height + "x" + array.depth + " " + array.format + " slice=" + slice;
	}

	void LogCopyFailure(string reason, int globalIndex, Texture2DArray array, int slice, string detail)
	{
		if (!IsMapArrayBridgeDiagnosticEnabled())
			return;
		if (_copyFailureDiagRemaining <= 0)
			return;
		_copyFailureDiagRemaining--;
		Plugin.LogSource?.LogWarning(
			"Homm3 map array slice bridge: copy skipped reason='"
			+ reason
			+ "' labSid='"
			+ (_labSid ?? "?")
			+ "' frame="
			+ globalIndex
			+ " chunk="
			+ _arraySliceSize
			+ " sourceRenderer='"
			+ (_sourceRenderer ? _sourceRenderer.name : "(none)")
			+ "' sourceMaterial='"
			+ (_arraySourceMaterial ? _arraySourceMaterial.name : "(none)")
			+ "' slots=["
			+ DescribeArraySlotsForFailureDiag()
			+ "]"
			+ " array="
			+ (array ? array.name + " " + array.width + "x" + array.height + "x" + array.depth : "(null)")
			+ " slice="
			+ slice
			+ (string.IsNullOrEmpty(detail) ? string.Empty : " detail='" + detail + "'")
			+ ".");
	}

	static bool IsMapArrayBridgeDiagnosticEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_map_array_bridge_diag.flag");
	}

	string DescribeArraySlotsForFailureDiag()
	{
		try
		{
			_arraySourceMpb ??= new MaterialPropertyBlock();
			if (_sourceRenderer)
				_sourceRenderer.GetPropertyBlock(_arraySourceMpb);
			return string.Join(
				";",
				new[]
				{
					DescribeArraySlot("_MainTexArray", MainTexArrayId, 0),
					DescribeArraySlot("_MainTexArray1", MainTexArray1Id, 1),
					DescribeArraySlot("_MainTexArray2", MainTexArray2Id, 2),
					DescribeArraySlot("_MainTexArray3", MainTexArray3Id, 3)
				});
		}
		catch (Exception ex)
		{
			return "failed:" + ex.GetType().Name;
		}
	}

	string DescribeArraySlot(string name, int propertyId, int cacheIndex)
	{
		var mpb = GetArrayTexture(_arraySourceMpb, propertyId);
		var mat = GetArrayTexture(_arraySourceMaterial, propertyId);
		var cache = cacheIndex >= 0 && cacheIndex < _arrayTextureCache.Length ? _arrayTextureCache[cacheIndex] : null;
		return name + "{mpb=" + DescribeArrayTexture(mpb) + ",mat=" + DescribeArrayTexture(mat) + ",cache=" + DescribeArrayTexture(cache) + "}";
	}

	static string DescribeArrayTexture(Texture2DArray array)
	{
		if (!array)
			return "(null)";
		return (array.name ?? "?") + ":" + array.width + "x" + array.height + "x" + array.depth + ":" + array.format;
	}

	void OnDestroy()
	{
		if (_sliceTexture)
			UnityEngine.Object.Destroy(_sliceTexture);
		if (_hexLitMaterial)
			UnityEngine.Object.Destroy(_hexLitMaterial);
	}
}
