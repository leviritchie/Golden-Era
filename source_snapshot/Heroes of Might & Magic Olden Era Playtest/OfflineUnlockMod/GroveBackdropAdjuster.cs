using System;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class GroveBackdropAdjusterBootstrap
{
	private const string GoName = "GroveBackdropAdjuster";
	private static bool _registered;
	private static bool _attached;

	internal static void Ensure()
	{
		if (_attached)
		{
			return;
		}

		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<GroveBackdropAdjusterBehaviour>();
				_registered = true;
			}

			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<GroveBackdropAdjusterBehaviour>() == null)
			{
				Plugin.LogSource?.LogError("Grove backdrop adjuster: AddComponent returned null.");
			}

			UnityObject.DontDestroyOnLoad(go);
			_attached = true;
			Plugin.LogSource?.LogInfo("Grove backdrop adjuster loaded. Press F8 in-game to tune the grove PNG.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Grove backdrop adjuster could not start: " + ex);
		}
	}
}

public sealed class GroveBackdropAdjusterBehaviour : MonoBehaviour
{
	private bool _enabled;
	private int _frameCount;

	private void Update()
	{
		if ((++_frameCount % 30) == 0 && ModActions.IsActiveSceneCityInterior())
		{
			ModActions.EnsureCityMenuCanvasesVisible();
		}

		if (Input.GetKeyDown(KeyCode.F8))
		{
			_enabled = !_enabled;
			ModActions.ApplyCustomCityBackdrop();
			Plugin.LogSource?.LogInfo(
				"Grove backdrop adjuster "
				+ (_enabled ? "enabled" : "disabled")
				+ ". Hotkeys: PageUp/PageDown layer, arrows move, +/- scale, [] alpha, R reset, L log."
			);
		}

		if (!_enabled)
		{
			return;
		}

		var offsetStep = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift) ? 25f : 5f;
		var scaleStep = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift) ? 0.05f : 0.01f;
		var alphaStep = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift) ? 0.10f : 0.02f;

		if (Input.GetKeyDown(KeyCode.PageUp))
		{
			ModActions.AdjustCityBackdropSibling(1);
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.PageDown))
		{
			ModActions.AdjustCityBackdropSibling(-1);
			LogStatus();
		}

		if (Input.GetKeyDown(KeyCode.LeftArrow))
		{
			ModActions.AdjustCityBackdropOffset(-offsetStep, 0f);
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.RightArrow))
		{
			ModActions.AdjustCityBackdropOffset(offsetStep, 0f);
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.UpArrow))
		{
			ModActions.AdjustCityBackdropOffset(0f, offsetStep);
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.DownArrow))
		{
			ModActions.AdjustCityBackdropOffset(0f, -offsetStep);
			LogStatus();
		}

		if (Input.GetKeyDown(KeyCode.Equals) || Input.GetKeyDown(KeyCode.KeypadPlus))
		{
			ModActions.AdjustCityBackdropScale(scaleStep);
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.Minus) || Input.GetKeyDown(KeyCode.KeypadMinus))
		{
			ModActions.AdjustCityBackdropScale(-scaleStep);
			LogStatus();
		}

		if (Input.GetKeyDown(KeyCode.RightBracket))
		{
			ModActions.AdjustCityBackdropAlpha(alphaStep);
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.LeftBracket))
		{
			ModActions.AdjustCityBackdropAlpha(-alphaStep);
			LogStatus();
		}

		if (Input.GetKeyDown(KeyCode.R))
		{
			ModActions.ResetCityBackdropAdjustments();
			LogStatus();
		}
		if (Input.GetKeyDown(KeyCode.L))
		{
			LogStatus();
		}
	}

	private static void LogStatus()
	{
		Plugin.LogSource?.LogInfo("Grove backdrop adjuster: " + ModActions.GetCityBackdropAdjusterStatus());
	}
}
