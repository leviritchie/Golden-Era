using System;

namespace OfflineUnlockMod;

/// <summary>
/// Narrow diagnostic adapter for the Castle law-index-6 state fixture.
/// It proves law activation and side/battle state only; it does not implement
/// or replace the native Battle Readiness Focus bonus.
/// </summary>
internal static class Homm3RuntimeLawFixtureAdapter
{
	private const int LogCap = 12;
	private static int _logged;

	internal static bool TryGetApplication(
		object battleUnit,
		int mechanicIndex,
		int generation,
		out Homm3RuntimeMechanicApplication application)
	{
		application = default;
		if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(mechanicIndex, out var mechanic)
		    || mechanic.ActivationKind != Homm3RuntimeMechanicActivationKind.Law
		    || !Homm3BattleLocalLawState.TryGetLawRuntimeMechanicBinding(
			    battleUnit,
			    out var boundMechanicIndex,
			    out var boundGeneration,
			    out var ownerStatus,
			    out var lawOwner,
			    out var battleSide)
		    || boundMechanicIndex != mechanicIndex
		    || boundGeneration != generation)
			return false;

		if (ownerStatus == Homm3RuntimeLawCacheStatus.Unknown)
		{
			Homm3CustomFactionLawRuntime.TryResolveDataSideFromBattleTransferSide(
				battleSide,
				out lawOwner,
				out _);
			ownerStatus = Homm3BattleLocalLawState.PublishRuntimeLawOwner(
				battleUnit,
				generation,
				lawOwner);
			if (ownerStatus == Homm3RuntimeLawCacheStatus.Failed)
			{
				LogOnce("law-owner resolution failed for mechanic " + mechanic.MechanicId + ".");
				return false;
			}
		}
		if (ownerStatus != Homm3RuntimeLawCacheStatus.Present || lawOwner == null)
			return false;

		var lawStatus = Homm3BattleLocalLawState.ReadRuntimeLawActivation(
			battleSide,
			lawOwner,
			mechanicIndex,
			generation,
			out _);
		if (lawStatus == Homm3RuntimeLawCacheStatus.Unknown)
		{
			var rank = 0;
			var resolution = Homm3CustomFactionLawRuntime.ResolveActiveKnownCustomLawState(
				lawOwner,
				mechanic.LawIndex,
				out var activeLaw,
				out var detail);
			if (resolution == Homm3CustomFactionLawRuntime.ActiveLawResolutionKind.Present
			    && string.Equals(activeLaw.FactionSid, mechanic.FactionSid, StringComparison.Ordinal))
			{
				rank = activeLaw.Rank;
				lawStatus = Homm3RuntimeLawCacheStatus.Present;
				detail = "present rank=" + rank;
			}
			else
			{
				lawStatus = resolution == Homm3CustomFactionLawRuntime.ActiveLawResolutionKind.Absent
					? Homm3RuntimeLawCacheStatus.Absent
					: Homm3RuntimeLawCacheStatus.Failed;
			}

			lawStatus = Homm3BattleLocalLawState.PublishRuntimeLawActivation(
				battleSide,
				lawOwner,
				mechanicIndex,
				generation,
				lawStatus,
				rank);
			LogOnce(
				"Castle law-index-6 diagnostic fixture cached "
				+ lawStatus
				+ " for generation="
				+ generation
				+ ": "
				+ detail
				+ ". This fixture does not implement Battle Readiness.");
		}

		return lawStatus == Homm3RuntimeLawCacheStatus.Present
		       && Homm3BattleLocalLawState.TryGetLawRuntimeMechanicApplication(
			       mechanicIndex,
			       generation,
			       lawOwner,
			       battleSide,
			       out application);
	}

	private static void LogOnce(string message)
	{
		if (_logged++ >= LogCap)
			return;
		Plugin.LogSource?.LogInfo("HoMM3 runtime-mechanics law fixture: " + message);
	}
}
