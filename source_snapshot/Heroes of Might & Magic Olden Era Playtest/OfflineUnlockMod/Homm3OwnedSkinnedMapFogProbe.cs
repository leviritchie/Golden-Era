using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Adventure-map fog for owned-skinned meshes. The native donor renderer stays hidden
/// (<c>forceRenderingOff</c>) so the dungeon stand-in does not draw. Owned draw follows the
/// native map-squad visibility flag (fog of war). Do not force owned meshes visible here —
/// that punched through fog. Do not attach <see cref="Homm3NativeShellVisibilitySync"/>.
/// Shader pin: <c>_HexFade</c>.
/// </summary>
public sealed class Homm3OwnedSkinnedMapFogProbe : MonoBehaviour
{
	private static readonly int HexFadeId = Shader.PropertyToID("_HexFade");
	private static bool _typeRegistered;
	private static int _diagRemaining = 12;
	private static int _missingNativeLogs = 8;

	private Transform _visual;
	private Renderer[] _native;
	private Renderer[] _owned;

	public Homm3OwnedSkinnedMapFogProbe(IntPtr ptr)
		: base(ptr)
	{
	}

	internal static void TryAttach(GameObject shell, GameObject visual, ManualLogSource log)
	{
		if (!shell || !visual)
			return;
		EnsureTypeRegistered(log);
		var probe = shell.GetComponent<Homm3OwnedSkinnedMapFogProbe>();
		if (!probe)
			probe = shell.AddComponent<Homm3OwnedSkinnedMapFogProbe>();
		if (!probe)
		{
			log?.LogError("Homm3Import: owned-skinned map fog probe AddComponent failed on '" + (shell.name ?? "?") + "'.");
			return;
		}
		probe._visual = visual.transform;
		probe.Refresh();
	}

	internal static void EnsureTypeRegistered(ManualLogSource log)
	{
		if (_typeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3OwnedSkinnedMapFogProbe>();
			_typeRegistered = true;
			log?.LogInfo("Homm3Import: registered Il2Cpp type Homm3OwnedSkinnedMapFogProbe.");
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3Import: Homm3OwnedSkinnedMapFogProbe Il2Cpp register failed: " + ex.Message);
		}
	}

	private void LateUpdate()
	{
		if (!transform.parent)
			return;
		if (_native == null || _owned == null)
			Refresh();
		KeepNativeProbeHidden();
	}

	private void Refresh()
	{
		if (!_visual)
		{
			var found = transform.Find(Homm3ImportVisuals.MapPrefabVisualChildName);
			if (found)
				_visual = found;
		}

		var all = GetComponentsInChildren<Renderer>(true);
		var native = new System.Collections.Generic.List<Renderer>();
		var owned = new System.Collections.Generic.List<Renderer>();
		for (var i = 0; all != null && i < all.Length; i++)
		{
			var r = all[i];
			if (!r)
				continue;
			if (_visual && IsUnder(r.transform, _visual))
				owned.Add(r);
			else
			{
				r.forceRenderingOff = true;
				r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
				r.receiveShadows = false;
				native.Add(r);
			}
		}
		_native = native.ToArray();
		_owned = owned.ToArray();
	}

	private void KeepNativeProbeHidden()
	{
		if (_native == null || _owned == null || _owned.Length == 0)
			return;

		if (_native.Length == 0)
		{
			if (_missingNativeLogs > 0)
			{
				_missingNativeLogs--;
				Plugin.LogSource?.LogError(
					"Homm3Import: owned-skinned map fog probe has no native renderer on '"
					+ (gameObject ? gameObject.name : "?")
					+ "'; FoW WorldSpace still applies on owned Hex/Lit.");
			}
			return;
		}

		for (var i = 0; i < _native.Length; i++)
		{
			var native = _native[i];
			if (!native)
				continue;
			native.forceRenderingOff = true;
		}

		if (_diagRemaining <= 0)
			return;
		_diagRemaining--;
		Plugin.LogSource?.LogInfo(
			"Homm3Import: owned-skinned map fog probe shell='"
			+ (gameObject ? gameObject.name : "?")
			+ "' nativeProbeHidden=true ownedRenderers="
			+ _owned.Length
			+ " controllerOwnsOwnedDraw=true hexFadeId="
			+ HexFadeId
			+ ".");
	}

	private static bool IsUnder(Transform t, Transform parent)
	{
		if (!t || !parent)
			return false;
		for (var cur = t; cur != null; cur = cur.parent)
		{
			if (cur == parent)
				return true;
		}
		return false;
	}
}
