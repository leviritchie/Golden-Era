using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Keeps replacement battle and adventure-map quad billboards camera-facing even when vanilla movement
/// rotates the unit root. The chosen normal may point toward or away from the camera, whichever is
/// closer to the root's authored facing, so existing front/back orientation is preserved.
/// Static map-object town/dwelling billboards use <see cref="TryAttachMapObject"/> so the front
/// always tracks the camera without motion mirroring.
/// </summary>
public sealed class Homm3BattleBillboardCameraFacing : MonoBehaviour
{
	private const string MapUnitBillboardRootName = "homm3_map_visual";
	private const string CustomCityBillboardRootPrefix = "homm3_custom_city_billboard_";
	private const string StrongholdCityBillboardRootName = "homm3_stronghold_city_homm3_billboard";
	private const string StrongholdDwellingBillboardRootName = "homm3_stronghold_dwelling_billboard";
	private static bool _typeRegistered;
	private static int _attachDiagRemaining = 12;
	private static bool _pendingMapObjectMode;

	private Transform _billboard;
	private Transform _quad;
	private Quaternion _authoredLocalRotation = Quaternion.identity;
	private float _baseQuadScaleX;
	private Vector3 _authoredQuadLocalPosition;
	private float _authoredQuadLocalPositionAbsX;
	private Vector3 _lastRootPosition;
	private bool _hasLastRootPosition;
	private Camera _camera;
	private Vector3 _targetFacingWorldPosition;
	private float _targetFacingUntil;
	private bool _hasTargetFacingWorldPosition;
	private bool _lockNormalToCamera;
	private bool _enableMotionFlip = true;
	private Vector3 _lastCameraForward;
	private Vector3 _lastCameraUp;
	private Vector3 _lastFacingRootPosition;
	private Quaternion _lastFacingRootRotation;
	private bool _hasFacingCache;

	public Homm3BattleBillboardCameraFacing(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject battleRoot, ManualLogSource log)
	{
		TryAttachInternal(battleRoot, mapObjectMode: false, log);
	}

	/// <summary>
	/// Attach to a static map-object billboard root (town/dwelling). The component lives on the
	/// billboard transform itself and always faces the camera plane.
	/// </summary>
	internal static void TryAttachMapObject(Transform billboardRoot, ManualLogSource log)
	{
		if (billboardRoot == null || !billboardRoot)
			return;
		if (billboardRoot.Find("quad") == null)
			return;
		_pendingMapObjectMode = true;
		try
		{
			TryAttachInternal(billboardRoot.gameObject, mapObjectMode: true, log);
		}
		finally
		{
			_pendingMapObjectMode = false;
		}
	}

	private static void TryAttachInternal(GameObject host, bool mapObjectMode, ManualLogSource log)
	{
		if (!host || !host.transform)
			return;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3BattleBillboardCameraFacing>();
				_typeRegistered = true;
				if (Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag"))
					log?.LogInfo("Homm3 battle billboard camera-facing: registered Il2Cpp type.");
			}

			if (host.GetComponent<Homm3BattleBillboardCameraFacing>() != null)
				return;

			if (!mapObjectMode && TryResolveBillboardRoot(host.transform) == null)
				return;

			host.AddComponent<Homm3BattleBillboardCameraFacing>();
			if (Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag") && _attachDiagRemaining > 0)
			{
				_attachDiagRemaining--;
				log?.LogInfo(
					"Homm3 battle billboard camera-facing: attached to '"
					+ (host.name ?? "?")
					+ "'"
					+ (mapObjectMode ? " (map-object)." : "."));
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle billboard camera-facing: attach failed: " + ex.Message);
		}
	}

	internal static bool TryApplyTargetFacing(GameObject battleRoot, Vector3 targetWorldPosition, float durationSeconds)
	{
		if (!battleRoot || !battleRoot.transform)
			return false;
		var helper = battleRoot.GetComponent<Homm3BattleBillboardCameraFacing>();
		if (helper == null || !helper)
			return false;
		helper.ApplyTargetFacing(targetWorldPosition, durationSeconds);
		return true;
	}

	private void Awake()
	{
		_lockNormalToCamera = _pendingMapObjectMode;
		_enableMotionFlip = !_pendingMapObjectMode;
		_billboard = _lockNormalToCamera && transform.Find("quad") != null
			? transform
			: TryResolveBillboardRoot(transform);
		if (_billboard != null)
			_authoredLocalRotation = _billboard.localRotation;
		_quad = _billboard != null ? _billboard.Find("quad") : null;
		if (_quad == null)
			_quad = GetComponentInChildren<MeshRenderer>(true)?.transform;
		if (_quad != null)
		{
			_baseQuadScaleX = _quad.localScale.x;
			_authoredQuadLocalPosition = _quad.localPosition;
			_authoredQuadLocalPositionAbsX = Mathf.Abs(_authoredQuadLocalPosition.x);
			ApplyQuadAnchorForScale(_baseQuadScaleX);
		}
		_lastRootPosition = transform.position;
		_hasLastRootPosition = true;
	}

	private void LateUpdate()
	{
		if (_billboard == null || !_billboard)
			return;

		var cam = GetCamera();
		if (cam == null || !cam)
			return;

		var camTr = cam.transform;
		var camForward = camTr.forward;
		var camUp = camTr.up;
		var rootPos = transform.position;
		var rootRot = transform.rotation;
		var motionFlipNeeded = _enableMotionFlip;
		if (_hasFacingCache
		    && !motionFlipNeeded
		    && NearlyEqual(camForward, _lastCameraForward)
		    && NearlyEqual(camUp, _lastCameraUp)
		    && NearlyEqual(rootPos, _lastFacingRootPosition)
		    && NearlyEqual(rootRot, _lastFacingRootRotation))
			return;

		if (_hasFacingCache
		    && motionFlipNeeded
		    && NearlyEqual(camForward, _lastCameraForward)
		    && NearlyEqual(camUp, _lastCameraUp)
		    && NearlyEqual(rootPos, _lastFacingRootPosition)
		    && NearlyEqual(rootRot, _lastFacingRootRotation))
		{
			// Root/camera unchanged — still evaluate motion flip using position delta bookkeeping.
			ApplyCurrentMotionFlip(cam);
			return;
		}

		_lastCameraForward = camForward;
		_lastCameraUp = camUp;
		_lastFacingRootPosition = rootPos;
		_lastFacingRootRotation = rootRot;
		_hasFacingCache = true;

		var toCameraNormal = -camForward;
		if (toCameraNormal.sqrMagnitude < 0.0001f)
			return;
		toCameraNormal.Normalize();

		Vector3 targetNormal;
		if (_lockNormalToCamera)
		{
			targetNormal = toCameraNormal;
		}
		else
		{
			var authoredWorldNormal = rootRot * (_authoredLocalRotation * Vector3.forward);
			targetNormal = Vector3.Dot(authoredWorldNormal, toCameraNormal) >= 0f
				? toCameraNormal
				: -toCameraNormal;
		}

		var up = camUp;
		if (up.sqrMagnitude < 0.0001f || Mathf.Abs(Vector3.Dot(up.normalized, targetNormal)) > 0.98f)
			up = Vector3.up;

		_billboard.rotation = Quaternion.LookRotation(targetNormal, up);
		if (_enableMotionFlip)
			ApplyCurrentMotionFlip(cam);
	}

	private static bool NearlyEqual(Vector3 a, Vector3 b)
	{
		return (a - b).sqrMagnitude < 1e-8f;
	}

	private static bool NearlyEqual(Quaternion a, Quaternion b)
	{
		return (1f - Mathf.Abs(Quaternion.Dot(a, b))) < 1e-6f;
	}

	private void ApplyCurrentMotionFlip(Camera cam)
	{
		if (_quad == null || !_quad || Mathf.Abs(_baseQuadScaleX) <= 1e-5f)
			return;
		var sign = TryResolveTargetFacingSign(cam, out var targetSign)
			? targetSign
			: (TryResolveCurrentMotionSign(cam, out var motionSign) ? motionSign : 1);
		ApplyQuadFacingSign(sign);
	}

	private void ApplyTargetFacing(Vector3 targetWorldPosition, float durationSeconds)
	{
		_targetFacingWorldPosition = targetWorldPosition;
		_targetFacingUntil = Time.time + Mathf.Max(0.2f, durationSeconds);
		_hasTargetFacingWorldPosition = true;
		var cam = GetCamera();
		if (cam != null && cam && TryResolveTargetFacingSign(cam, out var sign))
			ApplyQuadFacingSign(sign);
	}

	private void ApplyQuadFacingSign(int sign)
	{
		if (_quad == null || !_quad || Mathf.Abs(_baseQuadScaleX) <= 1e-5f)
			return;
		var scale = _quad.localScale;
		var targetX = _baseQuadScaleX * sign;
		if (Mathf.Abs(scale.x - targetX) <= 1e-5f)
		{
			ApplyQuadAnchorForScale(targetX);
			return;
		}
		scale.x = targetX;
		_quad.localScale = scale;
		ApplyQuadAnchorForScale(targetX);
	}

	private void ApplyQuadAnchorForScale(float scaleX)
	{
		if (_quad == null || !_quad || _authoredQuadLocalPositionAbsX <= 1e-5f || Mathf.Abs(scaleX) <= 1e-5f)
			return;

		var p = _quad.localPosition;
		var targetX = _authoredQuadLocalPositionAbsX * (scaleX >= 0f ? 1f : -1f);
		if (Mathf.Abs(p.x - targetX) <= 1e-5f)
			return;
		p.x = targetX;
		_quad.localPosition = p;
	}

	private bool TryResolveCurrentMotionSign(Camera cam, out int sign)
	{
		if (!_hasLastRootPosition)
		{
			_lastRootPosition = transform.position;
			_hasLastRootPosition = true;
			sign = 1;
			return false;
		}

		var current = transform.position;
		var delta = current - _lastRootPosition;
		_lastRootPosition = current;
		if (delta.sqrMagnitude < 0.000004f || cam == null || !cam)
		{
			sign = 1;
			return false;
		}

		var axis = ResolveCameraHorizontalAxis(cam);
		var motion = Vector3.Dot(delta, axis);
		if (Mathf.Abs(motion) < 0.0015f)
		{
			sign = 1;
			return false;
		}

		sign = ResolveScreenDirectionSign(motion);
		return true;
	}

	private bool TryResolveTargetFacingSign(Camera cam, out int sign)
	{
		sign = 1;
		if (!_hasTargetFacingWorldPosition || Time.time > _targetFacingUntil || cam == null || !cam)
		{
			_hasTargetFacingWorldPosition = false;
			return false;
		}

		if (TryResolveTargetScreenDelta(cam, out var screenDelta) && Mathf.Abs(screenDelta.x) >= 2f)
		{
			sign = ResolveTargetScreenDirectionSign(screenDelta.x);
			return true;
		}

		var axis = ResolveCameraHorizontalAxis(cam);
		var direction = Vector3.Dot(_targetFacingWorldPosition - transform.position, axis);
		if (Mathf.Abs(direction) < 0.0015f)
			return false;
		sign = ResolveTargetScreenDirectionSign(direction);
		return true;
	}

	private int ResolveScreenDirectionSign(float screenDirection)
	{
		var baseSign = _baseQuadScaleX >= 0f ? 1 : -1;
		var directionSign = screenDirection >= 0f ? 1 : -1;
		return directionSign == baseSign ? 1 : -1;
	}

	private int ResolveTargetScreenDirectionSign(float screenDirection)
	{
		var baseSign = _baseQuadScaleX >= 0f ? 1 : -1;
		var directionSign = screenDirection >= 0f ? 1 : -1;
		return directionSign == baseSign ? 1 : -1;
	}

	private static Vector3 ResolveCameraHorizontalAxis(Camera cam)
	{
		var axis = cam.transform.right;
		axis.y = 0f;
		if (axis.sqrMagnitude < 0.0001f)
			axis = Vector3.right;
		axis.Normalize();
		return axis;
	}

	private bool TryResolveTargetScreenDelta(Camera cam, out Vector2 delta)
	{
		delta = default;
		if (cam == null || !cam)
			return false;
		var from = cam.WorldToScreenPoint(transform.position);
		var to = cam.WorldToScreenPoint(_targetFacingWorldPosition);
		if (from.z < 0f || to.z < 0f)
			return false;
		delta = new Vector2(to.x - from.x, to.y - from.y);
		return delta.sqrMagnitude >= 4f;
	}

	private static Transform TryResolveBillboardRoot(Transform root)
	{
		if (!root)
			return null;

		if (IsMapObjectBillboardRootName(root.name) && root.Find("quad") != null)
			return root;

		var battleBillboard = root.Find("billboard");
		if (battleBillboard != null && battleBillboard.Find("quad") != null)
			return battleBillboard;

		var mapBillboard = root.Find(MapUnitBillboardRootName);
		if (mapBillboard != null && mapBillboard.Find("quad") != null)
			return mapBillboard;

		var nestedMapBillboard = root.Find(MapUnitBillboardRootName + "/billboard");
		if (nestedMapBillboard != null && nestedMapBillboard.Find("quad") != null)
			return nestedMapBillboard;

		var dwellingBillboard = root.Find(StrongholdDwellingBillboardRootName);
		if (dwellingBillboard != null && dwellingBillboard.Find("quad") != null)
			return dwellingBillboard;

		var strongholdCityBillboard = root.Find(StrongholdCityBillboardRootName);
		if (strongholdCityBillboard != null && strongholdCityBillboard.Find("quad") != null)
			return strongholdCityBillboard;

		for (var i = 0; i < root.childCount; i++)
		{
			var child = root.GetChild(i);
			if (child == null || !child || child.name == null)
				continue;
			if (!child.name.StartsWith(CustomCityBillboardRootPrefix, StringComparison.Ordinal))
				continue;
			if (child.Find("quad") != null)
				return child;
		}

		return null;
	}

	private static bool IsMapObjectBillboardRootName(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		if (name == StrongholdDwellingBillboardRootName
		    || name == StrongholdCityBillboardRootName
		    || name == "homm3_artifact_billboard")
			return true;
		return name.StartsWith(CustomCityBillboardRootPrefix, StringComparison.Ordinal);
	}

	private Camera GetCamera()
	{
		if (_camera != null && _camera)
			return _camera;
		_camera = Camera.main;
		if (_camera != null && _camera)
			return _camera;
		var cameras = Camera.allCameras;
		if (cameras == null || cameras.Length == 0)
			return null;
		for (var i = 0; i < cameras.Length; i++)
		{
			var c = cameras[i];
			if (c != null && c && c.isActiveAndEnabled)
			{
				_camera = c;
				return _camera;
			}
		}

		return null;
	}
}
