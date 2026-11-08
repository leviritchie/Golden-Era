using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

internal static class Homm3DirectStateConflictAudit
{
	internal static bool TryAuditTarget(
		MethodBase target,
		string surface,
		out string failReason)
	{
		if (target == null)
		{
			failReason = "conflict audit target is null for " + (surface ?? "unknown");
			return false;
		}
		var info = Harmony.GetPatchInfo(target);
		if (info == null)
		{
			failReason = null;
			return true;
		}
		if (!TryAuditPatchSet(info.Prefixes, target, surface, out failReason)
		    || !TryAuditPatchSet(info.Postfixes, target, surface, out failReason)
		    || !TryAuditPatchSet(info.Transpilers, target, surface, out failReason)
		    || !TryAuditPatchSet(info.Finalizers, target, surface, out failReason))
			return false;
		failReason = null;
		return true;
	}

	/// <summary>
	/// Registration-path readback for the committed-damage surface: exact owned
	/// prefix/postfix pairing must be present whenever DamageApplied is claimed.
	/// </summary>
	internal static bool TryReadbackDamageSurfaceOwnership(
		MethodBase damageTarget,
		MethodInfo expectedPrefix,
		MethodInfo expectedPostfix,
		bool requirePrefix,
		bool requirePostfix,
		out string failReason)
	{
		if (damageTarget == null)
		{
			failReason = "damage surface readback target is null";
			return false;
		}
		var info = Harmony.GetPatchInfo(damageTarget);
		if (info == null)
		{
			if (!requirePrefix && !requirePostfix)
			{
				failReason = null;
				return true;
			}
			failReason = "damage surface readback found no Harmony patch info";
			return false;
		}
		if (requirePrefix
		    && !HasOwnedPatch(info.Prefixes, expectedPrefix, out failReason))
			return false;
		if (requirePostfix
		    && !HasOwnedPatch(info.Postfixes, expectedPostfix, out failReason))
			return false;
		if (requirePostfix && requirePrefix
		    && !HasOwnedPatch(info.Prefixes, expectedPrefix, out failReason))
		{
			failReason =
				"DamageApplied postfix requires owned typed damage prefix so Harmony __state is initialized";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool HasOwnedPatch(
		IEnumerable<Patch> patches,
		MethodInfo expected,
		out string failReason)
	{
		failReason = null;
		if (expected == null)
		{
			failReason = "expected owned damage patch method is null";
			return false;
		}
		foreach (var patch in patches)
		{
			if (patch.PatchMethod == expected
			    && patch.PatchMethod?.DeclaringType == typeof(Homm3RuntimeMechanicHooks))
				return true;
		}
		failReason =
			"damage surface readback missing owned patch "
			+ (expected.DeclaringType?.FullName ?? "?") + "." + expected.Name;
		return false;
	}

	private static bool TryAuditPatchSet(
		IEnumerable<Patch> patches,
		MethodBase target,
		string surface,
		out string failReason)
	{
		foreach (var patch in patches)
		{
			var declaringType = patch.PatchMethod?.DeclaringType;
			if (declaringType == typeof(Homm3RuntimeMechanicHooks)
			    || declaringType == typeof(Homm3BattleUnitLawOwnerRegistry))
				continue;
			failReason =
				"native surface conflict: surface=" + (surface ?? "unknown")
				+ " target=" + FormatMethod(target)
				+ " competingOwner=" + (declaringType?.FullName ?? patch.owner ?? "unknown")
				+ " patch=" + FormatMethod(patch.PatchMethod);
			return false;
		}
		failReason = null;
		return true;
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null
			? "null"
			: (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
