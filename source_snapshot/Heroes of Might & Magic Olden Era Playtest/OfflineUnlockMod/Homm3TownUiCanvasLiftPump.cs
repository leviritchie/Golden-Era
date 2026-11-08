using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3TownUiCanvasLiftPump
{
	private static bool _registered;
	private static bool _attached;

	internal static void Ensure(ManualLogSource log)
	{
		if (_attached)
			return;

		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3TownUiCanvasLiftPumpBehaviour>();
				_registered = true;
			}

			var go = new GameObject("OfflineUnlockTownUiCanvasLiftPump");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3TownUiCanvasLiftPumpBehaviour>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_attached = true;
		}
		catch (Exception ex)
		{
			log?.LogFatal("HoMM3 town UI canvas lift pump failed during startup: " + ex);
			throw;
		}
	}
}

public sealed class Homm3TownUiCanvasLiftPumpBehaviour : MonoBehaviour
{
	private void Update()
	{
		if (!ModActions.IsActiveSceneCityInterior())
			return;
		ModActions.ReconcileCustomTownPresentationForNativePanels();
	}
}
