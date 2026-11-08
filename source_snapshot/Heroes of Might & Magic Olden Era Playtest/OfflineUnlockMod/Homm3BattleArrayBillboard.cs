using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Option D prototype: drives battle flip-book frames via Texture2DArray + MaterialPropertyBlock
/// while native Animator clips supply timing only.
/// </summary>
public sealed class Homm3BattleArrayBillboard : MonoBehaviour
{
	const int GroupAttackUp = 11;
	const int GroupAttackFront = 12;
	const int GroupAttackDown = 13;
	const int GroupShootUp = 14;
	const int GroupShootFront = 15;
	const int GroupShootDown = 16;

	static readonly int MainTexArrayId = Shader.PropertyToID("_MainTexArray");
	static readonly int MainTexArray1Id = Shader.PropertyToID("_MainTexArray1");
	static readonly int MainTexArray2Id = Shader.PropertyToID("_MainTexArray2");
	static readonly int MainTexArray3Id = Shader.PropertyToID("_MainTexArray3");
	static readonly int FrameIndexId = Shader.PropertyToID("_FrameIndex");
	static readonly int FrameIndexOffsetId = Shader.PropertyToID("_FrameIndexOffset");
	static readonly int ArraySliceSizeId = Shader.PropertyToID("_ArraySliceSize");

	static readonly Dictionary<string, Homm3BattleArrayManifestData> ManifestByLabSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, Homm3BattleArrayManifestData> MapManifestByLabSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, float> PlaybackFpsByLabSid = new(StringComparer.Ordinal);
	static readonly Dictionary<string, float> MapPlaybackFpsByLabSid = new(StringComparer.Ordinal);
	static bool _typeRegistered;
	static int _playbackFpsDiagRemaining = 8;

	Homm3BattleArrayManifestData _manifest;
	float _playbackFps;
	Renderer _renderer;
	Animator _animator;
	MaterialPropertyBlock _mpb;
	int _frameIndexOffset;
	Vector3 _attackTargetWorldPosition;
	float _attackTargetUntil;
	bool _hasAttackTargetWorldPosition;
	Camera _camera;
	string _labSid;
	Vector3 _authoredQuadLocalScale = Vector3.one;
	Vector3 _authoredQuadLocalPosition;
	bool _capturedQuadTransform;
	bool _playbackSpeedScaled;
	float _playbackSpeedScale = 1f;
	float _animatorSpeedBeforeScale = 1f;
	Dictionary<int, Homm3BattleArrayClipDef> _clipDefByShortNameHash;
	int _cachedStateShortNameHash;
	Homm3BattleArrayClipDef _cachedClipDef;
	int _displayGlobalFrameIndex = -1;
	int _displayFrameIndexOffset;
	bool _isMapVisual;

	public Homm3BattleArrayBillboard(IntPtr ptr) : base(ptr) { }

	void OnDestroy()
	{
		if (_playbackSpeedScaled && _animator)
			_animator.speed = _animatorSpeedBeforeScale;
	}

	internal static bool IsArrayPrototypeLabSid(string labSid) =>
		!string.IsNullOrEmpty(labSid) && TryLoadManifest(labSid, null, out _);

	internal static bool IsMapArrayPrototypeLabSid(string labSid) =>
		!string.IsNullOrEmpty(labSid) && TryLoadMapManifest(labSid, null, out _);

	internal static bool IsMapArrayPilotReady(string labSid, Homm3ImportVisuals.Entry entry, ManualLogSource log)
	{
		if (!IsMapArrayPrototypeLabSid(labSid) || entry == null || string.IsNullOrEmpty(entry.BundleName))
			return false;
		var bundle = Homm3ImportVisuals.TryGetLoadedBundle(entry.BundleName, log);
		if (!bundle)
			return false;
		try
		{
			var names = bundle.GetAllAssetNames();
			if (names == null)
				return false;
			for (var i = 0; i < names.Length; i++)
			{
				var assetName = names[i];
				if (string.IsNullOrEmpty(assetName)
				    || assetName.IndexOf("map_array", StringComparison.OrdinalIgnoreCase) < 0
				    || !assetName.EndsWith(".mat", StringComparison.OrdinalIgnoreCase))
					continue;
				var mat = bundle.LoadAsset<Material>(assetName);
				if (mat && Homm3ImportVisuals.IsHomm3MapArrayBillboardMaterial(mat))
					return true;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle array billboard: map-array pilot bundle scan failed for '" + entry.BundleName + "': " + ex.Message);
		}
		return false;
	}

	internal static void PrewarmManifestForLabSid(string labSid, ManualLogSource log)
	{
		if (string.IsNullOrEmpty(labSid))
			return;
		TryLoadManifest(labSid, log, out _);
	}

	internal static void TryAttach(GameObject battleRoot, Homm3ImportVisuals.Entry entry, ManualLogSource log)
	{
		if (!battleRoot || entry == null)
			return;
		var labSid = Homm3ImportVisuals.TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3BattleArrayBillboard>();
				_typeRegistered = true;
				log?.LogInfo("Homm3 battle array billboard: registered Il2Cpp type.");
			}
			if (battleRoot.GetComponent<Homm3BattleArrayBillboard>() != null)
				return;
			if (!TryLoadManifest(labSid, log, out var manifest))
				return;
			var c = battleRoot.AddComponent<Homm3BattleArrayBillboard>();
			c._labSid = labSid;
			c._manifest = manifest;
			c._playbackFps = ResolvePlaybackFps(labSid, manifest, log);
			c._isMapVisual = false;
			c._renderer = FindBattleQuadRenderer(battleRoot);
			Homm3ArrayUpscaleShaderSupport.TryApply(c._renderer, log);
			if (IsBattleArrayBillboardDiagnosticEnabled())
				log?.LogInfo(
					"Homm3 battle array billboard: attached labSid='"
					+ labSid
					+ "' frames="
					+ manifest.frameCount
					+ " clips="
					+ (manifest.clips?.Length ?? 0)
					+ ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle array billboard: attach failed labSid='" + labSid + "': " + ex.Message);
		}
	}

	internal static void TryAttachForMapVisual(GameObject mapRoot, string labSid, ManualLogSource log)
	{
		if (!mapRoot || string.IsNullOrEmpty(labSid))
			return;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3BattleArrayBillboard>();
				_typeRegistered = true;
				log?.LogInfo("Homm3 map array billboard: registered Il2Cpp type.");
			}
			if (!TryLoadMapManifest(labSid, log, out var manifest))
				return;
			var c = mapRoot.GetComponent<Homm3BattleArrayBillboard>();
			var created = false;
			if (!c)
			{
				c = mapRoot.AddComponent<Homm3BattleArrayBillboard>();
				created = true;
			}
			c._labSid = labSid;
			c._manifest = manifest;
			c._playbackFps = ResolveMapPlaybackFps(labSid, manifest, log);
			c._isMapVisual = true;
			c._renderer = FindBattleQuadRenderer(mapRoot);
			c._animator = c.GetComponent<Animator>() ?? c.GetComponentInChildren<Animator>(true);
			c._mpb ??= new MaterialPropertyBlock();
			c._cachedClipDef = null;
			c._cachedStateShortNameHash = 0;
			c._displayGlobalFrameIndex = -1;
			c._displayFrameIndexOffset = 0;
			c.CaptureAuthoredQuadTransform();
			c.BuildClipDefHashLookup();
			c.SeedInitialMapDisplayFrame();
			c.EnsureMapAnimatorPlaying(log);
			c.LateUpdate();
			var shaderName = c._renderer && c._renderer.sharedMaterial && c._renderer.sharedMaterial.shader
				? c._renderer.sharedMaterial.shader.name
				: "?";
			if (IsMapArrayBillboardDiagnosticEnabled())
			{
				log?.LogInfo(
					"Homm3 map array billboard: attached labSid='"
					+ labSid
					+ "' frames="
					+ manifest.frameCount
					+ " playbackFps="
					+ c._playbackFps.ToString(CultureInfo.InvariantCulture)
					+ " shader="
					+ shaderName
					+ " mode="
					+ (created ? "created" : "refreshed")
					+ " renderer='"
					+ (c._renderer ? c._renderer.name : "?")
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 map array billboard: attach failed labSid='" + labSid + "': " + ex.Message);
		}
	}

	internal static bool TryApplyAttackDirection(GameObject battleRoot, Vector3 targetWorldPosition, float durationSeconds)
	{
		if (!battleRoot)
			return false;
		var helper = battleRoot.GetComponent<Homm3BattleArrayBillboard>();
		if (helper == null || !helper)
			return false;
		helper.ApplyAttackDirection(targetWorldPosition, durationSeconds);
		return true;
	}

	static bool IsMapArrayBillboardDiagnosticEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_map_array_bridge_diag.flag");
	}

	static bool IsBattleArrayBillboardDiagnosticEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag");
	}

	void Awake()
	{
		_renderer = FindBattleQuadRenderer(gameObject);
		_animator = GetComponent<Animator>() ?? GetComponentInChildren<Animator>(true);
		_mpb = new MaterialPropertyBlock();
		CaptureAuthoredQuadTransform();
		BuildClipDefHashLookup();
		EnsureMapAnimatorPlaying(null);
	}

	void EnsureMapAnimatorPlaying(ManualLogSource log)
	{
		if (!_animator)
			_animator = GetComponent<Animator>() ?? GetComponentInChildren<Animator>(true);
		if (!_animator)
		{
			if (log != null && _playbackFpsDiagRemaining > 0)
				log.LogWarning("Homm3 map array billboard: no Animator on '" + (gameObject ? gameObject.name : "?") + "'.");
			return;
		}

		_animator.enabled = true;
		_animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
		_animator.Play(MapAdventureWalkClipName, 0, 0f);
	}

	void BuildClipDefHashLookup()
	{
		_clipDefByShortNameHash = null;
		if (_manifest?.clips == null || _manifest.clips.Length == 0)
			return;
		_clipDefByShortNameHash = new Dictionary<int, Homm3BattleArrayClipDef>(_manifest.clips.Length);
		for (var i = 0; i < _manifest.clips.Length; i++)
		{
			var candidate = _manifest.clips[i];
			if (candidate == null || string.IsNullOrEmpty(candidate.name))
				continue;
			_clipDefByShortNameHash[Animator.StringToHash(candidate.name)] = candidate;
		}
	}

	void ApplyAttackDirection(Vector3 targetWorldPosition, float durationSeconds)
	{
		_attackTargetWorldPosition = targetWorldPosition;
		_attackTargetUntil = Time.time + Mathf.Max(0.2f, durationSeconds);
		_hasAttackTargetWorldPosition = true;
		_frameIndexOffset = 0;
	}

	void LateUpdate()
	{
		if (!_renderer || _manifest?.clips == null || _manifest.clips.Length == 0)
			return;
		CaptureAuthoredQuadTransform();
		if (!_animator)
			_animator = GetComponent<Animator>() ?? GetComponentInChildren<Animator>(true);
		if (!_animator)
			return;

		var stateInfo = _animator.GetCurrentAnimatorStateInfo(0);
		if (!TryResolveActiveClipDef(stateInfo, out var clipDef))
			return;

		var normalized = stateInfo.normalizedTime;
		if (clipDef.loop != 0)
			normalized -= Mathf.Floor(normalized);
		else if (normalized > 1f)
			normalized = 1f;
		var frameCount = clipDef.indices != null ? clipDef.indices.Length : 0;
		var localFrame = 0;
		if (frameCount > 0)
		{
			var builtFps = ResolveBuiltClipFrameRate(clipDef);
			var playbackFps = _playbackFps > 0f ? _playbackFps : ResolvePlaybackFps(_labSid, _manifest, null);
			// Rebaked bundles should match playbackFps (no scale). Legacy 120fps timing clips still need 0.5x.
			ApplyPlaybackSpeedScale(builtFps, playbackFps);
			LogTimingDiag(clipDef, stateInfo, frameCount, builtFps, playbackFps);
			var span = Mathf.Max(1, frameCount - 1);
			var sampleNorm = normalized;
			if (clipDef.loop == 0)
				sampleNorm = Mathf.Clamp01(sampleNorm);
			localFrame = Mathf.Clamp(Mathf.FloorToInt(sampleNorm * span + 0.001f), 0, frameCount - 1);
		}
		var globalIndex = clipDef.indices[localFrame];
		_frameIndexOffset = ResolveAttackDirectionOffset(clipDef);
		_displayGlobalFrameIndex = globalIndex + _frameIndexOffset;
		_displayFrameIndexOffset = _frameIndexOffset;
		var mat = _renderer.sharedMaterial;
		if (mat)
		{
			if (!_isMapVisual)
			{
				Homm3ArrayUpscaleShaderSupport.TryApply(_renderer, Plugin.LogSource);
				mat = _renderer.sharedMaterial;
			}
			CopyArrayTexture(mat, _mpb, MainTexArrayId);
			CopyArrayTexture(mat, _mpb, MainTexArray1Id);
			CopyArrayTexture(mat, _mpb, MainTexArray2Id);
			CopyArrayTexture(mat, _mpb, MainTexArray3Id);
			if (_manifest != null && _manifest.arrayChunkSize > 0)
				_mpb.SetFloat(ArraySliceSizeId, _manifest.arrayChunkSize);
			else if (mat.HasProperty(ArraySliceSizeId))
				_mpb.SetFloat(ArraySliceSizeId, mat.GetFloat(ArraySliceSizeId));
		}
		_mpb.SetFloat(FrameIndexId, globalIndex);
		_mpb.SetFloat(FrameIndexOffsetId, _frameIndexOffset);
		_renderer.SetPropertyBlock(_mpb);
	}

	void CaptureAuthoredQuadTransform()
	{
		if (_capturedQuadTransform)
			return;
		var quad = _renderer != null ? _renderer.transform : null;
		if (quad == null)
			quad = gameObject.transform.Find("billboard/quad");
		if (quad == null)
			return;
		var scale = quad.localScale;
		// Timing-only clips used to animate m_LocalScale.x to 1; repair if we captured after that ran.
		if (scale.y >= 6f && Mathf.Abs(scale.x) < scale.y * 0.45f)
		{
			var sign = scale.x >= 0f ? 1f : -1f;
			if (Mathf.Abs(scale.x) <= 1e-5f && Mathf.Abs(_authoredQuadLocalScale.x) > 1e-5f)
				sign = _authoredQuadLocalScale.x >= 0f ? 1f : -1f;
			scale.x = sign * scale.y * (13.5f / 12f);
		}
		_authoredQuadLocalScale = scale;
		_authoredQuadLocalPosition = quad.localPosition;
		if (_authoredQuadLocalScale.sqrMagnitude > 1e-4f)
			_capturedQuadTransform = true;
	}

	internal Renderer GetMapArraySourceRenderer() => _renderer;

	internal bool TryGetCurrentDisplayFrameIndex(out int globalIndex, out int frameIndexOffset)
	{
		globalIndex = _displayGlobalFrameIndex;
		frameIndexOffset = _displayFrameIndexOffset;
		return globalIndex >= 0;
	}

	internal static int ResolveMapArrayChunkSize(string labSid)
	{
		return TryLoadMapManifest(labSid, null, out var manifest) && manifest != null && manifest.arrayChunkSize > 0
			? manifest.arrayChunkSize
			: 2048;
	}

	void SeedInitialMapDisplayFrame()
	{
		if (_displayGlobalFrameIndex >= 0 || _manifest?.clips == null)
			return;
		for (var i = 0; i < _manifest.clips.Length; i++)
		{
			var clip = _manifest.clips[i];
			if (clip?.indices == null || clip.indices.Length == 0)
				continue;
			if (!string.Equals(clip.name, MapAdventureWalkClipName, StringComparison.Ordinal))
				continue;
			_displayGlobalFrameIndex = clip.indices[0];
			_displayFrameIndexOffset = 0;
			return;
		}
	}

	internal static bool TryResolveArraySlice(
		Material mat,
		int globalIndex,
		int arraySliceSize,
		out Texture2DArray array,
		out int slice)
	{
		array = null;
		slice = 0;
		if (!mat || globalIndex < 0)
			return false;
		var chunk = Mathf.Max(1, arraySliceSize);
		if (globalIndex < chunk)
		{
			if (!mat.HasProperty(MainTexArrayId))
				return false;
			array = mat.GetTexture(MainTexArrayId) as Texture2DArray;
			slice = globalIndex;
			return array;
		}
		globalIndex -= chunk;
		if (globalIndex < chunk)
		{
			if (!mat.HasProperty(MainTexArray1Id))
				return false;
			array = mat.GetTexture(MainTexArray1Id) as Texture2DArray;
			slice = globalIndex;
			return array;
		}
		globalIndex -= chunk;
		if (globalIndex < chunk)
		{
			if (!mat.HasProperty(MainTexArray2Id))
				return false;
			array = mat.GetTexture(MainTexArray2Id) as Texture2DArray;
			slice = globalIndex;
			return array;
		}
		globalIndex -= chunk;
		if (!mat.HasProperty(MainTexArray3Id))
			return false;
		array = mat.GetTexture(MainTexArray3Id) as Texture2DArray;
		slice = globalIndex;
		return array;
	}

	static void CopyArrayTexture(Material mat, MaterialPropertyBlock mpb, int propertyId)
	{
		if (!mat.HasProperty(propertyId))
			return;
		var tex = mat.GetTexture(propertyId);
		if (tex)
			mpb.SetTexture(propertyId, tex);
	}

	void RestoreAuthoredQuadTransform()
	{
		if (!_capturedQuadTransform)
			return;
		var quad = _renderer != null ? _renderer.transform : null;
		if (quad == null)
			return;
		var scale = quad.localScale;
		if (Mathf.Abs(scale.x - _authoredQuadLocalScale.x) > 0.05f
		    || Mathf.Abs(scale.y - _authoredQuadLocalScale.y) > 0.05f
		    || Mathf.Abs(scale.z - _authoredQuadLocalScale.z) > 0.05f)
			quad.localScale = _authoredQuadLocalScale;
		var position = quad.localPosition;
		if ((position - _authoredQuadLocalPosition).sqrMagnitude > 1e-4f)
			quad.localPosition = _authoredQuadLocalPosition;
	}

	bool TryResolveActiveClipDef(AnimatorStateInfo stateInfo, out Homm3BattleArrayClipDef clipDef)
	{
		clipDef = null;
		if (_manifest?.clips == null || _manifest.clips.Length == 0)
			return false;

		// Crossfade frames: keep the last resolved clip instead of calling GetCurrentAnimatorClipInfo.
		if (_animator && _animator.IsInTransition(0) && _cachedClipDef != null)
		{
			clipDef = _cachedClipDef;
			return true;
		}

		var stateHash = stateInfo.shortNameHash;
		if (stateHash == _cachedStateShortNameHash && _cachedClipDef != null)
		{
			clipDef = _cachedClipDef;
			return true;
		}

		if (_clipDefByShortNameHash != null
		    && _clipDefByShortNameHash.TryGetValue(stateHash, out clipDef)
		    && clipDef != null)
		{
			CacheActiveClipDef(stateHash, clipDef);
			return true;
		}

		for (var i = 0; i < _manifest.clips.Length; i++)
		{
			var candidate = _manifest.clips[i];
			if (candidate == null || string.IsNullOrEmpty(candidate.name))
				continue;
			if (stateInfo.IsName(candidate.name))
			{
				CacheActiveClipDef(stateHash, candidate);
				clipDef = candidate;
				return true;
			}
		}

		// Rare mismatch (non-manifest state names): resolve once via clip info, then cache by state hash.
		var clipInfos = _animator != null ? _animator.GetCurrentAnimatorClipInfo(0) : null;
		if (clipInfos != null && clipInfos.Length > 0)
		{
			for (var i = 0; i < clipInfos.Length; i++)
			{
				var clipName = clipInfos[i].clip?.name;
				if (string.IsNullOrEmpty(clipName))
					continue;
				if (TryResolveClipDefForAnimatorClip(clipName, out clipDef))
				{
					CacheActiveClipDef(stateHash, clipDef);
					return true;
				}
			}
		}

		return false;
	}

	void CacheActiveClipDef(int stateHash, Homm3BattleArrayClipDef clipDef)
	{
		_cachedStateShortNameHash = stateHash;
		_cachedClipDef = clipDef;
	}

	int ResolveAttackDirectionOffset(Homm3BattleArrayClipDef clipDef)
	{
		if (clipDef.attackBaseGroup < 0 || _manifest.attackGroups == null)
			return 0;
		if (!IsAttackClip(clipDef))
			return 0;
		if (!TryResolveDirectionalAttackGroup(clipDef, out var resolvedGroup))
			return 0;
		if (resolvedGroup == clipDef.attackBaseGroup)
			return 0;
		var baseStart = FindGroupStart(clipDef.attackBaseGroup);
		var resolvedStart = FindGroupStart(resolvedGroup);
		if (baseStart < 0 || resolvedStart < 0)
			return 0;
		return resolvedStart - baseStart;
	}

	bool IsAttackClip(Homm3BattleArrayClipDef clipDef)
	{
		return clipDef != null
		       && clipDef.attackBaseGroup >= 0
		       && (string.Equals(clipDef.name, "14.Attack", StringComparison.Ordinal)
		           || string.Equals(clipDef.name, "15.Skill_1", StringComparison.Ordinal));
	}

	int FindGroupStart(int groupId)
	{
		if (_manifest.attackGroups == null)
			return -1;
		for (var i = 0; i < _manifest.attackGroups.Length; i++)
		{
			var g = _manifest.attackGroups[i];
			if (g != null && g.group == groupId)
				return g.startIndex;
		}
		return -1;
	}

	bool TryResolveDirectionalAttackGroup(Homm3BattleArrayClipDef clipDef, out int attackGroup)
	{
		attackGroup = GroupAttackFront;
		if (!_hasAttackTargetWorldPosition || Time.time > _attackTargetUntil)
		{
			_hasAttackTargetWorldPosition = false;
			return false;
		}
		var cam = GetCamera();
		if (cam == null || !cam || !TryResolveAttackScreenDelta(cam, out var delta))
			return false;
		var threshold = Mathf.Max(8f, Mathf.Abs(delta.x) * 0.18f);
		var attackFamilyGroup = clipDef != null && clipDef.attackBaseGroup >= 0
			? clipDef.attackBaseGroup
			: _manifest.baseAttackGroup;
		var useShoot = IsShootAttackGroup(attackFamilyGroup);
		if (delta.y > threshold)
			attackGroup = useShoot ? GroupShootUp : GroupAttackUp;
		else if (delta.y < -threshold)
			attackGroup = useShoot ? GroupShootDown : GroupAttackDown;
		else
			attackGroup = useShoot ? GroupShootFront : GroupAttackFront;
		if (FindGroupStart(attackGroup) < 0)
			attackGroup = _manifest.baseAttackGroup;
		return true;
	}

	static bool IsShootAttackGroup(int groupId) =>
		groupId == GroupShootUp || groupId == GroupShootFront || groupId == GroupShootDown;

	bool TryResolveAttackScreenDelta(Camera cam, out Vector2 delta)
	{
		delta = default;
		if (cam == null || !cam)
			return false;
		var from = cam.WorldToScreenPoint(transform.position);
		var to = cam.WorldToScreenPoint(_attackTargetWorldPosition);
		if (from.z < 0f || to.z < 0f)
			return false;
		delta = new Vector2(to.x - from.x, to.y - from.y);
		return delta.sqrMagnitude >= 4f;
	}

	Camera GetCamera()
	{
		if (_camera != null && _camera)
			return _camera;
		_camera = Camera.main;
		return _camera != null && _camera ? _camera : null;
	}

	bool TryFindClipDef(string clipName, out Homm3BattleArrayClipDef clipDef)
	{
		clipDef = null;
		if (_manifest?.clips == null)
			return false;
		for (var i = 0; i < _manifest.clips.Length; i++)
		{
			var c = _manifest.clips[i];
			if (c != null && string.Equals(c.name, clipName, StringComparison.Ordinal))
			{
				clipDef = c;
				return true;
			}
		}
		return false;
	}

	bool TryResolveClipDefForAnimatorClip(string clipName, out Homm3BattleArrayClipDef clipDef)
	{
		if (TryFindClipDef(clipName, out clipDef))
			return true;
		var n = clipName.ToLowerInvariant();
		if ((n.Contains("mapidle") || string.Equals(clipName, MapAdventureWalkClipName, StringComparison.Ordinal))
		    && TryFindClipDef(MapAdventureWalkClipName, out clipDef))
			return true;
		if ((n.Contains("fly") || n.Contains("walk") || n.Contains("move") || n.Contains("run"))
		    && TryFindClipDef("01.Walk", out clipDef))
			return true;
		if ((n.Contains("attack") || n.Contains("atk") || n.Contains("shoot"))
		    && TryFindClipDef("14.Attack", out clipDef))
			return true;
		if ((n.Contains("damage") || n.Contains("hit") || n.Contains("wound"))
		    && TryFindClipDef("20.Damage", out clipDef))
			return true;
		if ((n.Contains("death") || n.Contains("die"))
		    && TryFindClipDef("21.Death", out clipDef))
			return true;
		if (TryFindClipDef("22.Idle", out clipDef))
			return true;
		return false;
	}

	static readonly HashSet<string> _timingDiagLogged = new(StringComparer.Ordinal);
	static int _timingDiagRemaining = EnableArrayTimingDiag() ? 60 : 0;

	static bool EnableArrayTimingDiag()
	{
		try
		{
			var v = Environment.GetEnvironmentVariable("HOMM3_ARRAY_TIMING_DIAG");
			return !string.IsNullOrEmpty(v)
			       && !string.Equals(v, "0", StringComparison.OrdinalIgnoreCase)
			       && !string.Equals(v, "false", StringComparison.OrdinalIgnoreCase);
		}
		catch
		{
			return false;
		}
	}

	void LogTimingDiag(Homm3BattleArrayClipDef clipDef, AnimatorStateInfo stateInfo, int frameCount, float builtFps, float playbackFps)
	{
		if (_timingDiagRemaining <= 0 || clipDef == null)
			return;
		var key = (_labSid ?? "?") + "/" + (clipDef.name ?? "?");
		if (!_timingDiagLogged.Add(key))
			return;
		_timingDiagRemaining--;
		AnimationClip activeClip = null;
		var clipInfos = _animator != null ? _animator.GetCurrentAnimatorClipInfo(0) : null;
		if (clipInfos != null && clipInfos.Length > 0)
			activeClip = clipInfos[0].clip;
		var expectedDuration = builtFps > 0f ? (frameCount - 1) / builtFps : -1f;
		UnityEngine.Debug.Log(
			"HOMM3_ARRAY_TIMING_DIAG"
			+ " labSid=" + (_labSid ?? "?")
			+ " clip=" + (clipDef.name ?? "?")
			+ " indices=" + frameCount
			+ " manifestFps=" + clipDef.fps.ToString(CultureInfo.InvariantCulture)
			+ " builtFps=" + builtFps.ToString(CultureInfo.InvariantCulture)
			+ " playbackFps=" + playbackFps.ToString(CultureInfo.InvariantCulture)
			+ " expectedClipLen=" + expectedDuration.ToString("F3", CultureInfo.InvariantCulture)
			+ " activeClipName=" + (activeClip != null ? activeClip.name : "<none>")
			+ " activeClipLen=" + (activeClip != null ? activeClip.length.ToString("F3", CultureInfo.InvariantCulture) : "?")
			+ " activeClipFrameRate=" + (activeClip != null ? activeClip.frameRate.ToString(CultureInfo.InvariantCulture) : "?")
			+ " stateLen=" + stateInfo.length.ToString("F3", CultureInfo.InvariantCulture)
			+ " stateSpeed=" + stateInfo.speed.ToString("F3", CultureInfo.InvariantCulture)
			+ " stateSpeedMult=" + stateInfo.speedMultiplier.ToString("F3", CultureInfo.InvariantCulture)
			+ " animatorSpeed=" + (_animator != null ? _animator.speed.ToString("F3", CultureInfo.InvariantCulture) : "?")
			+ " scaled=" + _playbackSpeedScaled
			+ " scale=" + _playbackSpeedScale.ToString("F3", CultureInfo.InvariantCulture));
	}

	void ApplyPlaybackSpeedScale(float builtFps, float playbackFps)
	{
		if (!_animator || builtFps <= 0f || playbackFps <= 0f)
			return;
		var scale = playbackFps / builtFps;
		if (Mathf.Abs(scale - 1f) < 0.01f)
			return;
		if (!_playbackSpeedScaled)
		{
			_animatorSpeedBeforeScale = _animator.speed;
			_playbackSpeedScale = scale;
			_playbackSpeedScaled = true;
			_animator.speed = _animatorSpeedBeforeScale * _playbackSpeedScale;
			return;
		}
		var expected = _animatorSpeedBeforeScale * _playbackSpeedScale;
		if (Mathf.Abs(_animator.speed - expected) > 0.05f)
		{
			// Game changed battleSpeed; recover the unscaled base before re-applying our factor.
			_animatorSpeedBeforeScale = _animator.speed / _playbackSpeedScale;
			_animator.speed = _animatorSpeedBeforeScale * _playbackSpeedScale;
		}
	}

	float ResolveBuiltClipFrameRate(Homm3BattleArrayClipDef clipDef) =>
		clipDef != null && clipDef.fps > 0f ? clipDef.fps : 60f;

	const string MapAdventureWalkClipName = "MapIdle";

	static float ResolvePlaybackFps(string labSid, Homm3BattleArrayManifestData manifest, ManualLogSource log)
	{
		if (!string.IsNullOrEmpty(labSid) && PlaybackFpsByLabSid.TryGetValue(labSid, out var cached) && cached > 0f)
			return cached;

		var fps = TryReadRifeTargetFps(labSid);
		if (fps <= 0f && manifest?.clips != null)
		{
			for (var i = 0; i < manifest.clips.Length; i++)
			{
				var clip = manifest.clips[i];
				if (clip != null && clip.fps > 0f)
				{
					fps = clip.fps;
					break;
				}
			}
		}
		if (fps <= 0f)
			fps = 60f;

		if (!string.IsNullOrEmpty(labSid))
			PlaybackFpsByLabSid[labSid] = fps;

		if (log != null && _playbackFpsDiagRemaining > 0)
		{
			_playbackFpsDiagRemaining--;
			log.LogInfo(
				"Homm3 battle array billboard: playbackFps="
				+ fps.ToString(CultureInfo.InvariantCulture)
				+ " labSid='"
				+ labSid
				+ "'.");
		}
		return fps;
	}

	static float TryReadRifeTargetFps(string labSid) =>
		TryReadRifeMetaTargetFps(labSid, "extracted_battle", ".rife120_done.json");

	static float TryReadMapRifeTargetFps(string labSid) =>
		TryReadRifeMetaTargetFps(labSid, "extracted_map", ".rife_map_done.json");

	static float TryReadRifeMetaTargetFps(string labSid, string extractFolder, string metaFileName)
	{
		if (string.IsNullOrEmpty(labSid))
			return 0f;
		var relative = Path.Combine("homm3_lab", labSid, extractFolder, metaFileName);
		string path = null;
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(relative, out var startupPath) && File.Exists(startupPath))
			path = startupPath;
		else
		{
			path = Path.Combine(Paths.PluginPath, relative);
			if (!File.Exists(path))
				path = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relative);
		}
		if (!File.Exists(path))
			return 0f;
		try
		{
			var root = JObject.Parse(File.ReadAllText(path));
			var fps = ReadJsonFloat(root, "targetFps", 0f);
			if (fps > 0f)
				return fps;
		}
		catch
		{
			return 0f;
		}
		return 0f;
	}

	static float ResolveMapPlaybackFps(string labSid, Homm3BattleArrayManifestData manifest, ManualLogSource log)
	{
		if (!string.IsNullOrEmpty(labSid) && MapPlaybackFpsByLabSid.TryGetValue(labSid, out var cached) && cached > 0f)
			return cached;

		var fps = TryReadMapRifeTargetFps(labSid);
		if (fps <= 0f && manifest?.clips != null)
		{
			for (var i = 0; i < manifest.clips.Length; i++)
			{
				var clip = manifest.clips[i];
				if (clip != null && clip.fps > 0f)
				{
					fps = clip.fps;
					break;
				}
			}
		}
		if (fps <= 0f)
			fps = 50f;

		if (!string.IsNullOrEmpty(labSid))
			MapPlaybackFpsByLabSid[labSid] = fps;

		if (log != null && _playbackFpsDiagRemaining > 0)
		{
			_playbackFpsDiagRemaining--;
			log.LogInfo(
				"Homm3 map array billboard: playbackFps="
				+ fps.ToString(CultureInfo.InvariantCulture)
				+ " labSid='"
				+ labSid
				+ "'.");
		}
		return fps;
	}

	static bool TryLoadMapManifest(string labSid, ManualLogSource log, out Homm3BattleArrayManifestData manifest)
	{
		manifest = null;
		if (string.IsNullOrEmpty(labSid))
			return false;
		if (MapManifestByLabSid.TryGetValue(labSid, out manifest) && manifest != null)
			return true;
		var relative = Path.Combine(
			"homm3_lab",
			labSid,
			"Generated",
			"MapBillboard",
			"array_map_manifest.json");
		string path = null;
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(relative, out var startupPath)
		    && File.Exists(startupPath))
			path = startupPath;
		else
		{
			path = Path.Combine(Paths.PluginPath, relative);
			if (!File.Exists(path))
				path = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relative);
		}
		if (!File.Exists(path))
			return false;
		try
		{
			manifest = ParseManifest(JObject.Parse(File.ReadAllText(path)));
			if (manifest?.clips == null || manifest.clips.Length == 0)
			{
				log?.LogWarning("Homm3 map array billboard: manifest has no clips for " + labSid);
				return false;
			}
			MapManifestByLabSid[labSid] = manifest;
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 map array billboard: manifest parse failed for " + labSid + ": " + ex.Message);
			return false;
		}
	}

	static Renderer FindBattleQuadRenderer(GameObject root)
	{
		if (!root)
			return null;
		// Map-array frame driver must stay on the hidden HoMM3 quad; transplant copies MPB/material to the native shell slot.
		var visualRoot = root.transform?.Find(Homm3ImportVisuals.MapPrefabVisualChildName);
		if (visualRoot != null)
		{
			var nestedQuad = visualRoot.Find("billboard/quad") ?? visualRoot.Find("quad");
			if (nestedQuad != null)
			{
				var r = nestedQuad.GetComponent<Renderer>();
				if (r)
					return r;
			}
		}
		var quad = root.transform?.Find("billboard/quad");
		if (quad != null)
		{
			var r = quad.GetComponent<Renderer>();
			if (r)
				return r;
		}
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			if (!Homm3ImportVisuals.IsCandidateNativeMapTransplantRenderer(r))
				continue;
			var path = Homm3ImportVisuals.MapPrefabVisualChildName;
			if (r.transform != null
			    && (IsUnderHoMm3Visual(r.transform, path) || string.Equals(r.name, "quad", StringComparison.OrdinalIgnoreCase)))
				return r;
		}
		return null;
	}

	static bool IsUnderHoMm3Visual(Transform t, string visualRootName)
	{
		if (!t || string.IsNullOrEmpty(visualRootName))
			return false;
		for (var cur = t; cur != null; cur = cur.parent)
			if (string.Equals(cur.name, visualRootName, StringComparison.Ordinal))
				return true;
		return false;
	}

	static bool TryLoadManifest(string labSid, ManualLogSource log, out Homm3BattleArrayManifestData manifest)
	{
		manifest = null;
		if (string.IsNullOrEmpty(labSid))
			return false;
		if (ManifestByLabSid.TryGetValue(labSid, out manifest) && manifest != null)
			return true;
		var relative = Path.Combine(
			"homm3_lab",
			labSid,
			"Generated",
			"BillboardAnim",
			"array_battle_manifest.json");
		string path = null;
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(relative, out var startupPath)
		    && File.Exists(startupPath))
			path = startupPath;
		else
		{
			path = Path.Combine(Paths.PluginPath, relative);
			if (!File.Exists(path))
				path = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relative);
		}
		if (!File.Exists(path))
		{
			log?.LogWarning("Homm3 battle array billboard: manifest missing at " + path);
			return false;
		}
		try
		{
			manifest = ParseManifest(JObject.Parse(File.ReadAllText(path)));
			if (manifest?.clips == null || manifest.clips.Length == 0)
			{
				log?.LogWarning("Homm3 battle array billboard: manifest has no clips for " + labSid);
				return false;
			}
			ManifestByLabSid[labSid] = manifest;
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle array billboard: manifest parse failed for " + labSid + ": " + ex.Message);
			return false;
		}
	}

	static Homm3BattleArrayManifestData ParseManifest(JObject root)
	{
		if (root == null)
			return null;
		var data = new Homm3BattleArrayManifestData
		{
			unitSid = ReadJsonString(root, "unitSid"),
			frameCount = ReadJsonInt(root, "frameCount", 0),
			arrayChunkSize = ReadJsonInt(root, "arrayChunkSize", 2048),
			arrayCount = ReadJsonInt(root, "arrayCount", 1),
			baseAttackGroup = ReadJsonInt(root, "baseAttackGroup", 12)
		};
		var attackGroups = ParseJsonArray(root["attackGroups"]);
		if (attackGroups != null)
		{
			var list = new List<Homm3BattleArrayGroupDef>();
			for (var i = 0; i < attackGroups.Count; i++)
			{
				var row = ParseJsonObject(attackGroups[i]);
				if (row == null)
					continue;
				list.Add(new Homm3BattleArrayGroupDef
				{
					group = ReadJsonInt(row, "group", 0),
					startIndex = ReadJsonInt(row, "startIndex", 0),
					length = ReadJsonInt(row, "length", 0)
				});
			}
			data.attackGroups = list.ToArray();
		}
		var clips = ParseJsonArray(root["clips"]);
		if (clips != null)
		{
			var list = new List<Homm3BattleArrayClipDef>();
			for (var i = 0; i < clips.Count; i++)
			{
				var row = ParseJsonObject(clips[i]);
				if (row == null)
					continue;
				var indices = new List<int>();
				var indexArray = ParseJsonArray(row["indices"]);
				if (indexArray != null)
				{
					for (var j = 0; j < indexArray.Count; j++)
					{
						if (TryReadJsonInt(indexArray[j], out var index))
							indices.Add(index);
					}
				}
				list.Add(new Homm3BattleArrayClipDef
				{
					name = ReadJsonString(row, "name"),
					indices = indices.ToArray(),
					fps = ReadJsonFloat(row, "fps", 60f),
					loop = ReadJsonInt(row, "loop", 0),
					attackBaseGroup = ReadJsonInt(row, "attackBaseGroup", -1)
				});
			}
			data.clips = list.ToArray();
		}
		return data;
	}

	static JArray ParseJsonArray(JToken token)
	{
		if (token == null || token.Type != JTokenType.Array)
			return null;
		try
		{
			return JArray.Parse(token.ToString());
		}
		catch
		{
			return null;
		}
	}

	static JObject ParseJsonObject(JToken token)
	{
		if (token == null || token.Type != JTokenType.Object)
			return null;
		try
		{
			return JObject.Parse(token.ToString());
		}
		catch
		{
			return null;
		}
	}

	static string ReadJsonString(JObject obj, string key)
	{
		if (obj == null || string.IsNullOrEmpty(key))
			return null;
		var value = obj[key]?.ToString();
		return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
	}

	static int ReadJsonInt(JObject obj, string key, int defaultValue)
	{
		if (obj == null || string.IsNullOrEmpty(key))
			return defaultValue;
		return TryReadJsonInt(obj[key], out var value) ? value : defaultValue;
	}

	static float ReadJsonFloat(JObject obj, string key, float defaultValue)
	{
		if (obj == null || string.IsNullOrEmpty(key))
			return defaultValue;
		var token = obj[key];
		if (token == null)
			return defaultValue;
		return Homm3JsonNumber.TryParseFloat(token.ToString(), out var value)
			? value
			: defaultValue;
	}

	static bool TryReadJsonInt(JToken token, out int value)
	{
		value = 0;
		if (token == null)
			return false;
		return int.TryParse(token.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
	}
}
