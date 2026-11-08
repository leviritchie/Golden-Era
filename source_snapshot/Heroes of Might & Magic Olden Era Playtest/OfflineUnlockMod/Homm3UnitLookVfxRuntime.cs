using System;
using System.Collections.Generic;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Runtime half of the def_retarget unit-look VFX delivery (docs/homm3_unit_look_pipeline.md,
/// "def_retarget delivery"). The lab builder (tools/homm3_import/unity_editor/
/// Homm3OwnedSkinnedLabBuild.DefRetarget.cs) bakes every VFX layer into the prefab and the clips,
/// so the native Animator already plays which cell/quad/light is on and when. This component only
/// does what an Animator cannot:
///   - flipbook holders <c>__homm3_vfx_billboard__*</c> face the camera; <c>__homm3_vfx_ground__*</c>
///     lie flat with their far edge away from the camera and their depth stretched by
///     1/sin(camera elevation) so the DEF cell keeps its on-screen aspect. The DEF cells are drawn
///     for the right-facing HoMM3 sprite, so both mirror horizontally when the unit's Orientation
///     node faces screen-left (the HoMM3 right-army mirror);
///   - Sprites/Default is re-resolved by name on the quad materials (bundle shader refs can
///     arrive as FallbackError);
///   - body uvAtlas: a crossfade blends the Animator's <c>_MainTex_ST</c> between two cells, which
///     would show the gutter/neighbour cells; the blended value is snapped to the nearest cell
///     recorded under <c>__homm3_vfx_uvatlas__</c> (localPosition = ST.zw, localScale = ST.xy);
///   - effect lights: range and intensity are authored in unscaled unit space; they are scaled by
///     the unit's world scale (range * s, intensity * s^2, the Hex/Lit point-light 1/d^2 term).
///     A plain Unity point Light is the native carrier: the game's Hex/Lit Lit pass loops over
///     Unity's per-object light list (unity_LightData.y up to 8, unity_LightIndices) into its
///     HexLighting _PunctualLightColors/Positions/Directions arrays, and 1059 native unit VFX light
///     themselves through ParticleSystem Lights (docs/homm3_prebaked_lighting.md). The diag reports
///     the lights on now and the peak since the previous diag line, so a flash inside a clip is
///     not missed by a line written at the clip's first frame.
/// It also writes a bounded diagnostic of the Animator's clip/speed/battleSlowIdle and the
/// VFX state, which is the slice's runtime evidence. Uses only public UnityEngine API.
/// </summary>
public sealed class Homm3UnitLookVfxRuntime : MonoBehaviour
{
	internal const string BillboardPrefix = "__homm3_vfx_billboard__";
	internal const string GroundPrefix = "__homm3_vfx_ground__";
	internal const string LightPrefix = "__homm3_vfx_light__";
	internal const string UvAtlasMarker = "__homm3_vfx_uvatlas__";
	private const float MinGroundSin = 0.2f;
	private static bool _typeRegistered;
	private static int _attachLogs = 24;
	private static int _diagLogs = 400;
	private static Shader _sprites;
	private static bool _spritesMissingLogged;

	private readonly List<Transform> _billboards = new();
	private readonly List<Vector3> _billboardBaseScale = new();
	private Transform _orientation;
	private float _mirror = 1f;
	private readonly List<Transform> _grounds = new();
	private readonly List<Vector3> _groundBaseScale = new();
	private readonly List<Light> _lights = new();
	private readonly List<float> _lightBaseRange = new();
	private readonly List<Vector4> _cells = new();
	private SkinnedMeshRenderer _body;
	private MaterialPropertyBlock _mpb;
	private Animator _animator;
	private Camera _camera;
	private string _lastClip;
	private float _nextDiag;
	private int _snaps;
	private int _lightsPeak;
	private float _lightPeakMax;
	private bool _initialised;

	public Homm3UnitLookVfxRuntime(IntPtr ptr) : base(ptr) { }

	/// <summary>Idempotent; a prefab without any VFX node gets nothing.</summary>
	internal static void TryAttach(GameObject instance, ManualLogSource log)
	{
		if (!instance)
			return;
		try
		{
			if (!HasVfxNodes(instance.transform))
				return;
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3UnitLookVfxRuntime>();
				_typeRegistered = true;
			}
			if (instance.GetComponent<Homm3UnitLookVfxRuntime>() != null)
				return;
			var runtime = instance.AddComponent<Homm3UnitLookVfxRuntime>();
			runtime.Initialise(log);
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3 unit-look VFX: attach failed on '" + (instance ? instance.name : "?") + "': " + ex.Message);
		}
	}

	private static bool HasVfxNodes(Transform root)
	{
		var all = root.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < all.Length; i++)
		{
			var n = all[i] ? all[i].name : null;
			if (n == null)
				continue;
			if (n.StartsWith(BillboardPrefix, StringComparison.Ordinal) || n.StartsWith(GroundPrefix, StringComparison.Ordinal)
			    || n.StartsWith(LightPrefix, StringComparison.Ordinal) || n == UvAtlasMarker)
				return true;
		}
		return false;
	}

	private void Initialise(ManualLogSource log)
	{
		if (_initialised)
			return;
		_initialised = true;
		_mpb = new MaterialPropertyBlock();
		_animator = GetComponentInChildren<Animator>(true);
		var quadRenderers = 0;
		var shaderFixed = 0;
		var all = GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < all.Length; i++)
		{
			var t = all[i];
			if (!t)
				continue;
			var n = t.name ?? "";
			if (n == "Orientation" && !_orientation)
				_orientation = t;
			if (n.StartsWith(BillboardPrefix, StringComparison.Ordinal))
			{
				_billboards.Add(t);
				_billboardBaseScale.Add(t.localScale);
			}
			else if (n.StartsWith(GroundPrefix, StringComparison.Ordinal))
			{
				_grounds.Add(t);
				_groundBaseScale.Add(t.localScale);
			}
			else if (n.StartsWith(LightPrefix, StringComparison.Ordinal))
			{
				var light = t.GetComponent<Light>();
				if (light)
				{
					_lights.Add(light);
					_lightBaseRange.Add(light.range);
				}
				else
					log?.LogError("Homm3 unit-look VFX: light node '" + n + "' has no Light component.");
			}
			else if (n == UvAtlasMarker)
			{
				for (var c = 0; c < t.childCount; c++)
				{
					var cell = t.GetChild(c);
					_cells.Add(new Vector4(cell.localScale.x, cell.localScale.y, cell.localPosition.x, cell.localPosition.y));
				}
			}
		}
		foreach (var holder in _billboards)
			shaderFixed += FixQuadShaders(holder, ref quadRenderers, log);
		foreach (var holder in _grounds)
			shaderFixed += FixQuadShaders(holder, ref quadRenderers, log);
		if (_cells.Count > 0)
		{
			var skins = GetComponentsInChildren<SkinnedMeshRenderer>(true);
			if (skins.Length != 1)
				log?.LogError("Homm3 unit-look VFX: uvAtlas needs exactly one SkinnedMeshRenderer, found " + skins.Length + "; atlas snap disabled.");
			else
				_body = skins[0];
		}
		if (_attachLogs-- > 0)
			log?.LogInfo("Homm3 unit-look VFX: attached to '" + name + "' billboards=" + _billboards.Count + " grounds=" + _grounds.Count
			             + " quadRenderers=" + quadRenderers + " spritesShaderRebound=" + shaderFixed + " lights=" + _lights.Count
			             + " uvAtlasCells=" + _cells.Count + " animator=" + (_animator ? "yes" : "no")
			             + " orientation=" + (_orientation ? "yes" : "no") + ".");
	}

	private static int FixQuadShaders(Transform holder, ref int count, ManualLogSource log)
	{
		if (_sprites == null || !_sprites)
			_sprites = Shader.Find("Sprites/Default");
		var fixedCount = 0;
		var renderers = holder.GetComponentsInChildren<MeshRenderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			count++;
			var m = r.sharedMaterial;
			if (!m)
				continue;
			if (m.shader && m.shader.isSupported && m.shader.name == "Sprites/Default")
				continue;
			if (_sprites == null || !_sprites)
			{
				if (!_spritesMissingLogged)
				{
					_spritesMissingLogged = true;
					log?.LogError("Homm3 unit-look VFX: Sprites/Default is not in this build; flipbook quads keep shader '"
					              + (m.shader ? m.shader.name : "null") + "'.");
				}
				continue;
			}
			m.shader = _sprites;
			fixedCount++;
		}
		return fixedCount;
	}

	private Camera GetCamera()
	{
		if (_camera && _camera.isActiveAndEnabled)
			return _camera;
		_camera = Camera.main;
		if (_camera && _camera.isActiveAndEnabled)
			return _camera;
		var cameras = Camera.allCameras;
		for (var i = 0; cameras != null && i < cameras.Length; i++)
		{
			if (cameras[i] && cameras[i].isActiveAndEnabled)
			{
				_camera = cameras[i];
				return _camera;
			}
		}
		return null;
	}

	private void LateUpdate()
	{
		// Each step is isolated so one failure never silences the others or the diag line;
		// a step that throws is logged (bounded) and retried next frame.
		Step(0);
		Step(1);
		if (_body && _cells.Count > 0)
			Step(2);
		if (_diagLogs > 0)
			Step(3);
	}

	private readonly int[] _stepFailures = new int[4];
	private readonly string[] _stepLastError = new string[4];

	private static readonly string[] StepLabels = { "facing", "lights", "atlas", "diag" };

	// No delegate parameter: members of an injected Il2Cpp type keep to interop-friendly signatures.
	private void Step(int index)
	{
		var label = StepLabels[index];
		try
		{
			switch (index)
			{
				case 0: UpdateFacing(); break;
				case 1: UpdateLights(); break;
				case 2: SnapAtlas(); break;
				default: Diagnose(); break;
			}
		}
		catch (Exception ex)
		{
			_stepFailures[index]++;
			_stepLastError[index] = ex.GetType().Name + ": " + ex.Message;
			if (_stepFailures[index] <= 3)
				Plugin.LogSource?.LogError("Homm3 unit-look VFX: " + label + " failed on '" + name + "' (" + _stepFailures[index] + "): " + _stepLastError[index]);
		}
	}

	private void UpdateFacing()
	{
		var cam = GetCamera();
		if (!cam)
			return;
		var camRot = cam.transform.rotation;
		if (_orientation)
		{
			// Body forward, not Orientation's: the idle-0 mesh faces the fleet bind yaw (-60) inside it.
			var side = Vector3.Dot(Homm3ImportVisuals.OwnedSkinnedBodyRotation(_orientation) * Vector3.forward, cam.transform.right);
			if (Mathf.Abs(side) > 1e-3f)
				_mirror = side >= 0f ? 1f : -1f;
		}
		for (var i = 0; i < _billboards.Count; i++)
		{
			var bb = _billboards[i];
			if (!bb)
				continue;
			bb.rotation = camRot;
			var b = _billboardBaseScale[i];
			bb.localScale = new Vector3(b.x * _mirror, b.y, b.z);
		}
		if (_grounds.Count == 0)
			return;
		var fwd = cam.transform.forward;
		var flat = new Vector3(fwd.x, 0f, fwd.z);
		if (flat.sqrMagnitude < 1e-6f)
			flat = cam.transform.up;
		flat.y = 0f;
		flat.Normalize();
		var sinElevation = Mathf.Max(MinGroundSin, Mathf.Clamp01(-fwd.y));
		var ground = Quaternion.LookRotation(Vector3.down, flat);
		for (var i = 0; i < _grounds.Count; i++)
		{
			var g = _grounds[i];
			if (!g)
				continue;
			g.rotation = ground;
			var b = _groundBaseScale[i];
			g.localScale = new Vector3(b.x * _mirror, b.y / sinElevation, b.z);
		}
	}

	private void UpdateLights()
	{
		var s = Mathf.Abs(transform.lossyScale.x);
		var on = 0;
		for (var i = 0; i < _lights.Count; i++)
		{
			var l = _lights[i];
			if (!l)
				continue;
			l.range = _lightBaseRange[i] * s;
			// The Animator rewrites m_Intensity every frame before LateUpdate, so this is not cumulative.
			l.intensity *= s * s;
			if (IsLit(l))
			{
				on++;
				_lightPeakMax = Mathf.Max(_lightPeakMax, l.intensity);
			}
		}
		_lightsPeak = Math.Max(_lightsPeak, on);
	}

	// A light the renderer can use: component enabled, GameObject active, intensity above zero.
	private static bool IsLit(Light l) => l && l.isActiveAndEnabled && l.intensity > 0f;

	private void SnapAtlas()
	{
		_body.GetPropertyBlock(_mpb);
		var st = _mpb.GetVector("_MainTex_ST");
		var best = 0;
		var bestD = float.MaxValue;
		for (var i = 0; i < _cells.Count; i++)
		{
			var d = (st - _cells[i]).sqrMagnitude;
			if (d < bestD)
			{
				bestD = d;
				best = i;
			}
		}
		if (bestD <= 1e-8f)
			return;
		// No ST in the block (Animator not bound yet) or a crossfade blend: put it on a cell.
		if (st.sqrMagnitude < 1e-12f)
			best = 0;
		_mpb.SetVector("_MainTex_ST", _cells[best]);
		_body.SetPropertyBlock(_mpb);
		_snaps++;
	}

	private void Diagnose()
	{
		var clip = "(no animator)";
		if (_animator)
		{
			try
			{
				var infos = _animator.GetCurrentAnimatorClipInfo(0);
				clip = infos != null && infos.Length > 0 && infos[0].clip ? infos[0].clip.name : "(none)";
			}
			catch (Exception ex)
			{
				clip = "(clipInfo " + ex.GetType().Name + ")";
			}
		}
		if (clip == _lastClip && Time.time < _nextDiag)
			return;
		var prevClip = _lastClip ?? "(start)";
		_lastClip = clip;
		_nextDiag = Time.time + 10f;
		_diagLogs--;
		var stateText = "state=n/a";
		var slowIdle = "n/a";
		var speed = "n/a";
		if (_animator)
		{
			try
			{
				var state = _animator.GetCurrentAnimatorStateInfo(0);
				// speedMultiplier is the state's speed-parameter value (battleSlowIdle on the idle states).
				stateText = "stateSpeed=" + state.speed.ToString("0.###") + " speedMultiplier=" + state.speedMultiplier.ToString("0.###")
				            + " normalizedTime=" + state.normalizedTime.ToString("0.###") + " stateLength=" + state.length.ToString("0.###");
			}
			catch (Exception ex)
			{
				stateText = "state=(" + ex.GetType().Name + ")";
			}
			slowIdle = TryGetFloat(_animator, BattleSlowIdleHash);
			speed = TryGetFloat(_animator, BattleSpeedHash);
		}
		var quadsOn = 0;
		foreach (var h in _billboards)
			quadsOn += CountEnabled(h);
		foreach (var h in _grounds)
			quadsOn += CountEnabled(h);
		var lightsOn = 0;
		var maxIntensity = 0f;
		foreach (var l in _lights)
		{
			if (IsLit(l))
			{
				lightsOn++;
				maxIntensity = Mathf.Max(maxIntensity, l.intensity);
			}
		}
		// Peak since the previous diag line (mostly the clip that just ended), then reset.
		var lightsPeak = Math.Max(_lightsPeak, lightsOn);
		var lightPeakMax = Mathf.Max(_lightPeakMax, maxIntensity);
		_lightsPeak = 0;
		_lightPeakMax = 0f;
		// The pipeline's own point-light switch (HexLighting._PunctualLights, cb2[9].x in the Lit pass).
		// Read-only; 0 here with lightsPeak > 0 means the pipeline did not publish punctual lights
		// as a global this frame (or binds HexLighting as a whole cbuffer), not that the light is off.
		var punctual = "n/a";
		try
		{
			punctual = Shader.GetGlobalFloat(PunctualLightsId).ToString("0.###");
		}
		catch (Exception ex)
		{
			punctual = "(" + ex.GetType().Name + ")";
		}
		var st = "n/a";
		var shapeMax = -1f;
		if (_body)
		{
			_body.GetPropertyBlock(_mpb);
			st = _mpb.GetVector("_MainTex_ST").ToString("F4");
		}
		var skin = _body ? _body : GetComponentInChildren<SkinnedMeshRenderer>(true);
		if (skin && skin.sharedMesh)
		{
			var n = skin.sharedMesh.blendShapeCount;
			for (var i = 0; i < n; i++)
				shapeMax = Mathf.Max(shapeMax, skin.GetBlendShapeWeight(i));
		}
		var failures = "";
		for (var i = 0; i < _stepFailures.Length; i++)
			if (_stepFailures[i] > 0)
				failures += " fail" + i + "=" + _stepFailures[i] + "(" + _stepLastError[i] + ")";
		Plugin.LogSource?.LogInfo("Homm3 unit-look VFX diag: unit='" + name + "' clip=" + clip + " " + stateText
		                          + " battleSlowIdle=" + slowIdle + " battleSpeed=" + speed + failures
		                          + " blendShapeMax=" + shapeMax.ToString("0.#") + " quadsOn=" + quadsOn + " lightsOn=" + lightsOn
		                          + " lightMax=" + maxIntensity.ToString("0.###") + " lights=" + _lights.Count
		                          + " lightsPeak=" + lightsPeak + " lightPeakMax=" + lightPeakMax.ToString("0.###")
		                          + " peakWindowClip=" + prevClip + " punctualLights=" + punctual
		                          + " bodyST=" + st + " atlasSnaps=" + _snaps
		                          + " mirror=" + _mirror.ToString("0") + " worldScale=" + transform.lossyScale.x.ToString("0.###") + ".");
	}

	private static int CountEnabled(Transform holder)
	{
		if (!holder)
			return 0;
		var on = 0;
		var renderers = holder.GetComponentsInChildren<MeshRenderer>(true);
		for (var i = 0; i < renderers.Length; i++)
			if (renderers[i] && renderers[i].enabled)
				on++;
		return on;
	}

	// Animator.StringToHash values (EsquireBattleAnimatorSetHook.HintForId). Never touch the Animator's
	// parameter array: Il2CppReferenceArray<AnimatorControllerParameter> violates the interop generic
	// constraint on this game (EsquireBattleAnimatorTelemetry records the same).
	private const int BattleSlowIdleHash = -1555555164;
	private const int BattleSpeedHash = -995794305;
	private static readonly int PunctualLightsId = Shader.PropertyToID("_PunctualLights");

	private static string TryGetFloat(Animator animator, int hash)
	{
		try
		{
			return animator.GetFloat(hash).ToString("0.###");
		}
		catch (Exception ex)
		{
			return "(" + ex.GetType().Name + ")";
		}
	}
}
