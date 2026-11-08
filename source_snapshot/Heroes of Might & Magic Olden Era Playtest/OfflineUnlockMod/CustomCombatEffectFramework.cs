using System;

namespace OfflineUnlockMod;

internal readonly struct PreparedDamageMutation
{
	internal PreparedDamageMutation(int mechanicIndex, int expectedDamage, int newDamage)
	{
		MechanicIndex = mechanicIndex;
		ExpectedDamage = expectedDamage;
		NewDamage = newDamage;
	}

	internal int MechanicIndex { get; }
	internal int ExpectedDamage { get; }
	internal int NewDamage { get; }
	internal int Delta => NewDamage - ExpectedDamage;
	internal bool IsValid => MechanicIndex >= 0 && ExpectedDamage >= 0 && NewDamage >= 0 && NewDamage != ExpectedDamage;
}

/// <summary>
/// Dispatches compiled runtime mechanics and prepares explicit transformations.
/// The manager never writes native arguments; NativeCombatWriteGateway remains
/// the sole committed-damage writer.
/// </summary>
internal static class CustomCombatEffectManager
{
	private const int LogCap = 32;
	private static int _logged;

	internal static bool TryPrepareDamageApplying(
		object caster,
		object receiver,
		int currentDamage,
		out Homm3RuntimeMechanicApplication application,
		out PreparedDamageMutation mutation)
	{
		application = default;
		mutation = default;
		if (caster == null || receiver == null || currentDamage <= 0)
			return false;

		if (!Homm3BattleLocalLawState.TryGetUnitRuntimeMechanicApplication(caster, out application))
		{
			if (!Homm3BattleLocalLawState.TryGetLawRuntimeMechanicBinding(
				    caster,
				    out var lawMechanicIndex,
				    out var generation,
				    out _,
				    out _,
				    out _)
			    || !Homm3RuntimeLawFixtureAdapter.TryGetApplication(
				    caster,
				    lawMechanicIndex,
				    generation,
				    out application))
				return false;
		}

		if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(application.MechanicIndex, out var mechanic))
			return false;
		if (mechanic.AdapterId != Homm3DirectStateAdapterId.Damage
		    || mechanic.Operation != Homm3DirectStateOperation.DamageFlatDelta)
			return false;
		return CombatMutationApi.TryPrepareFlatDamageMutation(
			mechanic.MechanicIndex,
			currentDamage,
			mechanic.DamageDelta,
			out mutation);
	}

	internal static void LogAppliedDamage(
		Homm3RuntimeMechanicApplication application,
		PreparedDamageMutation mutation)
	{
		if (_logged++ >= LogCap)
			return;
		Plugin.LogSource?.LogInfo(
			"HoMM3 runtime mechanic applied committed damage:"
			+ " mechanic=" + Homm3RuntimeMechanicRegistry.DescribeActiveMechanic(application.MechanicIndex)
			+ " scope=" + application.Scope
			+ " generation=" + application.Generation
			+ " oldDamage=" + mutation.ExpectedDamage
			+ " delta=" + mutation.Delta
			+ " newDamage=" + mutation.NewDamage
			+ ".");
	}
}

