using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22, owner answer 1: the HoMM3 Escape Tunnel comes with the Stronghold Fort. A hero defending a
/// siege of a <c>homm3_stronghold_city</c> that has <c>Build_Wall</c> level 1 or higher may retreat.
///
/// Native rule (Ghidra, build 26615913, <c>ekf$$bfcc</c> @ 0x182061720, the BattleCompletionUtility.CanEscape):
/// <c>ESideCommandsState CanEscape(Logic, int loserIndex)</c> returns <c>ReasonDefenderCant</c> (10) when the loser's
/// world side owns the battle object (a town siege, after the Type_Hero / OnMap / ban checks). Live interop name:
/// <c>ObjectPublicAbstractSealedbf57aInESbf6abidUnique.Method_Public_Static_ESideCommandsState_&lt;Logic&gt;_Int32_1</c>
/// (token 100706108). <c>_Int32_0</c> is CanCapitulate (left alone: the Escape Tunnel is retreat only); the
/// <c>_PDM_0..3</c> variants have no callers. Callers: the battle SideCommands helper (retreat button) and the simulated
/// battle UI, so player and quick-combat retreat both follow.
///
/// This postfix flips exactly <c>ReasonDefenderCant</c> to <c>Allowed</c>, only for the defending hero side of a
/// Stronghold siege whose town has the Fort. Every other refusal (banned escape, single hero, tourney, not a hero)
/// is kept.
///
/// Safety of the result (mono decomp, unchanged surfaces in the live build): <c>CmdBattleSideEscape</c> ->
/// <c>ApplyResult</c>; a Type_Hero loser marked Escaped goes through <c>world.heroes.ReturnToSideReserve</c>, which
/// calls <c>CityHeroesUtility.DeleteHero(city, hero)</c> for a town hero (the same cleanup as a killed defender), so
/// the hero returns to the side's reserve (re-hireable in the tavern). <c>CityBattleController.ApplyResults(attacker)</c>
/// then hands the town to the attacker exactly as when the defender dies. Units are lost unless the side has the
/// native <c>enableSavePartyByEscape</c> bonus.
/// </summary>
internal static class Homm3StrongholdEscapeTunnelRuntime
{
	internal const string CitySid = "homm3_stronghold_city";
	internal const string FortSid = "Build_Wall";
	internal const int FortLevel = 1;
	private const string UtilityTypeName = GameSymbols.TownBuildingPass.BattleCompletionUtilityTypeName;
	private const string CanEscapeNameSuffix = "_Int32_1";

	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedGrants;
	private static int _loggedSkips;
	private static readonly Dictionary<(IntPtr logic, IntPtr battle, int loser), bool> _decisions = new();

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var target = ResolveCanEscape();
			var postfix = typeof(Homm3StrongholdEscapeTunnelRuntime).GetMethod(nameof(PostfixCanEscape), BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
				throw new MissingMethodException("postfix incompatible: " + reason);
			harmony.Patch(target, postfix: new HarmonyMethod(postfix));
			_registered = true;
			_log?.LogInfo("HoMM3 Stronghold Escape Tunnel registered on " + target.DeclaringType?.FullName + "." + target.Name + " (Fort L1 lets the defending hero retreat).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Stronghold Escape Tunnel not registered (defenders keep the native retreat ban): " + ex.Message);
		}
	}

	private static MethodInfo ResolveCanEscape()
	{
		var hexAssembly = typeof(TransferBattle).Assembly;
		var initMethod = Homm3TownSiegeDefenseRuntime.ResolveBattleLogicInit("homm3.strongholdEscapeTunnel");
		var logicType = initMethod.DeclaringType;
		var utilityType = hexAssembly.GetType(UtilityTypeName)
		                  ?? throw new MissingMemberException("BattleCompletionUtility type " + UtilityTypeName + " not found");
		var exactName = GameSymbols.TownBuildingPass.CanEscapeNamePrefix + logicType.Name + CanEscapeNameSuffix;
		foreach (var method in utilityType.GetMethods(BindingFlags.Static | BindingFlags.Public))
		{
			if (!string.Equals(method.Name, exactName, StringComparison.Ordinal) || method.ReturnType != typeof(ESideCommandsState))
				continue;
			var p = method.GetParameters();
			if (p.Length == 2 && p[0].ParameterType == logicType && p[1].ParameterType == typeof(int))
				return method;
		}
		throw new MissingMethodException("CanEscape " + exactName + "(" + logicType.Name + ", int) not found on " + UtilityTypeName);
	}

	private static void PostfixCanEscape(object __0, int __1, ref ESideCommandsState __result)
	{
		if (__result != ESideCommandsState.ReasonDefenderCant)
			return;
		try
		{
			if (Allows(__0, __1))
				__result = ESideCommandsState.Allowed;
		}
		catch (Exception ex)
		{
			LogSkip("check failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static bool Allows(object logic, int loserIndex)
	{
		if (logic == null || loserIndex < 0)
			return false;
		var transferBattle = Homm3TowerArtificingRuntime.ReadMember(logic, GameSymbols.BattleResultLaws.BattleLogicTransferBattleFields) as TransferBattle
		                     ?? Homm3TowerArtificingRuntime.ReadMember(logic, GameSymbols.BattleResultLaws.BattleLogicStartedTransferBattleFields) as TransferBattle;
		if (transferBattle == null)
			return false;
		var key = ((logic as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero, transferBattle.Pointer, loserIndex);
		if (key.Item1 != IntPtr.Zero && _decisions.TryGetValue(key, out var cached))
			return cached;

		var allowed = Decide(transferBattle, loserIndex);
		if (key.Item1 != IntPtr.Zero)
		{
			if (_decisions.Count > 32)
				_decisions.Clear();
			_decisions[key] = allowed;
		}
		return allowed;
	}

	private static bool Decide(TransferBattle transferBattle, int loserIndex)
	{
		if (!Homm3TownBuildingReader.TryGetSiegeDefender(transferBattle, out var city, out var defenderIndex, out var defender))
			return false;
		if (defenderIndex != loserIndex || defender.typeInWorld != TransferSide.EType.Type_Hero)
			return false;
		if (!Homm3TownBuildingReader.CityMatchesSid(city, CitySid))
			return false;
		if (!Homm3TownBuildingReader.CityHasBuilding(city, FortSid, FortLevel))
			return false;
		if (_loggedGrants++ < 8)
			_log?.LogInfo("HoMM3 Stronghold Escape Tunnel: defending hero (side " + loserIndex + ") of city #" + city.idMapObject + " may retreat.");
		return true;
	}

	private static void LogSkip(string message)
	{
		if (_loggedSkips++ < 8)
			_log?.LogWarning("HoMM3 Stronghold Escape Tunnel: " + message);
	}
}
