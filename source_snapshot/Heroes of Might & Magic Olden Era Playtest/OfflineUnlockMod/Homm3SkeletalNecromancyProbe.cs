using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3-style Necropolis skeleton generation.
/// The release path grants <c>h3_skeleton</c> stacks to the winning Necropolis
/// hero's transfer side immediately before battle results are applied to the world.
/// Do not revive the in-combat SubstituteByHp bridge as production behavior.
/// </summary>
internal static class Homm3SkeletalNecromancyProbe
{
	private const string NecropolisFactionSid = "homm3_necropolis";
	private const string SkeletonRewardUnitSid = "h3_skeleton";
	private const string SkeletonWarriorRewardUnitSid = "h3_skeleton_upg";
	private const string SkeletonArcherRewardUnitSid = "h3_skeleton_upg_alt";
	private const string WarriorRewardSubSkillSid = "sub_skill_faction_homm3_necropolis_bone_tithe";
	private const string ArcherRewardSubSkillSid = "sub_skill_faction_homm3_necropolis_grave_discipline";
	private const float BasicConversionPercent = 0.05f;
	private const float AdvancedConversionPercent = 0.10f;
	private const float ExpertConversionPercent = 0.15f;

	// law pass 2026-11-21: Necropolis faction laws that change Necromancy (docs/faction_law_pass_20261121/necropolis.md).
	// No law or a read failure gives rank 0 and the current reward.
	// law pass 2026-11-25: Bone Tithe (#7) replaces Bone Conductors (+2%/+4% share); Grave Robbers (#9) replaces
	// Skeleton Transformer (repeated Warrior Levy); Unearthed Graves (#8) also gives a defending hero +5%.
	private const int LawBoneTithe = 7;
	private const int LawUnearthedGraves = 8;
	private const int LawGraveRobbers = 9;
	private const int LawBoneHarvest = 12;
	private const int LawDarkAscension = 30;
	private static readonly double[] BoneTitheGoldShare = { 0.25, 0.50 };
	private const float UnearthedGravesHeroPercent = 0.05f;
	private const string GoldResourceName = "gold";
	private const float BoneHarvestPercent = BasicConversionPercent;
	private const float DarkAscensionPercentPerLevel = 0.05f;
	private const string DarkAscensionRewardUnitSid = "h3_wight";

	// building pass 2026-11-22 (docs/building_pass_20261122/necropolis.md): town buildings that raise the share.
	// Values are HoMM3's halved, like the 5/10/15% buckets above. Read through Homm3TownBuildingReader (fails closed).
	private const string NecropolisCitySid = "homm3_necropolis_city";
	private const string AmplifierBuildingSid = "Build_Mother_Nature";
	private const string SoulPrisonBuildingSid = "Build_Gaping_Maw";
	private const float AmplifierBuildingPercent = 0.05f;
	private const float SoulPrisonPercent = 0.10f;

	private static bool _registered;
	private static ManualLogSource _log;
	private static MethodInfo _transferSideAddSpawnedUnitMethod;
	private static MethodInfo _transferSideSortBySlotMethod;
	private static Type _configRootType;
	private static object _unitLogicConfigTable;
	private static bool _postBattleEnabled;
	// Keyed by native BattleLogic pointer + battle id: the id is a per-session counter that repeats after
	// a save reload or new game, which would otherwise silently skip that battle's skeleton reward.
	private static readonly HashSet<(long ptr, int id)> _postBattleApplied = new();
	private static int _loggedSkipped;
	private static int _loggedPostBattleResults;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before skeletal necromancy probe registration.");

		_log = log;
		_postBattleEnabled = false;
		var applyResultMethod = ResolveApplyBattleResultMethod();
		if (applyResultMethod == null)
			throw new MissingMethodException("battle.skeletalNecromancy.applyBattleResult", "eff.bdol(eep,bool) / BattlesManager.ApplyResult(Logic)");

		_transferSideAddSpawnedUnitMethod = ResolveTransferSideMethod(
			GameSymbols.SkeletalNecromancy.TransferSideAddSpawnedUnit.NameHints,
			typeof(void),
			typeof(TransferUnit),
			typeof(bool));
		if (_transferSideAddSpawnedUnitMethod == null)
			throw new MissingMethodException("battle.skeletalNecromancy.transferSide.addSpawnedUnit", "TransferSide.bech(TransferUnit,bool)");

		_transferSideSortBySlotMethod = ResolveTransferSideMethod(
			GameSymbols.SkeletalNecromancy.TransferSideSortBySlot.NameHints,
			typeof(void));
		if (_transferSideSortBySlotMethod == null)
			throw new MissingMethodException("battle.skeletalNecromancy.transferSide.sortBySlot", "TransferSide.becl()");

		if (!Homm3RuntimeMechanicHooks.TryRegisterSharedBattleResult(harmony, log))
			throw new InvalidOperationException("shared battle-result hook did not register for skeletal necromancy");

		Homm3SkeletalNecromancyNotificationBootstrap.Ensure();
		_postBattleEnabled = true;
		_registered = true;
		_log?.LogInfo("HoMM3 skeletal necromancy post-battle: delegated to shared hook " + FormatMethod(applyResultMethod) + "; add=" + _transferSideAddSpawnedUnitMethod.Name + " sort=" + _transferSideSortBySlotMethod.Name + ".");
	}

	private static MethodInfo ResolveApplyBattleResultMethod()
	{
		var assembly = typeof(TransferSide).Assembly;
		var logicType = ResolveTypeByNames(assembly, GameSymbols.SkeletalNecromancy.BattleLogicTypeHints);
		if (logicType == null)
			return null;
		foreach (var managerType in ResolveTypesByNames(assembly, GameSymbols.SkeletalNecromancy.BattlesManagerTypeHints))
		{
			foreach (var name in GameSymbols.SkeletalNecromancy.ApplyBattleResult.NameHints)
			{
				var method = managerType.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (method == null || method.ReturnType != typeof(void))
					continue;
				var ps = method.GetParameters();
				if ((ps.Length == 1 || ps.Length == 2)
				    && ps[0].ParameterType == logicType
				    && (ps.Length == 1 || ps[1].ParameterType == typeof(bool)))
					return method;
			}
		}
		return null;
	}

	private static MethodInfo ResolveTransferSideMethod(string[] names, Type returnType, params Type[] parameterTypes)
	{
		foreach (var method in typeof(TransferSide).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType != returnType || !NameMatches(method, names))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != parameterTypes.Length)
				continue;
			var match = true;
			for (var i = 0; i < parameterTypes.Length; i++)
			{
				if (ps[i].ParameterType != parameterTypes[i])
				{
					match = false;
					break;
				}
			}
			if (match)
				return method;
		}
		return null;
	}

	private static void PrefixApplyBattleResult(object __0, bool __1, MethodBase __originalMethod)
	{
		ObserveBeforeBattleResult(__0, __1, __originalMethod);
	}

	internal static void ObserveBeforeBattleResult(object __0, bool __1, MethodBase __originalMethod)
	{
		try
		{
			if (!_postBattleEnabled || __0 == null)
				return;
			if (ReadBoolMember(__0, GameSymbols.SkeletalNecromancy.BattleLogicAlreadyAppliedFields) == true)
				return;

			lock (_postBattleApplied)
			{
				if (_postBattleApplied.Contains(GetBattleLogicAppliedKey(__0)))
					return;
			}

			var showNotification = __1;

            if (ApplyPostBattleSkeletonReward(__0, FormatMethod(__originalMethod), showNotification))
			{
				lock (_postBattleApplied)
					_postBattleApplied.Add(GetBattleLogicAppliedKey(__0));
			}
		}
		catch (Exception ex)
		{
			if (_loggedSkipped++ < 8)
				_log?.LogWarning("HoMM3 skeletal necromancy post-battle: reward application failed: " + ex.Message);
		}
	}

	private static (long ptr, int id) GetBattleLogicAppliedKey(object battleLogic)
	{
		var ptr = battleLogic is Il2CppObjectBase il2Cpp ? il2Cpp.Pointer.ToInt64() : 0L;
		return (ptr, GetBattleLogicKey(battleLogic));
	}

	private static int GetBattleLogicKey(object battleLogic)
	{
		var id = ReadIntMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicIdFields);
		if (id != 0)
			return id;
		if (battleLogic is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
		{
			var ptr = il2Cpp.Pointer.ToInt64();
			return unchecked((int)(ptr ^ (ptr >> 32)));
		}
		return battleLogic.GetHashCode();
	}

	private static bool ApplyPostBattleSkeletonReward(object battleLogic, string source, bool showNotification)
	{
		var transferBattle = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
		var startedTransferBattle = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle;
		var resultInfo = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
		if (transferBattle?.sides == null || startedTransferBattle?.sides == null || resultInfo == null)
		{
			LogPostBattle("skip missing transfer/result data source=" + source);
			return false;
		}

		var winnerIndex = resultInfo.winnerIndex;
		if (winnerIndex < 0 || winnerIndex >= transferBattle.sides.Length)
		{
			LogPostBattle("skip invalid winnerIndex=" + winnerIndex + " source=" + source);
			return false;
		}

		var winner = transferBattle.sides[winnerIndex];
		var winnerStarted = winnerIndex < startedTransferBattle.sides.Length ? startedTransferBattle.sides[winnerIndex] : null;
		// law pass 2026-11-21: Unearthed Graves (#8): a hero-less garrison of a player holding the law raises at the Basic share.
		var garrisonGraves = false;
		if (!IsNecropolisHeroSide(winnerStarted ?? winner, out var heroSid))
		{
			if (!IsUnearthedGravesGarrison(transferBattle, winnerStarted ?? winner))
				return false;
			garrisonGraves = true;
			heroSid = "garrison(Unearthed Graves)";
		}

		var loserIndices = ResolveLoserIndices(resultInfo);
		if (loserIndices.Count == 0)
		{
			LogPostBattle("skip no loser indices hero=" + heroSid + " source=" + source);
			return false;
		}

		var graveRobbers = !garrisonGraves && NecropolisLawRank(LawGraveRobbers, winner, winnerStarted) > 0;
		var eligibleValue = 0;
		var enemyStacks = 0;
		var blockedStacks = 0;
		var blockedDetails = new StringBuilder();
		foreach (var loserIndex in loserIndices)
		{
			if (loserIndex < 0 || loserIndex >= startedTransferBattle.sides.Length)
				continue;
			var loserStarted = startedTransferBattle.sides[loserIndex];
			var loserAfter = loserIndex < transferBattle.sides.Length ? transferBattle.sides[loserIndex] : null;
			// law pass 2026-11-25: Grave Robbers (#9): defeated Undead enemies count too (heroes only).
			eligibleValue += SumEligibleLostSquadValue(loserStarted, loserAfter, out var sideEnemyStacks, out var sideBlockedStacks, blockedDetails, graveRobbers);
			enemyStacks += sideEnemyStacks;
			blockedStacks += sideBlockedStacks;
		}

		var conversionPercent = garrisonGraves ? BasicConversionPercent : ResolveNecromancyConversionPercent(winner, winnerStarted);
		if (conversionPercent <= 0f)
		{
			LogPostBattle("skip missing necromancy rank hero=" + heroSid + " source=" + source);
			return false;
		}
		var lawNotes = new StringBuilder();
		var ownLostValue = 0;
		var darkAscension = 0;
		if (!garrisonGraves)
		{
			if (graveRobbers)
				lawNotes.Append(" graveRobbers");
			// law pass 2026-11-25: Unearthed Graves (#8): a Necropolis hero who wins as the town's siege defender gets +5%.
			if (NecropolisLawRank(LawUnearthedGraves, winner, winnerStarted) > 0 && IsSiegeDefender(startedTransferBattle, transferBattle, winnerIndex))
			{
				conversionPercent += UnearthedGravesHeroPercent;
				lawNotes.Append(" unearthedGravesHero=+" + UnearthedGravesHeroPercent.ToString("0.##"));
			}
			// building pass 2026-11-22: Necromancy Amplifier building (+5%, once per side however many towns have it)
			// and the Soul Prison grail (+10%). Both stack with each other and with the law.
			if (NecropolisSideOwnsBuilding(AmplifierBuildingSid, winner, winnerStarted))
			{
				conversionPercent += AmplifierBuildingPercent;
				lawNotes.Append(" amplifierBuilding=+" + AmplifierBuildingPercent.ToString("0.##"));
			}
			if (NecropolisSideOwnsBuilding(SoulPrisonBuildingSid, winner, winnerStarted))
			{
				conversionPercent += SoulPrisonPercent;
				lawNotes.Append(" soulPrison=+" + SoulPrisonPercent.ToString("0.##"));
			}
			// law pass 2026-11-21: Bone Harvest (#12): the winner's own fallen living creatures also count, at 5%.
			if (NecropolisLawRank(LawBoneHarvest, winner, winnerStarted) > 0)
			{
				ownLostValue = SumEligibleLostSquadValue(winnerStarted, winner, out var ownStacks, out _, null);
				lawNotes.Append(" boneHarvestValue=" + ownLostValue + " (" + ownStacks + " stacks)");
			}
			// law pass 2026-11-21: Dark Ascension (#30): also raise Wights worth 5%/10% of the fallen.
			darkAscension = Math.Min(NecropolisLawRank(LawDarkAscension, winner, winnerStarted), 2);
		}

		var rewardUnitSid = garrisonGraves ? SkeletonRewardUnitSid : ResolveRewardUnitSid(winner, winnerStarted);
		var rewardUnitValue = ResolveRewardUnitSquadValue(rewardUnitSid);
		if (rewardUnitValue <= 0)
		{
			LogPostBattle("skip missing reward unit value hero=" + heroSid + " rewardUnit=" + rewardUnitSid + " source=" + source);
			return false;
		}

		var reward = CalculateReward(eligibleValue, conversionPercent, rewardUnitValue);
		if (ownLostValue > 0)
			reward = Math.Max(0, (int)Math.Floor((eligibleValue * (double)conversionPercent + ownLostValue * (double)BoneHarvestPercent) / rewardUnitValue));
		var wights = 0;
		if (darkAscension > 0)
			wights = CalculateReward(eligibleValue, DarkAscensionPercentPerLevel * darkAscension, ResolveRewardUnitSquadValue(DarkAscensionRewardUnitSid));
		if (reward <= 0 && wights <= 0)
		{
			LogPostBattle(
				"skip zero reward hero="
				+ heroSid
				+ " enemyLostStacks="
				+ enemyStacks
				+ " blockedLostStacks="
				+ blockedStacks
				+ " eligibleSquadValue="
				+ eligibleValue
				+ " blockedDetails="
				+ (blockedDetails.Length > 0 ? blockedDetails.ToString() : "none")
				+ lawNotes
				+ " source="
				+ source);
			return false;
		}

		var before = CountUnitStacks(winner, rewardUnitSid);
		var invoked = reward > 0 && GrantSkeletonsToWinner(winner, rewardUnitSid, reward);
		var after = CountUnitStacks(winner, rewardUnitSid);
		var skeletonsGranted = invoked && after > before;
		var wightsGranted = false;
		if (wights > 0)
		{
			var wightsBefore = CountUnitStacks(winner, DarkAscensionRewardUnitSid);
			wightsGranted = GrantSkeletonsToWinner(winner, DarkAscensionRewardUnitSid, wights)
			                && CountUnitStacks(winner, DarkAscensionRewardUnitSid) > wightsBefore;
			lawNotes.Append(" darkAscension=L" + darkAscension + " wights=" + wights + (wightsGranted ? "" : " FAILED"));
		}
		if (!skeletonsGranted && !wightsGranted)
		{
			LogPostBattle(
				"grant failed hero="
				+ heroSid
				+ " rewardUnit="
				+ rewardUnitSid
				+ " reward="
				+ reward
				+ " before="
				+ before
				+ " after="
				+ after
				+ lawNotes
				+ " source="
				+ source);
			return false;
		}

		// law pass 2026-11-25: Bone Tithe (#7): Gold equal to 25%/50% of the Gold cost of the creatures just raised.
		var titheRank = garrisonGraves ? GarrisonOwnerLawRank(transferBattle, winnerStarted ?? winner, LawBoneTithe) : NecropolisLawRank(LawBoneTithe, winner, winnerStarted);
		if (titheRank > 0)
			lawNotes.Append(" " + PayBoneTithe(titheRank, winner, winnerStarted, skeletonsGranted ? reward : 0, rewardUnitSid, wightsGranted ? wights : 0));
		LogPostBattle(
			"granted hero="
			+ heroSid
			+ " rewardUnit="
			+ rewardUnitSid
			+ " reward="
			+ reward
			+ " before="
			+ before
			+ " after="
			+ after
			+ " enemyLostStacks="
			+ enemyStacks
			+ " blockedLostStacks="
			+ blockedStacks
			+ " eligibleSquadValue="
			+ eligibleValue
			+ " conversionPercent="
			+ conversionPercent.ToString("0.##")
			+ lawNotes
			+ " source="
			+ source);
		// Only the local player's own raise gets the popup; AI necromancers raise silently (user 2026-11-13: the popup
		// kept appearing at turn end while playing Tower).
		if (showNotification && winnerStarted != null && winnerStarted.controlType == TransferSide.EControlType.ME)
		{
			if (skeletonsGranted)
				Homm3SkeletalNecromancyNotificationBootstrap.Show(reward, rewardUnitSid);
			else if (wightsGranted)
				Homm3SkeletalNecromancyNotificationBootstrap.Show(wights, DarkAscensionRewardUnitSid);
		}
		return true;
	}

	/// <summary>law pass 2026-11-21: Necropolis law level (0 = not taken) for a battle side; tries each owner in turn, fail closed.</summary>
	private static int NecropolisLawRank(int lawIndex, params TransferSide[] sides)
	{
		if (sides == null)
			return 0;
		foreach (var side in sides)
		{
			if (side == null)
				continue;
			foreach (var owner in new object[] { side, side.logicHero })
			{
				if (owner == null)
					continue;
				try
				{
					var rank = Homm3CustomFactionLawRuntime.CustomLawRank(owner, lawIndex, NecropolisFactionSid);
					if (rank > 0)
						return rank;
				}
				catch
				{
					// fail closed: try the next owner
				}
			}
		}
		return 0;
	}

	/// <summary>
	/// building pass 2026-11-22: true when the side (or its hero) owns at least one Necropolis with the building
	/// constructed. Tries each owner in turn; any read error counts as not owned.
	/// </summary>
	private static bool NecropolisSideOwnsBuilding(string buildingSid, params TransferSide[] sides)
	{
		if (sides == null)
			return false;
		foreach (var side in sides)
		{
			if (side == null)
				continue;
			foreach (var owner in new object[] { side, side.logicHero })
			{
				if (owner == null)
					continue;
				try
				{
					if (Homm3TownBuildingReader.SideHasBuilding(owner, buildingSid, NecropolisCitySid))
						return true;
				}
				catch
				{
					// fail closed: try the next owner
				}
			}
		}
		return false;
	}

	/// <summary>
	/// law pass 2026-11-21: Unearthed Graves (#8). The winner is a garrison with no hero, and the player who owns it holds
	/// the law. The owner is read from the side itself, or from its side id when that id is unique in the battle
	/// (a garrison side carries no hero to resolve laws through). Any doubt: no reward.
	/// </summary>
	private static bool IsUnearthedGravesGarrison(TransferBattle transferBattle, TransferSide side)
	{
		try
		{
			if (side == null || side.hero != null || side.logicHero != null || side.typeInWorld != TransferSide.EType.Type_Garnison)
				return false;
			return GarrisonOwnerLawRank(transferBattle, side, LawUnearthedGraves) > 0;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>
	/// Law level of the player who owns a hero-less side (0 = not taken or unknown): read from the side itself, or from its
	/// side id when that id is unique in the battle. law pass 2026-11-25: shared by Unearthed Graves (#8) and Bone Tithe (#7).
	/// </summary>
	private static int GarrisonOwnerLawRank(TransferBattle transferBattle, TransferSide side, int lawIndex)
	{
		try
		{
			if (side == null)
				return 0;
			var direct = NecropolisLawRank(lawIndex, side);
			if (direct > 0)
				return direct;
			if (!TryReadIntMember(side, GameSymbols.BattleEventLaws.TransferSideSideIdMembers, out var sideId) || sideId < 0)
				return 0;
			if (transferBattle?.sides == null)
				return 0;
			foreach (var other in transferBattle.sides)
			{
				if (other == null || ReferenceEquals(other, side) || other.Pointer == side.Pointer)
					continue;
				if (TryReadIntMember(other, GameSymbols.BattleEventLaws.TransferSideSideIdMembers, out var otherId) && otherId == sideId)
					return 0;
			}
			if (!Homm3BattleUnitLawOwnerRegistry.TryResolveGlobalDataSide(sideId, out var dataSide, out _) || dataSide == null)
				return 0;
			return Math.Max(0, Homm3CustomFactionLawRuntime.CustomLawRank(dataSide, lawIndex, NecropolisFactionSid));
		}
		catch
		{
			return 0;
		}
	}

	/// <summary>law pass 2026-11-25: Unearthed Graves (#8) hero part. True when the winner defended a town in a siege; fail closed.</summary>
	private static bool IsSiegeDefender(TransferBattle startedTransferBattle, TransferBattle transferBattle, int winnerIndex)
	{
		try
		{
			if (Homm3TownBuildingReader.TryGetSiegeDefender(startedTransferBattle, out _, out var defenderIndex, out _))
				return defenderIndex == winnerIndex;
			return Homm3TownBuildingReader.TryGetSiegeDefender(transferBattle, out _, out defenderIndex, out _) && defenderIndex == winnerIndex;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>
	/// law pass 2026-11-25: Bone Tithe (#7). Pays the winner's side Gold equal to the level's share of the Gold cost of the
	/// creatures just raised; returns a log note. Any read or grant failure pays nothing.
	/// </summary>
	private static string PayBoneTithe(int rank, TransferSide winner, TransferSide winnerStarted, int raised, string raisedSid, int wights)
	{
		try
		{
			var share = BoneTitheGoldShare[Math.Min(rank, BoneTitheGoldShare.Length) - 1];
			var cost = (long)raised * UnitGoldCost(raisedSid) + (long)wights * UnitGoldCost(DarkAscensionRewardUnitSid);
			var gold = (int)Math.Min(int.MaxValue, Math.Floor(cost * share));
			if (gold <= 0)
				return "boneTithe=L" + rank + " gold=0 (cost " + cost + ")";
			var owner = winnerStarted ?? winner;
			if (!TryReadIntMember(owner, GameSymbols.BattleEventLaws.TransferSideSideIdMembers, out var sideId) || sideId < 0)
				return "boneTithe=L" + rank + " FAILED (side id unreadable)";
			return Homm3CovePlunderHook.Grant(sideId, GoldResourceName, gold, out var before, out var after, out var fail)
				? "boneTithe=L" + rank + " +" + gold + " gold (" + before + "->" + after + ")"
				: "boneTithe=L" + rank + " FAILED (" + fail + ")";
		}
		catch (Exception ex)
		{
			return "boneTithe FAILED (" + ex.GetBaseException().Message + ")";
		}
	}

	/// <summary>law pass 2026-11-25: Bone Tithe (#7). Gold in a unit's recruitment cost (0 when unreadable).</summary>
	private static int UnitGoldCost(string sid)
	{
		var costs = ResolveUnitLogicConfigBySid(sid)?.unitCost?.costResArray;
		for (var i = 0; costs != null && i < costs.Length; i++)
		{
			if (string.Equals(NormalizeSid(costs[i]?.name), GoldResourceName, StringComparison.Ordinal))
				return ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is int cost ? Math.Max(0, cost) : 0;
		}
		return 0;
	}

	private static string ResolveRewardUnitSid(TransferSide winner, TransferSide winnerStarted)
	{
		if (HasHeroSubSkill(winner, ArcherRewardSubSkillSid) || HasHeroSubSkill(winnerStarted, ArcherRewardSubSkillSid))
			return SkeletonArcherRewardUnitSid;
		if (HasHeroSubSkill(winner, WarriorRewardSubSkillSid) || HasHeroSubSkill(winnerStarted, WarriorRewardSubSkillSid))
			return SkeletonWarriorRewardUnitSid;
		return SkeletonRewardUnitSid;
	}

	private static int ResolveRewardUnitSquadValue(string sid)
	{
		var config = ResolveUnitLogicConfigBySid(sid);
		return config != null ? Math.Max(0, config.squadValue) : 0;
	}

	private static float ResolveNecromancyConversionPercent(TransferSide winner, TransferSide winnerStarted)
	{
		// Overlay still writes necromancyPerBonus 0.10/0.20/0.30 as rank keys only.
		var raw = ReadNecromancyPerBonus(winner);
		if (raw <= 0f)
			raw = ReadNecromancyPerBonus(winnerStarted);
		if (raw >= 0.295f)
			return ExpertConversionPercent;
		if (raw >= 0.195f)
			return AdvancedConversionPercent;
		if (raw >= 0.095f)
			return BasicConversionPercent;
		return 0f;
	}

	private static float ReadNecromancyPerBonus(TransferSide side)
	{
		foreach (var heroStat in ReadHeroStats(side))
		{
			var value = ReadFloatMember(heroStat, GameSymbols.SkeletalNecromancy.HeroStatNecromancyPerBonusMembers);
			if (value > 0f)
				return value;
		}
		return 0f;
	}

	private static IEnumerable<object> ReadHeroStats(TransferSide side)
	{
		if (side == null)
			yield break;
		var emitted = new HashSet<object>();

		var transferHero = ReadMember(side, GameSymbols.SkeletalNecromancy.TransferSideHeroMembers);
		foreach (var heroStat in ReadStatsFromOwner(transferHero, GameSymbols.SkeletalNecromancy.TransferHeroStatMembers, emitted))
			yield return heroStat;

		var logicHero = ReadMember(side, GameSymbols.SkeletalNecromancy.TransferSideLogicHeroMembers);
		foreach (var heroStat in ReadStatsFromOwner(logicHero, GameSymbols.SkeletalNecromancy.LogicHeroStatMembers, emitted))
			yield return heroStat;

		var dataHero = ReadMember(logicHero, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers);
		foreach (var heroStat in ReadStatsFromOwner(dataHero, GameSymbols.SkeletalNecromancy.DataHeroStatMembers, emitted))
			yield return heroStat;
	}

	private static bool HasHeroSubSkill(TransferSide side, string subSkillSid)
	{
		if (side == null || string.IsNullOrWhiteSpace(subSkillSid))
			return false;
		foreach (var dataHero in ReadDataHeroes(side))
		{
			var skills = ReadMember(dataHero, GameSymbols.SkeletalNecromancy.DataHeroSkillsMembers);
			var skillList = ReadMember(skills, GameSymbols.SkeletalNecromancy.HeroSkillsListMembers);
			foreach (var heroSkill in EnumerateObjects(skillList))
			{
				var subSkills = ReadMember(heroSkill, GameSymbols.SkeletalNecromancy.HeroSkillSubSkillsMembers);
				foreach (var subSkill in EnumerateObjects(subSkills))
				{
					var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.SkeletalNecromancy.HeroSubSkillSidMembers));
					if (string.Equals(sid, subSkillSid, StringComparison.Ordinal) && Homm3DungeonDraconicDominionHook.IsSubSkillActive(subSkill))
						return true;
				}
			}
		}
		return false;
	}

	private static IEnumerable<object> ReadDataHeroes(TransferSide side)
	{
		if (side == null)
			yield break;
		var emitted = new HashSet<object>();
		var logicHero = ReadMember(side, GameSymbols.SkeletalNecromancy.TransferSideLogicHeroMembers);
		var dataHero = ReadMember(logicHero, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers);
		if (dataHero != null && emitted.Add(dataHero))
			yield return dataHero;
	}

	private static IEnumerable<object> ReadStatsFromOwner(object owner, string[] memberNames, HashSet<object> emitted)
	{
		if (owner == null || memberNames == null || emitted == null)
			yield break;
		foreach (var name in memberNames)
		{
			var stat = ReadMember(owner, name);
			if (stat != null && emitted.Add(stat))
				yield return stat;
		}
	}

	private static List<int> ResolveLoserIndices(BattleResultInfo resultInfo)
	{
		var result = new List<int>();
		var losers = ReadMember(resultInfo, GameSymbols.SkeletalNecromancy.BattleResultLosersFields)
		             ?? ReadIl2CppReferenceField(resultInfo, GameSymbols.SkeletalNecromancy.BattleResultLosersFields);
		foreach (var loser in EnumerateObjects(losers))
		{
			if (!TryReadIntMember(loser, GameSymbols.SkeletalNecromancy.BattleResultLoserIndexFields, out var loserIndex))
				continue;
			if (loserIndex >= 0)
				result.Add(loserIndex);
		}
		return result;
	}

	private static int SumEligibleLostSquadValue(TransferSide started, TransferSide after, out int enemyStacks, out int blockedStacks, StringBuilder blockedDetails, bool allowUndead = false)
	{
		enemyStacks = 0;
		blockedStacks = 0;
		if (started?.units == null)
			return 0;

		var value = 0;
		foreach (var beforeUnit in started.units)
		{
			if (beforeUnit == null || beforeUnit.stacks <= 0)
				continue;
			var afterUnit = FindMatchingAfterBattleUnit(after, beforeUnit);
			var afterStacks = afterUnit != null ? Math.Max(0, afterUnit.stacks) : 0;
			var lostStacks = Math.Max(0, beforeUnit.stacks - afterStacks);
			if (lostStacks <= 0)
				continue;

			enemyStacks++;
			var config = ResolveUnitLogicConfig(beforeUnit);
			var blockedReason = GetBlockedReason(config) ?? GetBlockedHomm3SidReason(beforeUnit.configSid);
			// law pass 2026-11-25: Grave Robbers (#9): Undead losses count (constructs and elementals stay out).
			if (blockedReason != null && allowUndead && IsGraveRobbersUndead(config, beforeUnit.configSid))
				blockedReason = null;
			if (blockedReason != null)
			{
				blockedStacks++;
				AppendBlockedDetail(blockedDetails, beforeUnit, config, lostStacks, blockedReason);
				continue;
			}
			value += Math.Max(0, config.squadValue) * lostStacks;
		}
		return value;
	}

	private static TransferUnit FindMatchingAfterBattleUnit(TransferSide after, TransferUnit beforeUnit)
	{
		if (after?.units == null || beforeUnit == null)
			return null;
		foreach (var candidate in after.units)
		{
			if (candidate == null)
				continue;
			if (candidate.slotPos == beforeUnit.slotPos
			    && string.Equals(NormalizeSid(candidate.configSid), NormalizeSid(beforeUnit.configSid), StringComparison.Ordinal))
				return candidate;
		}
		return null;
	}

	private static bool GrantSkeletonsToWinner(TransferSide winner, string rewardUnitSid, int count)
	{
		if (winner == null || string.IsNullOrWhiteSpace(rewardUnitSid) || count <= 0)
			return false;
		var reward = new TransferUnit(rewardUnitSid, count, 0);
		_transferSideAddSpawnedUnitMethod.Invoke(winner, new object[] { reward, true });
		_transferSideSortBySlotMethod.Invoke(winner, Array.Empty<object>());
		return true;
	}

	private static int CountUnitStacks(TransferSide side, string sid)
	{
		if (side?.units == null)
			return 0;
		var total = 0;
		foreach (var unit in side.units)
		{
			if (unit != null && string.Equals(NormalizeSid(unit.configSid), sid, StringComparison.Ordinal))
				total += Math.Max(0, unit.stacks);
		}
		return total;
	}

	private static void LogPostBattle(string message)
	{
		if (_loggedPostBattleResults++ < 24)
			_log?.LogInfo("HoMM3 skeletal necromancy post-battle: " + message + ".");
	}

	private static bool IsNecropolisHeroSide(TransferSide side, out string heroSid)
	{
		heroSid = null;
		if (side == null)
			return false;
		heroSid = NormalizeSid(side.hero?.configId);
		if (string.IsNullOrWhiteSpace(heroSid))
			return false;
		return heroSid.StartsWith("homm3_necropolis_hero_", StringComparison.Ordinal)
		       || heroSid.StartsWith("hero_homm3_necropolis_", StringComparison.Ordinal);
	}

	/// <summary>
	/// HoMM3 non-living lines. The overlay rewrites donor 'undead' class tags to the faction sid and the
	/// undead/construct class lives only on the view config, so the logic-tag check above misses them.
	/// </summary>
	private static string GetBlockedHomm3SidReason(string configSid)
	{
		var sid = NormalizeSid(configSid);
		if (string.IsNullOrEmpty(sid) || !sid.StartsWith("h3_", StringComparison.Ordinal))
			return null;
		if (Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(sid, out var factionSid)
		    && string.Equals(factionSid, "homm3_necropolis", StringComparison.Ordinal))
			return "homm3Undead:" + sid;
		if (sid.Contains("_elemental")
		    || sid.StartsWith("h3_golem", StringComparison.Ordinal)
		    || sid.StartsWith("h3_gargoyle", StringComparison.Ordinal))
			return "homm3NonLiving:" + sid;
		return null;
	}

	/// <summary>law pass 2026-11-25: Grave Robbers (#9). An Undead creature (HoMM3 Necropolis line or undead tag), never a construct, embodiment or elemental.</summary>
	private static bool IsGraveRobbersUndead(UnitLogicConfig config, string configSid)
	{
		if (config == null)
			return false;
		var sidReason = GetBlockedHomm3SidReason(configSid);
		if (sidReason != null)
			return sidReason.StartsWith("homm3Undead:", StringComparison.Ordinal);
		var undead = false;
		for (var i = 0; config.tags != null && i < config.tags.Length; i++)
		{
			var tag = NormalizeSid(config.tags[i]);
			if (string.Equals(tag, "construct", StringComparison.Ordinal)
			    || string.Equals(tag, "embodiment", StringComparison.Ordinal)
			    || string.Equals(tag, "base_class_construct", StringComparison.Ordinal)
			    || string.Equals(tag, "base_class_embodiment", StringComparison.Ordinal))
				return false;
			if (string.Equals(tag, "undead", StringComparison.Ordinal) || string.Equals(tag, "base_class_undead", StringComparison.Ordinal))
				undead = true;
		}
		return undead;
	}

	private static string GetBlockedReason(UnitLogicConfig config)
	{
		if (config == null || !config.leaveCorpse)
			return config == null ? "nullConfig" : "noCorpse";
		if (config.tags == null)
			return null;
		for (var i = 0; i < config.tags.Length; i++)
		{
			var tag = NormalizeSid(config.tags[i]);
			if (string.Equals(tag, "undead", StringComparison.Ordinal)
			    || string.Equals(tag, "construct", StringComparison.Ordinal)
			    || string.Equals(tag, "embodiment", StringComparison.Ordinal)
			    || string.Equals(tag, "base_class_undead", StringComparison.Ordinal)
			    || string.Equals(tag, "base_class_construct", StringComparison.Ordinal)
			    || string.Equals(tag, "base_class_embodiment", StringComparison.Ordinal))
				return "tag:" + tag;
		}
		return null;
	}

	private static void AppendBlockedDetail(StringBuilder target, TransferUnit unit, UnitLogicConfig config, int lostStacks, string reason)
	{
		if (target == null || target.Length > 240)
			return;
		if (target.Length > 0)
			target.Append(';');
		target.Append(NormalizeSid(unit?.configSid) ?? "?");
		target.Append(":lost=");
		target.Append(lostStacks);
		target.Append(":reason=");
		target.Append(reason ?? "?");
		target.Append(":value=");
		target.Append(config != null ? Math.Max(0, config.squadValue).ToString() : "?");
		target.Append(":corpse=");
		target.Append(config != null && config.leaveCorpse ? "1" : "0");
		if (config?.tags != null)
		{
			target.Append(":tags=");
			for (var i = 0; i < Math.Min(config.tags.Length, 4); i++)
			{
				if (i > 0)
					target.Append(',');
				target.Append(NormalizeSid(config.tags[i]) ?? "?");
			}
		}
	}

	private static UnitLogicConfig ResolveUnitLogicConfig(TransferUnit transfer)
	{
		if (transfer == null)
			return null;
		var direct = ReadMember(transfer, GameSymbols.SkeletalNecromancy.TransferUnitLogicConfigGetter.NameHints) as UnitLogicConfig
		             ?? ReadIl2CppReferenceField(transfer, GameSymbols.SkeletalNecromancy.TransferUnitLogicConfigFields) as UnitLogicConfig;
		if (direct != null)
			return direct;
		return ResolveUnitLogicConfigBySid(transfer.configSid);
	}

	private static UnitLogicConfig ResolveUnitLogicConfigBySid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var logicTable = ResolveUnitLogicConfigTable();
		if (logicTable == null)
			return null;
		return TryLookupConfigBySid(logicTable, sid.Trim(), out UnitLogicConfig logic) ? logic : null;
	}

	private static object ResolveUnitLogicConfigTable()
	{
		if (_unitLogicConfigTable != null)
			return _unitLogicConfigTable;

		var rootType = _configRootType ?? ResolveTypeByNames(typeof(TransferSide).Assembly, GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		if (rootType == null)
			return null;
		_configRootType = rootType;

		var root = ReadStaticMember(rootType, GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers);
		if (root == null)
			return null;

		_unitLogicConfigTable = ReadMember(root, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigTables);
		return _unitLogicConfigTable;
	}

	private static bool TryLookupConfigBySid<T>(object table, string sid, out T value) where T : class
	{
		value = null;
		if (table == null || string.IsNullOrWhiteSpace(sid))
			return false;
		try
		{
			var method = FindConfigTableTryGetMethod(table.GetType(), typeof(T));
			if (method == null)
				return false;
			var args = new object[] { sid, null };
			if (!(method.Invoke(table, args) is bool found) || !found)
				return false;
			value = args[1] as T;
			return value != null;
		}
		catch
		{
			return false;
		}
	}

	private static MethodInfo FindConfigTableTryGetMethod(Type tableType, Type valueType)
	{
		if (tableType == null || valueType == null)
			return null;
		foreach (var method in tableType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType != typeof(bool) || !NameMatches(method, GameSymbols.UnitPreviewAbilityIcons.ConfigTableTryGet.NameHints))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != 2 || ps[0].ParameterType != typeof(string))
				continue;
			if (!ps[1].ParameterType.IsByRef || ps[1].ParameterType.GetElementType() != valueType)
				continue;
			return method;
		}
		return null;
	}

	private static int CalculateReward(int eligibleSquadValue, float conversionPercent, int rewardUnitSquadValue)
	{
		if (eligibleSquadValue <= 0 || rewardUnitSquadValue <= 0)
			return 0;
		return Math.Max(0, (int)Math.Floor(eligibleSquadValue * conversionPercent / rewardUnitSquadValue));
	}

	private static bool NameMatches(string candidate, string[] names)
	{
		if (string.IsNullOrWhiteSpace(candidate) || names == null)
			return false;
		for (var i = 0; i < names.Length; i++)
		{
			if (string.Equals(candidate, names[i], StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool NameMatches(MemberInfo candidate, string[] names)
	{
		if (candidate == null || names == null)
			return false;
		return NameMatches(candidate.Name, names)
		       || NameMatches(GameMember.ReadObfuscatedName(candidate), names);
	}

	private static IEnumerable<object> EnumerateObjects(object value)
	{
		if (value == null)
			yield break;

		if (value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}

		var type = value.GetType();
		var count = TryReadCount(value, type);
		if (count == null || count.Value <= 0)
			yield break;

		var indexer = ResolveIntIndexer(type);
		if (indexer == null)
			yield break;

		for (var i = 0; i < count.Value; i++)
		{
			object item = null;
			try
			{
				item = indexer.Invoke(value, new object[] { i });
			}
			catch
			{
			}

			if (item != null)
				yield return item;
		}
	}

	private static int? TryReadCount(object value, Type type)
	{
		if (value == null || type == null)
			return null;

		try
		{
			var prop = type.GetProperty("Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (prop != null && prop.GetIndexParameters().Length == 0 && prop.GetValue(value, null) is int propCount)
				return propCount;
		}
		catch
		{
		}

		try
		{
			var method = type.GetMethod("get_Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (method != null && method.GetParameters().Length == 0 && method.Invoke(value, Array.Empty<object>()) is int methodCount)
				return methodCount;
		}
		catch
		{
		}

		return null;
	}

	private static MethodInfo ResolveIntIndexer(Type type)
	{
		if (type == null)
			return null;

		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType == typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 1 && ps[0].ParameterType == typeof(int)
			    && (string.Equals(method.Name, "get_Item", StringComparison.Ordinal)
			        || string.Equals(method.Name, "get_ItemOf", StringComparison.Ordinal)))
				return method;
		}

		return null;
	}

	private static Type ResolveTypeByNames(Assembly asm, IEnumerable<string> names)
	{
		if (asm == null || names == null)
			return null;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null)
				return type;
			type = GameMember.FindType("battle.skeletalNecromancy.type." + name, name);
			if (type != null && type.Assembly == asm)
				return type;
		}
		return null;
	}

	private static IEnumerable<Type> ResolveTypesByNames(Assembly asm, IEnumerable<string> names)
	{
		if (asm == null || names == null)
			yield break;
		var emitted = new HashSet<Type>();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null && emitted.Add(type))
				yield return type;
			type = GameMember.FindType("battle.skeletalNecromancy.type." + name, name);
			if (type != null && type.Assembly == asm && emitted.Add(type))
				yield return type;
		}
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj, null);
			}
			catch
			{
			}
			try
			{
				var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (field != null)
					return field.GetValue(obj);
			}
			catch
			{
			}
			try
			{
				var method = type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (method != null && method.GetParameters().Length == 0)
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch
			{
			}
		}
		return null;
	}

	private static object ReadMemberFieldOnly(object obj, params string[] names)
	{
		return ReadMemberFieldOnlyDeep(obj, names);
	}

	private static object ReadIl2CppReferenceField(object owner, params string[] logicalFieldNames)
	{
		if (owner == null || logicalFieldNames == null)
			return null;

		var reflected = ReadMemberFieldOnlyDeep(owner, logicalFieldNames);
		if (reflected != null)
			return reflected;

		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;

		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var logicalName in logicalFieldNames)
			{
				var native = TryReadNativeReferenceField(owner, type, logicalName);
				if (native != null)
					return native;
			}
		}

		return null;
	}

	private static object TryReadNativeReferenceField(object owner, Type ownerType, string logicalName)
	{
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero || ownerType == null)
			return null;

		var classPtr = GetNativeClassPtr(ownerType);
		if (classPtr == IntPtr.Zero)
			return null;

		foreach (var candidate in ExpandNativeFieldCandidates(logicalName))
		{
			try
			{
				var fieldPtr = TryGetGeneratedNativeFieldInfoPtr(ownerType, candidate.NativeInfoName);
				if (fieldPtr == IntPtr.Zero)
					fieldPtr = IL2CPP.GetIl2CppField(classPtr, candidate.Il2CppName);
				if (fieldPtr == IntPtr.Zero)
					continue;

				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				return Il2CppObjectPool.Get<Il2CppObjectBase>(valuePtr);
			}
			catch
			{
			}
		}

		return null;
	}

	private static bool TryReadNativeIntField(object owner, Type ownerType, string logicalName, out int value)
	{
		value = 0;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero || ownerType == null)
			return false;

		var classPtr = GetNativeClassPtr(ownerType);
		if (classPtr == IntPtr.Zero)
			return false;

		foreach (var candidate in ExpandNativeFieldCandidates(logicalName))
		{
			try
			{
				var fieldPtr = TryGetGeneratedNativeFieldInfoPtr(ownerType, candidate.NativeInfoName);
				if (fieldPtr == IntPtr.Zero)
					fieldPtr = IL2CPP.GetIl2CppField(classPtr, candidate.Il2CppName);
				if (fieldPtr == IntPtr.Zero)
					continue;

				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				value = Marshal.ReadInt32(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				return true;
			}
			catch
			{
			}
		}

		return false;
	}

	private static IEnumerable<(string Il2CppName, string NativeInfoName)> ExpandNativeFieldCandidates(string logicalName)
	{
		if (string.IsNullOrWhiteSpace(logicalName))
			yield break;

		yield return (logicalName, "NativeFieldInfoPtr_" + logicalName);

		if (logicalName.StartsWith("<", StringComparison.Ordinal) && logicalName.EndsWith(">k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.IndexOf('>', StringComparison.Ordinal) - 1);
			yield return (logicalName, "NativeFieldInfoPtr__" + inner + "_k__BackingField");
			yield return (inner, "NativeFieldInfoPtr_" + inner);
		}

		if (logicalName.StartsWith("_", StringComparison.Ordinal) && logicalName.EndsWith("_k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.Length - "_k__BackingField".Length - 1);
			yield return ("<" + inner + ">k__BackingField", "NativeFieldInfoPtr_<" + inner + ">k__BackingField");
			yield return (inner, "NativeFieldInfoPtr_" + inner);
		}
	}

	private static IntPtr GetNativeClassPtr(Type managedType)
	{
		if (managedType == null)
			return IntPtr.Zero;

		try
		{
			var storeType = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			var nativeClassPtrField = storeType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public);
			if (nativeClassPtrField?.FieldType == typeof(IntPtr))
			{
				var value = (IntPtr)nativeClassPtrField.GetValue(null);
				if (value != IntPtr.Zero)
					return value;
			}
		}
		catch
		{
		}

		try
		{
			var field = managedType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field?.FieldType == typeof(IntPtr))
				return (IntPtr)field.GetValue(null);
		}
		catch
		{
		}

		return IntPtr.Zero;
	}

	private static IntPtr TryGetGeneratedNativeFieldInfoPtr(Type managedType, string fieldInfoName)
	{
		if (managedType == null || string.IsNullOrWhiteSpace(fieldInfoName))
			return IntPtr.Zero;
		try
		{
			var field = managedType.GetField(fieldInfoName, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field == null || field.FieldType != typeof(IntPtr))
				return IntPtr.Zero;
			return (IntPtr)field.GetValue(null);
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	private static object ReadMemberFieldOnlyDeep(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;

		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
					if (field != null)
						return field.GetValue(obj);
				}
				catch
				{
				}
			}
		}

		return null;
	}

	private static object ReadStaticMember(Type type, params string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(null, null);
			}
			catch
			{
			}
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(null);
			}
			catch
			{
			}
			try
			{
				var method = type.GetMethod(name, flags);
				if (method != null && method.GetParameters().Length == 0)
					return method.Invoke(null, Array.Empty<object>());
			}
			catch
			{
			}
		}
		return null;
	}

	private static string TryReadString(object obj, params string[] names)
	{
		return ReadMember(obj, names) as string;
	}

	private static int ReadIntMember(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		if (value is int i)
			return i;
		return 0;
	}

	private static float ReadFloatMember(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		if (value is float f)
			return f;
		if (value is double d)
			return (float)d;
		if (value is int i)
			return i;
		return 0f;
	}

	private static bool TryReadIntMember(object obj, string[] names, out int result)
	{
		result = 0;
		var value = ReadMember(obj, names);
		if (value is int reflected)
		{
			result = reflected;
			return true;
		}

		if (obj == null || names == null)
			return false;

		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in names)
			{
				if (TryReadNativeIntField(obj, type, name, out result))
					return true;
			}
		}

		return false;
	}

	private static bool? ReadBoolMember(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		if (value is bool b)
			return b;
		return null;
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		var declaring = method.DeclaringType != null ? method.DeclaringType.FullName : "?";
		return declaring + "." + method.Name;
	}
}

internal static class Homm3SkeletalNecromancyNotificationBootstrap
{
	private const string GoName = "Homm3SkeletalNecromancyNotification";
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
				ClassInjector.RegisterTypeInIl2Cpp<Homm3SkeletalNecromancyNotificationBehaviour>();
				_registered = true;
			}

			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<Homm3SkeletalNecromancyNotificationBehaviour>() == null)
				Plugin.LogSource?.LogError("HoMM3 skeletal necromancy notification: AddComponent returned null.");
			UnityEngine.Object.DontDestroyOnLoad(go);
			_attached = true;
			Plugin.LogSource?.LogInfo("HoMM3 skeletal necromancy notification: IMGUI host registered.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 skeletal necromancy notification: host registration failed: " + ex.Message);
		}
	}

	internal static void Show(int count, string rewardUnitSid)
	{
		if (count <= 0 || string.IsNullOrWhiteSpace(rewardUnitSid))
			return;
		Ensure();
		Homm3SkeletalNecromancyNotificationBehaviour.Show(count, rewardUnitSid);
	}
}

public sealed class Homm3SkeletalNecromancyNotificationBehaviour : MonoBehaviour
{
	private const float DurationSeconds = 9f;
	private const float PanelWidth = 620f;
	private const float PanelHeight = 260f;
	private const string PanelTextureRelativePath = "homm3_ui/necromancy_dialog_panel.png";
	private const string Homm3NecromancyPrefix = "Practicing the dark arts of necromancy, your hero is able to raise ";
	private const string Homm3NecromancyMiddle = " of the enemy's dead to return under their service as ";
	private static readonly object LockObject = new();
	private static int s_count;
	private static string s_rewardUnitSid;
	private static float s_until;
	private static GUIStyle s_panelStyle;
	private static GUIStyle s_bodyStyle;
	private static GUIStyle s_rewardStyle;
	private static GUIStyle s_buttonStyle;
	private static Texture2D s_panelTexture;
	private static readonly Dictionary<string, Sprite> s_portraits = new();
	private static readonly HashSet<string> s_portraitResolved = new();
	private static readonly HashSet<string> s_missingPortraitLogged = new();
	private static bool s_loggedMissingPanelTexture;
	private static int s_styleScaleBucket = -1;

	internal static void Show(int count, string rewardUnitSid)
	{
		if (count <= 0 || string.IsNullOrWhiteSpace(rewardUnitSid))
			return;
		lock (LockObject)
		{
			s_count = count;
			s_rewardUnitSid = rewardUnitSid.Trim();
			s_until = Time.realtimeSinceStartup + DurationSeconds;
		}
	}

	private void OnGUI()
	{
		int count;
		string rewardUnitSid;
		float until;
		lock (LockObject)
		{
			count = s_count;
			rewardUnitSid = s_rewardUnitSid;
			until = s_until;
		}
		if (count <= 0 || string.IsNullOrWhiteSpace(rewardUnitSid) || Time.realtimeSinceStartup > until)
			return;

		if (!EnsureStyles())
			return;
		// Height-relative scale matching the Castle Elite Strategem indicator (source/static; 4K runtime unproven).
		var scale = Mathf.Clamp(Screen.height / 720f, 0.75f, 3f);
		var margin = Mathf.Clamp(16f * scale, 12f, 48f);
		var width = Mathf.Min(PanelWidth * scale, Mathf.Max(1f, Screen.width - margin * 2f));
		var height = Mathf.Min(PanelHeight * scale, Mathf.Max(1f, Screen.height - margin * 2f));
		var rect = new Rect((Screen.width - width) * 0.5f, Mathf.Clamp(Screen.height * 0.1f, margin, Mathf.Max(margin, Screen.height - height - margin)), width, height);

		GUI.Box(rect, GUIContent.none, s_panelStyle);
		var pad = 20f * scale;
		var portraitSize = 58f * scale;
		var bodyRect = new Rect(rect.x + pad, rect.y + pad, rect.width - pad * 2f, 116f * scale);
		var portraitRect = new Rect(rect.x + (rect.width - portraitSize) * 0.5f, bodyRect.yMax + 4f * scale, portraitSize, portraitSize);
		var rewardRect = new Rect(rect.x + pad, portraitRect.yMax + 4f * scale, rect.width - pad * 2f, 28f * scale);
		var buttonRect = new Rect(rect.x + (rect.width - 78f * scale) * 0.5f, rect.yMax - 36f * scale, 78f * scale, 26f * scale);

		GUI.Label(bodyRect, BuildBody(count, rewardUnitSid), s_bodyStyle);
		DrawPortrait(portraitRect, rewardUnitSid);
		GUI.Label(rewardRect, BuildRewardLine(count, rewardUnitSid), s_rewardStyle);
		if (GUI.Button(buttonRect, "OK", s_buttonStyle))
			Hide();
	}

	private static void Hide()
	{
		lock (LockObject)
		{
			s_count = 0;
			s_rewardUnitSid = null;
			s_until = 0f;
		}
	}

	private static string BuildBody(int count, string rewardUnitSid)
	{
		var names = RewardUnitNames(rewardUnitSid);
		return Homm3NecromancyPrefix
		       + FormatBodyCount(count)
		       + Homm3NecromancyMiddle
		       + (count == 1 ? "a " + names.singular : names.plural)
		       + ".";
	}

	private static string BuildRewardLine(int count, string rewardUnitSid)
	{
		var names = RewardUnitNames(rewardUnitSid);
		return count + " " + (count == 1 ? names.singular : names.plural);
	}

	private static string FormatBodyCount(int count)
	{
		return count == 1 ? "one" : count.ToString();
	}

	private static void DrawPortrait(Rect rect, string rewardUnitSid)
	{
		if (!TryResolvePortrait(rewardUnitSid, out var sprite) || sprite == null || sprite.texture == null)
			return;
		var texture = sprite.texture;
		var tr = sprite.textureRect;
		var coords = new Rect(tr.x / texture.width, tr.y / texture.height, tr.width / texture.width, tr.height / texture.height);
		GUI.DrawTextureWithTexCoords(rect, texture, coords, true);
	}

	private static bool TryResolvePortrait(string rewardUnitSid, out Sprite sprite)
	{
		rewardUnitSid = NormalizeRewardSid(rewardUnitSid);
		if (s_portraitResolved.Contains(rewardUnitSid))
		{
			s_portraits.TryGetValue(rewardUnitSid, out sprite);
			return sprite != null;
		}

		if (Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(rewardUnitSid, out sprite) && sprite)
		{
			s_portraitResolved.Add(rewardUnitSid);
			s_portraits[rewardUnitSid] = sprite;
			return true;
		}

		s_portraitResolved.Add(rewardUnitSid);
		if (s_missingPortraitLogged.Add(rewardUnitSid))
		{
			Plugin.LogSource?.LogWarning("HoMM3 skeletal necromancy notification: missing portrait sprite sid='" + rewardUnitSid + "'.");
		}
		sprite = null;
		return false;
	}

	private static (string singular, string plural) RewardUnitNames(string rewardUnitSid)
	{
		switch (NormalizeRewardSid(rewardUnitSid))
		{
			case "h3_skeleton_upg":
				return ("Skeleton Warrior", "Skeleton Warriors");
			case "h3_skeleton_upg_alt":
				return ("Skeleton Archer", "Skeleton Archers");
			default:
				return ("Skeleton", "Skeletons");
		}
	}

	private static string NormalizeRewardSid(string rewardUnitSid)
	{
		return string.IsNullOrWhiteSpace(rewardUnitSid) ? "h3_skeleton" : rewardUnitSid.Trim();
	}

	private static bool EnsureStyles()
	{
		var bucket = Mathf.Clamp(Screen.height / 180, 4, 12);
		if (s_panelStyle != null && s_styleScaleBucket == bucket)
			return true;
		s_styleScaleBucket = bucket;
		if (s_panelTexture == null)
		{
			if (!TryLoadPanelTexture(out var panelTexture))
			{
				Hide();
				return false;
			}
			s_panelTexture = panelTexture;
		}

		s_panelStyle = new GUIStyle(GUI.skin.box)
		{
			normal = { background = s_panelTexture },
			border = CreateRectOffset(12, 12, 12, 12),
			padding = CreateRectOffset(16, 16, 16, 16)
		};
		s_bodyStyle = new GUIStyle(GUI.skin.label)
		{
			alignment = TextAnchor.UpperCenter,
			wordWrap = true,
			fontSize = Mathf.Clamp(bucket * 4, 18, 44),
			fontStyle = FontStyle.Bold,
			normal = { textColor = new Color(0.98f, 0.93f, 0.82f, 1f) }
		};
		s_rewardStyle = new GUIStyle(s_bodyStyle)
		{
			alignment = TextAnchor.MiddleCenter,
			fontSize = Mathf.Clamp(bucket * 4 - 2, 16, 40)
		};
		s_buttonStyle = new GUIStyle(GUI.skin.button)
		{
			alignment = TextAnchor.MiddleCenter,
			fontSize = Mathf.Clamp(bucket * 4 - 2, 16, 40),
			fontStyle = FontStyle.Bold
		};
		return true;
	}

	private static bool TryLoadPanelTexture(out Texture2D texture)
	{
		texture = null;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(PanelTextureRelativePath);
		if (path == null)
		{
			LogMissingPanelTexture("missing deployed panel texture '" + PanelTextureRelativePath + "'.");
			return false;
		}

		try
		{
			var bytes = File.ReadAllBytes(path);
			var loaded = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			loaded.hideFlags = HideFlags.HideAndDontSave;
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			if (!ImageConversion.LoadImage(loaded, il2cppBytes))
			{
				UnityEngine.Object.Destroy(loaded);
				LogMissingPanelTexture("failed to decode panel texture '" + path + "'.");
				return false;
			}

			loaded.name = "homm3_necromancy_dialog_panel";
			loaded.filterMode = FilterMode.Point;
			loaded.wrapMode = TextureWrapMode.Clamp;
			texture = loaded;
			return true;
		}
		catch (Exception ex)
		{
			LogMissingPanelTexture("failed to load panel texture '" + path + "': " + ex.Message);
			return false;
		}
	}

	private static void LogMissingPanelTexture(string message)
	{
		if (s_loggedMissingPanelTexture)
			return;
		s_loggedMissingPanelTexture = true;
		Plugin.LogSource?.LogError("HoMM3 skeletal necromancy notification asset contract failed: " + message);
	}

	private static RectOffset CreateRectOffset(int left, int right, int top, int bottom)
	{
		var offset = new RectOffset();
		offset.left = left;
		offset.right = right;
		offset.top = top;
		offset.bottom = bottom;
		return offset;
	}
}
