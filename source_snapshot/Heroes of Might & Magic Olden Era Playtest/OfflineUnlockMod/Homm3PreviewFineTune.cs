using System;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Runtime snapshot for resets and copy-paste from the last HOMM3 unit-detail preview model instance.
/// </summary>
internal static class Homm3PreviewFineTuneRegistry
{
	internal static GameObject Target;
	internal static Renderer Background;
	internal static Vector3 InitialLocalPosition;
	internal static Vector3 InitialLocalEuler;
	internal static Vector3 InitialLocalScale;
	private static Material _donorMaterial;
	private static Material[] _initialSharedMaterials;
	private static int _materialMode;

	internal static bool HasLiveTarget()
	{
		return Target;
	}

	internal static void SetTarget(GameObject instance, Renderer donor, Renderer background)
	{
		ClearTarget();
		if (!instance)
			return;
		Target = instance;
		Background = background;
		_donorMaterial = donor ? donor.sharedMaterial : null;
		_initialSharedMaterials = SnapshotMaterials(instance);
		var t = instance.transform;
		InitialLocalPosition = t.localPosition;
		InitialLocalEuler = t.localEulerAngles;
		InitialLocalScale = t.localScale;
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
		{
			_materialMode = 3;
			Plugin.LogSource?.LogInfo(
				"Homm3 preview fine-tune: keeping Hex/Lit on owned skinned mesh '"
				+ instance.name
				+ "'. F10 = panel."
			);
			return;
		}

		_materialMode = 1;
		ApplyCurrentMaterialMode();
		Plugin.LogSource?.LogInfo(
			"Homm3 preview fine-tune: target='"
			+ instance.name
			+ "'. F10 = panel. Num4/8/6/2 = move X/Z if arrows are eaten by UI."
		);
	}

	internal static void ClearTarget()
	{
		Target = null;
		Background = null;
		_donorMaterial = null;
		_initialSharedMaterials = null;
	}

	internal static void ResetPoseToSnapshot()
	{
		if (!Target)
			return;
		var t = Target.transform;
		t.localPosition = InitialLocalPosition;
		t.localEulerAngles = InitialLocalEuler;
		t.localScale = InitialLocalScale;
	}

	internal static string FormatCurrentLine()
	{
		if (!Target)
			return "Homm3 preview fine-tune: (no target)";
		var t = Target.transform;
		return "Homm3 preview fine-tune: name='"
		       + Target.name
		       + "' localPosition="
		       + t.localPosition.ToString("F4")
		       + " localEuler="
		       + t.localEulerAngles.ToString("F2")
		       + " localScale="
		       + t.localScale.ToString("F4")
		       + " | reset uses snapshot from first SetTarget.";
	}

	internal static void LogCurrentLine()
	{
		Plugin.LogSource?.LogInfo(FormatCurrentLine());
	}

	internal static void CycleMaterialMode()
	{
		if (Target && Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(Target))
		{
			_materialMode = 3;
			Plugin.LogSource?.LogInfo(
				"Homm3 preview fine-tune: overlay material modes are forbidden on owned skinned meshes."
			);
			return;
		}

		_materialMode = (_materialMode + 1) % 4;
		ApplyCurrentMaterialMode();
		Plugin.LogSource?.LogInfo("Homm3 preview fine-tune material mode: " + MaterialModeName(_materialMode));
		LogCurrentLine();
	}

	private static Material[] SnapshotMaterials(GameObject instance)
	{
		if (!instance)
			return null;
		var wa = instance.GetComponentsInChildren<Renderer>(true);
		var mats = new Material[wa.Length];
		for (var i = 0; i < wa.Length; i++)
			mats[i] = wa[i] ? wa[i].sharedMaterial : null;
		return mats;
	}

	private static void ApplyCurrentMaterialMode()
	{
		if (!Target)
			return;
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(Target))
		{
			_materialMode = 3;
			var owned = Target.GetComponentsInChildren<Renderer>(true);
			if (_initialSharedMaterials != null && owned.Length == _initialSharedMaterials.Length)
			{
				for (var i = 0; i < owned.Length; i++)
				{
					var r = owned[i];
					if (!r)
						continue;
					var init = _initialSharedMaterials[i];
					if (init)
						r.sharedMaterial = init;
				}
			}
			return;
		}

		var wa = Target.GetComponentsInChildren<Renderer>(true);
		if (_materialMode == 3 && _initialSharedMaterials != null && wa.Length == _initialSharedMaterials.Length)
		{
			for (var i = 0; i < wa.Length; i++)
			{
				var r = wa[i];
				if (!r)
					continue;
				var init = _initialSharedMaterials[i];
				if (init)
					r.sharedMaterial = init;
			}
			return;
		}

		for (var i = 0; i < wa.Length; i++)
		{
			var r = wa[i];
			if (!r)
				continue;
			var original = _initialSharedMaterials != null && i < _initialSharedMaterials.Length ? _initialSharedMaterials[i] : r.sharedMaterial;
			var tex = GetMainTexture(original) ?? GetMainTexture(r.sharedMaterial);
			var replacement = CreateMaterialForMode(_materialMode, original, tex);
			if (replacement)
				r.sharedMaterial = replacement;
		}
	}

	private static Material CreateMaterialForMode(int mode, Material original, Texture tex)
	{
		Material m = null;
		if (mode == 0 && _donorMaterial)
		{
			m = new Material(_donorMaterial);
			m.name = "HOMM3_preview_donor_" + _donorMaterial.name;
		}
		else if (mode == 1)
			m = CreateShaderMaterial("Sprites/Default", original, "HOMM3_preview_sprites");
		else if (mode == 2)
			m = CreateShaderMaterial("Unlit/Transparent", original, "HOMM3_preview_unlit");

		if (!m)
			return null;
		ApplyTexture(m, tex);
		if (m.HasProperty("_Color"))
			m.color = Color.white;
		SetCullOff(m);
		ApplyPreviewOverlayRenderState(m);
		return m;
	}

	private static Material CreateShaderMaterial(string shaderName, Material original, string name)
	{
		var shader = Shader.Find(shaderName);
		if (!shader)
			return original ? new Material(original) : null;
		var md = new Material(shader) { name = name };
		if (original)
			md.renderQueue = original.renderQueue;
		return md;
	}

	private static Texture GetMainTexture(Material mat)
	{
		if (!mat)
			return null;
		if (mat.mainTexture)
			return mat.mainTexture;
		if (mat.HasProperty("_BaseMap"))
			return mat.GetTexture("_BaseMap");
		if (mat.HasProperty("_BaseColorMap"))
			return mat.GetTexture("_BaseColorMap");
		return null;
	}

	private static void ApplyTexture(Material m, Texture tex)
	{
		if (!m || !tex)
			return;
		m.mainTexture = tex;
		if (m.HasProperty("_BaseMap"))
			m.SetTexture("_BaseMap", tex);
		if (m.HasProperty("_BaseColorMap"))
			m.SetTexture("_BaseColorMap", tex);
	}

	private static void SetCullOff(Material m)
	{
		if (!m)
			return;
		if (m.HasProperty("_Cull"))
			m.SetFloat("_Cull", 0f);
		if (m.HasProperty("_CullMode"))
			m.SetFloat("_CullMode", 0f);
		if (m.HasProperty("_CullModeForward"))
			m.SetFloat("_CullModeForward", 0f);
	}

	private static void ApplyPreviewOverlayRenderState(Material m)
	{
		if (!m)
			return;
		m.renderQueue = 4000;
		if (m.HasProperty("_ZWrite"))
			m.SetFloat("_ZWrite", 0f);
		if (m.HasProperty("_ZTest"))
			m.SetFloat("_ZTest", (float)UnityEngine.Rendering.CompareFunction.Always);
	}

	private static string MaterialModeName(int mode)
	{
		return mode switch
		{
			0 => "donor preview material",
			1 => "Sprites/Default",
			2 => "Unlit/Transparent",
			3 => "original bundle material",
			_ => "unknown"
		};
	}
}

internal static class Homm3PreviewFineTuneBootstrap
{
	private const string GoName = "Homm3PreviewFineTune";
	private static bool _registered;
	private static bool _attached;

	internal static void Ensure()
	{
		if (_attached)
			return;

		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3PreviewFineTuneBehaviour>();
				_registered = true;
			}

			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<Homm3PreviewFineTuneBehaviour>() == null)
				Plugin.LogSource?.LogError("Homm3 preview fine-tune: AddComponent returned null.");

			UnityObject.DontDestroyOnLoad(go);
			_attached = true;
			Plugin.LogSource?.LogInfo("Homm3 preview fine-tune overlay ready. Press F10 in-game.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3 preview fine-tune could not start: " + ex);
		}
	}
}

public sealed class Homm3PreviewFineTuneBehaviour : MonoBehaviour
{
	private const float GuiReferenceHeight = 1080f;

	private bool _enabled;
	private GUIStyle _boxStyle;

	private static bool ShiftHeld()
	{
		return Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
	}

	private void Update()
	{
		if (Input.GetKeyDown(KeyCode.F10))
		{
			_enabled = !_enabled;
			Plugin.LogSource?.LogInfo("Homm3 preview fine-tune " + (_enabled ? "ON" : "OFF") + ".");
		}

		if (!_enabled)
			return;

		var t = Homm3PreviewFineTuneRegistry.Target;
		if (!t)
			return;

		var posStep = ShiftHeld() ? 0.02f : 0.06f;
		var eulerStep = ShiftHeld() ? 0.5f : 2.0f;
		var scaleFactor = ShiftHeld() ? 1.02f : 1.06f;

		var tr = t.transform;

		if (Input.GetKeyDown(KeyCode.LeftArrow) || Input.GetKeyDown(KeyCode.Keypad4))
			tr.localPosition += new Vector3(-posStep, 0f, 0f);
		if (Input.GetKeyDown(KeyCode.RightArrow) || Input.GetKeyDown(KeyCode.Keypad6))
			tr.localPosition += new Vector3(posStep, 0f, 0f);
		if (Input.GetKeyDown(KeyCode.UpArrow) || Input.GetKeyDown(KeyCode.Keypad8))
			tr.localPosition += new Vector3(0f, 0f, posStep);
		if (Input.GetKeyDown(KeyCode.DownArrow) || Input.GetKeyDown(KeyCode.Keypad2))
			tr.localPosition += new Vector3(0f, 0f, -posStep);
		if (Input.GetKeyDown(KeyCode.PageUp))
			tr.localPosition += new Vector3(0f, posStep, 0f);
		if (Input.GetKeyDown(KeyCode.PageDown))
			tr.localPosition += new Vector3(0f, -posStep, 0f);

		var euler = tr.localEulerAngles;
		if (Input.GetKeyDown(KeyCode.LeftBracket))
			euler.y -= eulerStep;
		if (Input.GetKeyDown(KeyCode.RightBracket))
			euler.y += eulerStep;
		if (Input.GetKeyDown(KeyCode.Comma))
			euler.x -= eulerStep;
		if (Input.GetKeyDown(KeyCode.Period))
			euler.x += eulerStep;
		if (Input.GetKeyDown(KeyCode.Semicolon))
			euler.z -= eulerStep;
		if (Input.GetKeyDown(KeyCode.Quote))
			euler.z += eulerStep;
		tr.localEulerAngles = euler;

		if (Input.GetKeyDown(KeyCode.Equals) || Input.GetKeyDown(KeyCode.KeypadPlus))
		{
			var s = tr.localScale * scaleFactor;
			if (s.x > 1e-4f && s.x < 500f)
				tr.localScale = s;
		}
		if (Input.GetKeyDown(KeyCode.Minus) || Input.GetKeyDown(KeyCode.KeypadMinus))
		{
			var s = tr.localScale / scaleFactor;
			if (s.x > 1e-4f)
				tr.localScale = s;
		}

		if (Input.GetKeyDown(KeyCode.Home))
		{
			Homm3PreviewFineTuneRegistry.ResetPoseToSnapshot();
			Homm3PreviewFineTuneRegistry.LogCurrentLine();
		}
		if (Input.GetKeyDown(KeyCode.End))
		{
			Homm3PreviewFineTuneRegistry.ClearTarget();
			Plugin.LogSource?.LogInfo("Homm3 preview fine-tune: target cleared (open preview again).");
		}
		if (Input.GetKeyDown(KeyCode.BackQuote) || Input.GetKeyDown(KeyCode.L))
			Homm3PreviewFineTuneRegistry.LogCurrentLine();
		if (Input.GetKeyDown(KeyCode.M))
			Homm3PreviewFineTuneRegistry.CycleMaterialMode();
	}

	private void EnsureBoxStyle()
	{
		if (_boxStyle != null)
			return;
		_boxStyle = new GUIStyle(GUI.skin.box)
		{
			normal = { textColor = Color.white },
			fontSize = 13,
			alignment = TextAnchor.UpperLeft,
			wordWrap = true
		};
	}

	private void OnGUI()
	{
		if (!_enabled)
			return;

		EnsureBoxStyle();

		var h = Mathf.Max(1f, (float)Screen.height);
		var scale = Mathf.Clamp(h / GuiReferenceHeight, 0.75f, 3f);

		var logicalW = Screen.width / scale;
		const float pad = 8f;
		var panelW = Mathf.Min(520f, logicalW - pad * 2f);
		const float panelH = 220f;

		var prev = GUI.matrix;
		GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));
		try
		{
			GUILayout.BeginArea(new Rect(pad, pad, panelW, panelH));
			GUILayout.BeginVertical(_boxStyle);
			GUILayout.Label("HOMM3 unit preview fine-tune (F10 off)  •  Shift = smaller steps", _boxStyle);
			if (!Homm3PreviewFineTuneRegistry.HasLiveTarget())
				GUILayout.Label("No target yet — open a lane-B preview (army or recruitment after extra hooks load).", _boxStyle);
			else
			{
				GUILayout.Label(Homm3PreviewFineTuneRegistry.FormatCurrentLine(), _boxStyle);
				GUILayout.Label(
					"Arrows or Num4826: local X/Z  •  PgUp/Dn: Y  •  [ ] yaw  •  , . pitch  •  ; ': roll"
					+ "  •  +/- scale  •  M material  •  `/L log  •  Home reset  •  End clear",
					_boxStyle
				);
			}
			GUILayout.EndVertical();
			GUILayout.EndArea();
		}
		finally
		{
			GUI.matrix = prev;
		}
	}
}
