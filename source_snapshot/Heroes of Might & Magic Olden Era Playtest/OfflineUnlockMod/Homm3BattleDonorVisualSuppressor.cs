using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

public sealed class Homm3BattleDonorVisualSuppressor : MonoBehaviour
{
	private static bool _typeRegistered;
	private static int _attachDiagRemaining = 12;
	private static int _suppressDiagRemaining = 16;

	private Transform _scanRoot;
	private string _unitSid;
	private bool _skinnedDiagDumped;

	public Homm3BattleDonorVisualSuppressor(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject replacementRoot, Transform scanRoot, string unitSid, ManualLogSource log)
	{
		if (!replacementRoot || !replacementRoot.transform || !scanRoot)
			return;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3BattleDonorVisualSuppressor>();
				_typeRegistered = true;
				log?.LogInfo("Homm3 battle donor visual suppressor: registered Il2Cpp type.");
			}

			var existing = replacementRoot.GetComponent<Homm3BattleDonorVisualSuppressor>();
			var suppressor = existing != null && existing ? existing : replacementRoot.AddComponent<Homm3BattleDonorVisualSuppressor>();
			suppressor._scanRoot = scanRoot;
			suppressor._unitSid = unitSid;
			if (_attachDiagRemaining > 0)
			{
				_attachDiagRemaining--;
				log?.LogInfo(
					"Homm3 battle donor visual suppressor: attached unitSid='"
					+ (unitSid ?? "?")
					+ "' scanRoot='"
					+ (scanRoot.name ?? "?")
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle donor visual suppressor attach failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private void LateUpdate()
	{
		if (!_scanRoot || !transform)
			return;

		if (!_skinnedDiagDumped && Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(gameObject)
		    && Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag"))
		{
			_skinnedDiagDumped = true;
			Plugin.LogSource?.LogInfo(
				"Homm3 battle donor visual suppressor: skinned-lane late diag unitSid='"
				+ (_unitSid ?? "?")
				+ "' "
				+ Homm3ImportVisuals.DescribeSkinnedBattleLaneState(gameObject));
		}

		Homm3ImportReleaseBattleVisualHook.SuppressDonorVisuals(
			_scanRoot,
			transform,
			null,
			suppressAllOtherVisuals: true,
			out var disabledRenderers,
			out var stoppedParticles,
			out var disabledLights);
		if ((disabledRenderers <= 0 && stoppedParticles <= 0 && disabledLights <= 0) || _suppressDiagRemaining <= 0)
			return;

		_suppressDiagRemaining--;
		Plugin.LogSource?.LogInfo(
			"Homm3 battle donor visual suppressor: suppressed late donor visuals near unitSid='"
			+ (_unitSid ?? "?")
			+ "' renderers="
			+ disabledRenderers
			+ " particles="
			+ stoppedParticles
			+ " lights="
			+ disabledLights
			+ ".");
	}
}
