using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Buff-add prefix for the unit design kits: swaps the SID of a buff as it is added, by the generated tables
/// Homm3UnitKitRules.BuffRotations (Master Genie "Wish": each use grants the next wish) and
/// Homm3UnitKitRules.BuffEscalations (Ice Elemental "Frostbite": a repeat application becomes Frozen). The decision
/// lives in <see cref="Homm3UnitKitRuntime.SwapAddedBuff"/>; this class only owns the patch.
///
/// Patches the same buff-manager add methods as <see cref="Homm3CoveAfterShotHook"/>. Optional: when the methods do
/// not resolve, the kits keep their first buff (Wish stays +4 Attack, Frostbite never freezes). Every path fails
/// closed to the buff the game asked for.
/// Proof tier: build only; runtime unproven.
/// </summary>
internal static class Homm3UnitKitBuffSwapHook
{
	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedSwaps;
	private static int _loggedErrors;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			Homm3UnitKitBattleHooks.TryRegister(harmony, log);
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 unit kit battle hooks threw during registration (acting kit rules stay off): " + ex.GetBaseException().Message);
		}
		if (Homm3UnitKitRules.BuffRotations.Count == 0 && Homm3UnitKitRules.BuffEscalations.Count == 0
		    && Homm3UnitKitRules.BuffChains.Count == 0 && Homm3UnitKitRules.BuffScales.Count == 0 && !Homm3UnitKitRuntime.HasQuarryRules)
			return;
		try
		{
			var buffManagerType = GameMember.FindType(
				GameSymbols.CoveAfterShot.BuffManagerTypeId,
				GameSymbols.CoveAfterShot.BuffManagerTypeHint);
			if (buffManagerType == null)
				throw new MissingMemberException("buff manager type");
			var prefixMethod = typeof(Homm3UnitKitBuffSwapHook).GetMethod(nameof(PrefixBuffAdd), BindingFlags.NonPublic | BindingFlags.Static);
			var prefix = new HarmonyMethod(prefixMethod);
			var patched = 0;
			foreach (var method in Homm3CoveAfterShotHook.ResolveRequiredBuffAddMethods(buffManagerType))
			{
				if (!GameMember.IsHarmonyPatchCompatible(method, prefixMethod, out var reason))
				{
					_log?.LogWarning("HoMM3 unit kit buff swap: skipped " + method.Name + " (" + reason + ").");
					continue;
				}
				harmony.Patch(method, prefix: prefix);
				patched++;
			}
			if (patched == 0)
				throw new MissingMethodException(buffManagerType.FullName, "no buff-add method matched");
			_registered = true;
			_log?.LogInfo("HoMM3 unit kit buff swap: registered on " + patched + " buff-add method(s) ("
				+ Homm3UnitKitRules.BuffRotations.Count + " rotation(s), " + Homm3UnitKitRules.BuffEscalations.Count + " escalation(s), "
				+ Homm3UnitKitRules.BuffChains.Count + " chain(s), " + Homm3UnitKitRules.BuffScales.Count + " caster scale(s), quarry=" + Homm3UnitKitRuntime.HasQuarryRules + ").");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 unit kit buff swap NOT registered (rotating and escalating kit buffs keep their first buff): "
				+ ex.GetBaseException().Message);
		}
	}

	private static void PrefixBuffAdd(object __instance, [HarmonyArgument(0)] ref string sid, [HarmonyArgument(3)] object caster)
	{
		try
		{
			var swapped = Homm3UnitKitRuntime.SwapAddedBuff(__instance, sid, caster, out var detail);
			if (swapped == null || swapped == sid)
				return;
			sid = swapped;
			if (detail != null && _loggedSwaps++ < 24)
				_log?.LogInfo("HoMM3 unit kit buff swap: " + detail + ".");
		}
		catch (Exception ex)
		{
			if (_loggedErrors++ < 4)
				_log?.LogWarning("HoMM3 unit kit buff swap failed closed: " + ex.GetBaseException().Message);
		}
	}
}
