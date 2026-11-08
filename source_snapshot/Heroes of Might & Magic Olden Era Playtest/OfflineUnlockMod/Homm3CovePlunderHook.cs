using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Data;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting "Plunder" (added on top of Treasure Hunting; nothing native is removed).
/// A hero with skill_faction_homm3_cove at level L (1..3):
/// - chests: when the hero opens a chest (the native chest logic starts the gold/XP choice), the hero's side also
///   gains L of one rare resource (crystals/mercury/gemstones) picked by a deterministic hash of the chest object id
///   and the hero; once per chest object in this loaded game;
/// - mines: when the mine changes owner to that hero's side, the side gains one native resource-pile midpoint
///   of the mine's resource scaled 100/150/200%, at most once per hero per mine in this loaded game
///   (in-memory, keyed by native pointers: not persisted across save/load).
/// Chests bind the chest map-object logic open virtual (GameSymbols.CovePlunder.ChestHeroOpen). The reward-set
/// method the Tower Mana Well Aegis hook binds (TowerBottomlessKnowledge.ManaRewardSetAppliers) is a UI event
/// subscriber, not the applier; it is kept here only as a logged diagnostic and never pays.
/// Mines bind the current-build mine logic (GameSymbols.CovePlunder). Fail closed with a log on every miss.
/// Every step logs a greppable "HoMM3 Cove Plunder: ..." line (see the step tags in the messages).
/// </summary>
internal static class Homm3CovePlunderHook
{
	private const string PlunderSkillSid = "skill_faction_homm3_cove";
	private const string ChestRewardSetLabel = "chest_label";
	private const string LogPrefix = "HoMM3 Cove Plunder: ";
	private const int StepLogCap = 400;
	private const int RewardEventLogCap = 32;

	private static readonly string[] ChestRareResources = { "crystals", "mercury", "gemstones" };

	// Native map pile midpoints (Core resources.json pile ranges: gold 400-800, wood/ore 4-6, rare 2-4).
	private static readonly Dictionary<string, int> MinePileMidpoints = new(StringComparer.Ordinal)
	{
		{ "gold", 600 },
		{ "wood", 5 },
		{ GameSymbols.CovePlunder.OreResourceName, 5 },
		{ "crystals", 3 },
		{ "mercury", 3 },
		{ "gemstones", 3 },
	};

	private static readonly int[] MinePilePercentByLevel = { 0, 100, 150, 200 };

	private sealed class Visitor
	{
		internal IntPtr HeroPtr;
		internal string HeroSid;
		internal int SideId;
		internal int Level;
	}

	private static bool _registered;
	private static ManualLogSource _log;
	private static ConstructorInfo _resourceWrapperCtor;
	private static MethodInfo _addResourceMethod;
	private static IntPtr _mineLogicClass;
	private static IntPtr _chestLogicClass;
	private static IntPtr _logicHeroClass;
	private static IntPtr _rewardSetClass;

	private static readonly HashSet<int> _plunderedChests = new();
	private static readonly HashSet<(IntPtr hero, IntPtr mine)> _plunderedMines = new();
	private static readonly Dictionary<IntPtr, Visitor> _lastMineVisitor = new();
	private static readonly Dictionary<IntPtr, int> _visitOwnerBefore = new();
	private static int _loggedRewardEvents;
	private static int _loggedSteps;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new ArgumentNullException(nameof(harmony));
		_log = log;

		// Resolve every surface before patching anything, so a miss leaves no partial feature behind.
		var chestLogicType = GameMember.FindType(GameSymbols.CovePlunder.ChestLogicTypeId, GameSymbols.CovePlunder.ChestLogicTypeHint);
		if (chestLogicType == null)
			throw new TypeLoadException("Cove Plunder: missing chest logic type (CovePlunder.ChestLogicTypeHint).");
		if (!HasReadableMember(chestLogicType, GameSymbols.CovePlunder.ChestLogicChestMembers, typeof(ObjChest)))
			throw new MissingMemberException(chestLogicType.FullName, "chest data member (CovePlunder.ChestLogicChestMembers)");
		var chestOpenMethods = GameMember.FindMethodsByNames(chestLogicType, 1, GameSymbols.CovePlunder.ChestHeroOpen.Id, GameSymbols.CovePlunder.ChestHeroOpen.NameHints);
		if (chestOpenMethods.Length != 1 || chestOpenMethods[0].ReturnType != typeof(void) || chestOpenMethods[0].IsStatic
			|| !typeof(Il2CppObjectBase).IsAssignableFrom(chestOpenMethods[0].GetParameters()[0].ParameterType))
			throw new MissingMethodException(chestLogicType.FullName, "chest open virtual (CovePlunder.ChestHeroOpen): matched " + chestOpenMethods.Length);

		var resourceWrapperType = GameMember.FindType(
			GameSymbols.SwashbucklerGold.ResourceWrapperTypeId,
			GameSymbols.SwashbucklerGold.ResourceWrapperTypeHint);
		if (resourceWrapperType == null)
			throw new TypeLoadException("Cove Plunder: missing resource wrapper type (SwashbucklerGold.ResourceWrapperTypeHint).");
		_resourceWrapperCtor = resourceWrapperType.GetConstructor(BindingFlags.Public | BindingFlags.Instance, null, new[] { typeof(ResHeap) }, null);
		if (_resourceWrapperCtor == null)
			throw new MissingMethodException(resourceWrapperType.FullName, ".ctor(ResHeap)");
		_addResourceMethod = GameMember.FindFirstMethodByNames(
			resourceWrapperType,
			new[] { typeof(string), typeof(int) },
			GameSymbols.SwashbucklerGold.AddResource);
		if (_addResourceMethod == null || _addResourceMethod.ReturnType != typeof(void))
			throw new MissingMethodException(resourceWrapperType.FullName, "exact resource add (SwashbucklerGold.AddResource)");

		var mineLogicType = GameMember.FindType(GameSymbols.CovePlunder.MineLogicTypeId, GameSymbols.CovePlunder.MineLogicTypeHint);
		if (mineLogicType == null)
			throw new TypeLoadException("Cove Plunder: missing mine logic type (CovePlunder.MineLogicTypeHint).");
		if (!HasReadableMember(mineLogicType, GameSymbols.CovePlunder.MineLogicResMineMembers, typeof(ObjResMine)))
			throw new MissingMemberException(mineLogicType.FullName, "mine data member (CovePlunder.MineLogicResMineMembers)");
		if (!HasReadableMember(mineLogicType, GameSymbols.CovePlunder.MineLogicConfigMembers, typeof(ObjResMineConfig)))
			throw new MissingMemberException(mineLogicType.FullName, "mine config member (CovePlunder.MineLogicConfigMembers)");
		var visitMethods = GameMember.FindMethodsByNames(mineLogicType, 1, GameSymbols.CovePlunder.MineHeroVisitMethods.Id, GameSymbols.CovePlunder.MineHeroVisitMethods.NameHints);
		if (visitMethods.Length != GameSymbols.CovePlunder.MineHeroVisitMethods.NameHints.Length)
			throw new MissingMethodException(mineLogicType.FullName, "mine hero visit methods: matched " + visitMethods.Length + "/" + GameSymbols.CovePlunder.MineHeroVisitMethods.NameHints.Length);
		foreach (var m in visitMethods)
		{
			if (m.ReturnType != typeof(void) || m.IsStatic || !typeof(Il2CppObjectBase).IsAssignableFrom(m.GetParameters()[0].ParameterType))
				throw new MissingMethodException(mineLogicType.FullName, "mine hero visit method shape " + m.Name);
		}
		var ownerChangedMethods = GameMember.FindMethodsByNames(mineLogicType, 2, GameSymbols.CovePlunder.MineOwnerChanged.Id, GameSymbols.CovePlunder.MineOwnerChanged.NameHints);
		if (ownerChangedMethods.Length != 1 || ownerChangedMethods[0].ReturnType != typeof(void) || ownerChangedMethods[0].IsStatic)
			throw new MissingMethodException(mineLogicType.FullName, "mine owner-change override: matched " + ownerChangedMethods.Length);

		_chestLogicClass = NativeClassOf(chestLogicType);
		_mineLogicClass = NativeClassOf(mineLogicType);
		_logicHeroClass = NativeClassOf(typeof(LogicHero));
		_rewardSetClass = NativeClassOf(typeof(DataRewardSet));
		if (_chestLogicClass == IntPtr.Zero || _mineLogicClass == IntPtr.Zero || _logicHeroClass == IntPtr.Zero || _rewardSetClass == IntPtr.Zero)
			throw new TypeLoadException("Cove Plunder: native class pointer unresolved for the fold guards.");

		// Diagnostic only (never pays): the reward-set event method the Tower Mana Well Aegis hook also binds.
		// Logs whether it fires at all and with which label, which is the open runtime question for Aegis too.
		MethodInfo[] rewardEventMethods = Array.Empty<MethodInfo>();
		var rewardApplierType = GameMember.FindType(
			GameSymbols.TowerBottomlessKnowledge.RewardApplierTypeId,
			GameSymbols.TowerBottomlessKnowledge.RewardApplierTypeHint);
		if (rewardApplierType != null)
		{
			rewardEventMethods = GameMember.FindMethodsByNames(
				rewardApplierType,
				new[] { typeof(LogicHero), typeof(DataRewardSet) },
				GameSymbols.TowerBottomlessKnowledge.ManaRewardSetAppliers);
		}

		harmony.Patch(chestOpenMethods[0], postfix: new HarmonyMethod(typeof(Homm3CovePlunderHook), nameof(PostfixChestOpen)));
		var visitPrefix = new HarmonyMethod(typeof(Homm3CovePlunderHook), nameof(PrefixMineHeroVisit));
		var visitPostfix = new HarmonyMethod(typeof(Homm3CovePlunderHook), nameof(PostfixMineHeroVisit));
		foreach (var method in visitMethods)
			harmony.Patch(method, prefix: visitPrefix, postfix: visitPostfix);
		harmony.Patch(ownerChangedMethods[0], postfix: new HarmonyMethod(typeof(Homm3CovePlunderHook), nameof(PostfixMineOwnerChanged)));
		var rewardEventPostfix = new HarmonyMethod(typeof(Homm3CovePlunderHook), nameof(PostfixRewardSetEvent));
		foreach (var method in rewardEventMethods)
			harmony.Patch(method, postfix: rewardEventPostfix);

		_registered = true;
		log?.LogInfo(LogPrefix + "registered chest-open postfix on " + chestLogicType.Name + "." + chestOpenMethods[0].Name
			+ ", mine visit prefix/postfix on " + visitMethods.Length + " method(s) (" + JoinNames(visitMethods) + "), owner-change postfix on "
			+ ownerChangedMethods[0].Name + ", reward-set event diagnostic on " + rewardEventMethods.Length + " method(s) ("
			+ JoinNames(rewardEventMethods) + "; never pays). Chest payout once per chest, mine payout once per hero per mine per loaded game (not saved). Runtime unproven.");
	}

	// ---------------------------------------------------------------- chests

	private static void PostfixChestOpen(object __instance, object __0)
	{
		try
		{
			if (!IsNativeInstanceOf(__instance, _chestLogicClass))
			{
				Step("chest-open skip: instance is not the chest logic (folded body?)");
				return;
			}
			var chest = ReadMember(__instance, GameSymbols.CovePlunder.ChestLogicChestMembers) as ObjChest;
			if (chest == null)
			{
				Step("chest-open skip: chest data unreadable");
				return;
			}
			var objectId = chest.idMapObject;
			var rewardSet = chest.rewardSet;
			var label = rewardSet?.label;
			if (!TryResolveWorldHero(__0, out var dataHero, out var heroFail))
			{
				Step("chest-open skip: object=" + objectId + " " + heroFail);
				return;
			}
			var level = ReadPlunderLevel(dataHero, out var rankInfo);
			Step("chest-open fired: object=" + objectId + " label=" + (label ?? "<null>") + " hero=" + dataHero.configSid
				+ " side=" + dataHero.sideId + " rank=" + level + " (" + rankInfo + ")");
			if (level <= 0)
			{
				Step("chest-open skip: object=" + objectId + " hero=" + dataHero.configSid + " has no Treasure Hunting rank");
				return;
			}
			if (rewardSet == null)
			{
				Step("chest-open skip: object=" + objectId + " has no reward set (native refuses to open it)");
				return;
			}
			if (!string.Equals(label, ChestRewardSetLabel, StringComparison.Ordinal))
				Step("chest-open note: object=" + objectId + " reward-set label '" + (label ?? "<null>") + "' is not '" + ChestRewardSetLabel + "' (paying anyway: the chest logic is the gate)");
			if (objectId <= 0)
			{
				Step("chest-open skip: chest has no object id (" + objectId + "); refusing an unseeded roll");
				return;
			}
			if (_plunderedChests.Contains(objectId))
			{
				Step("chest-open skip: object " + objectId + " already plundered");
				return;
			}

			var resource = ChestRareResources[DeterministicIndex("plunder|chest|" + objectId + "|" + dataHero.configSid, ChestRareResources.Length)];
			if (Grant(dataHero.sideId, resource, level, out var before, out var after, out var fail))
			{
				_plunderedChests.Add(objectId);
				_log?.LogInfo(LogPrefix + "chest payout object=" + objectId + " hero=" + dataHero.configSid + " level=" + level
					+ " side=" + dataHero.sideId + " +" + level + " " + resource + " (" + before + "->" + after + ").");
			}
			else
			{
				_log?.LogWarning(LogPrefix + "chest payout FAILED object=" + objectId + " +" + level + " " + resource + ": " + fail);
			}
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "chest-open postfix failed: " + ex);
		}
	}

	private static void PostfixRewardSetEvent(LogicHero __0, DataRewardSet __1)
	{
		try
		{
			if (_loggedRewardEvents >= RewardEventLogCap)
				return;
			_loggedRewardEvents++;
			if (__0 == null || __1 == null || !IsNativeInstanceOf(__1, _rewardSetClass) || !IsNativeInstanceOf(__0, _logicHeroClass))
			{
				_log?.LogInfo(LogPrefix + "reward-set event diagnostic: null or folded arguments; ignored.");
				return;
			}
			_log?.LogInfo(LogPrefix + "reward-set event diagnostic: fired label=" + (__1.label ?? "<null>") + " object=" + __1.objectId
				+ " (diagnostic only; chests pay from the chest-open hook).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "reward-set event diagnostic failed: " + ex.Message);
		}
	}

	// ---------------------------------------------------------------- mines

	private static void PrefixMineHeroVisit(object __instance, object __0, MethodBase __originalMethod)
	{
		try
		{
			if (!IsNativeInstanceOf(__instance, _mineLogicClass))
				return;
			var mine = ReadMember(__instance, GameSymbols.CovePlunder.MineLogicResMineMembers) as ObjResMine;
			if (mine == null)
			{
				Step("mine-visit skip: mine data unreadable (" + __originalMethod?.Name + ")");
				return;
			}
			var minePtr = mine.Pointer;
			_visitOwnerBefore[minePtr] = mine.ownerSide;

			if (!TryResolveWorldHero(__0, out var dataHero, out var heroFail))
			{
				Step("mine-visit skip: mine=" + mine.idMapObject + " " + heroFail + " (" + __originalMethod?.Name + ")");
				_lastMineVisitor.Remove(minePtr);
				return;
			}
			var level = ReadPlunderLevel(dataHero, out var rankInfo);
			Step("mine-visit fired: mine=" + mine.idMapObject + " owner=" + mine.ownerSide + " hero=" + dataHero.configSid
				+ " side=" + dataHero.sideId + " rank=" + level + " (" + rankInfo + ") method=" + __originalMethod?.Name);
			// Every visitor overwrites the record (also non-Plunder heroes), so a later capture is never misattributed.
			// The record survives the guard battle: the post-battle capture finds the hero who started it.
			_lastMineVisitor[minePtr] = new Visitor
			{
				HeroPtr = dataHero.Pointer,
				HeroSid = dataHero.configSid,
				SideId = dataHero.sideId,
				Level = level,
			};
		}
		catch (Exception ex)
		{
			Step("mine-visit prefix failed: " + ex.Message);
		}
	}

	private static void PostfixMineHeroVisit(object __instance)
	{
		try
		{
			if (!IsNativeInstanceOf(__instance, _mineLogicClass))
				return;
			var mine = ReadMember(__instance, GameSymbols.CovePlunder.MineLogicResMineMembers) as ObjResMine;
			if (mine == null)
				return;
			var minePtr = mine.Pointer;
			if (!_visitOwnerBefore.TryGetValue(minePtr, out var before))
				return;
			_visitOwnerBefore.Remove(minePtr);
			if (before == mine.ownerSide)
				return;
			// Ownership moved inside the hero visit (unguarded capture). Pays here when the owner-change hook did not
			// already pay (dedup by hero+mine), so either surface firing is enough; the trigger is logged.
			TryPayMine(__instance, mine, "visit", before);
		}
		catch (Exception ex)
		{
			Step("mine-visit postfix failed: " + ex.Message);
		}
	}

	private static void PostfixMineOwnerChanged(object __instance)
	{
		try
		{
			if (!IsNativeInstanceOf(__instance, _mineLogicClass))
				return;
			var mine = ReadMember(__instance, GameSymbols.CovePlunder.MineLogicResMineMembers) as ObjResMine;
			if (mine == null)
			{
				Step("mine-owner-change skip: mine data unreadable");
				return;
			}
			TryPayMine(__instance, mine, "owner-change", null);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "mine owner-change postfix failed: " + ex);
		}
	}

	private static void TryPayMine(object mineLogic, ObjResMine mine, string trigger, int? ownerBefore)
	{
		var minePtr = mine.Pointer;
		var owner = mine.ownerSide;
		Step("mine-capture fired: trigger=" + trigger + " mine=" + mine.idMapObject + " owner=" + (ownerBefore.HasValue ? ownerBefore + "->" : "") + owner);
		if (!_lastMineVisitor.TryGetValue(minePtr, out var visitor))
		{
			Step("mine-capture skip: mine=" + mine.idMapObject + " owner=" + owner + " no recorded visiting hero");
			return;
		}
		if (visitor.SideId != owner)
		{
			Step("mine-capture skip: mine=" + mine.idMapObject + " owner=" + owner + " is not visitor " + visitor.HeroSid + " side=" + visitor.SideId);
			return;
		}
		if (visitor.Level <= 0)
		{
			Step("mine-capture skip: mine=" + mine.idMapObject + " visitor " + visitor.HeroSid + " has no Treasure Hunting rank");
			return;
		}
		var key = (visitor.HeroPtr, minePtr);
		if (_plunderedMines.Contains(key))
		{
			Step("mine-capture skip: mine=" + mine.idMapObject + " already plundered by hero " + visitor.HeroSid);
			return;
		}
		var config = ReadMember(mineLogic, GameSymbols.CovePlunder.MineLogicConfigMembers) as ObjResMineConfig;
		var resource = config?.resName;
		if (string.IsNullOrEmpty(resource) || !MinePileMidpoints.TryGetValue(resource, out var midpoint))
		{
			_log?.LogWarning(LogPrefix + "mine payout FAILED mine=" + mine.idMapObject + " resource '" + (resource ?? "<null>") + "' has no pile midpoint.");
			return;
		}
		var level = Math.Min(visitor.Level, 3);
		var amount = (midpoint * MinePilePercentByLevel[level] + 50) / 100;
		if (Grant(owner, resource, amount, out var before, out var after, out var fail))
		{
			_plunderedMines.Add(key);
			_log?.LogInfo(LogPrefix + "mine payout trigger=" + trigger + " mine=" + mine.idMapObject + " hero=" + visitor.HeroSid + " level=" + level
				+ " side=" + owner + " +" + amount + " " + resource + " (" + before + "->" + after + ").");
		}
		else
		{
			_log?.LogWarning(LogPrefix + "mine payout FAILED mine=" + mine.idMapObject + " +" + amount + " " + resource + ": " + fail);
		}
	}

	// ---------------------------------------------------------------- shared

	private static bool TryResolveWorldHero(object worldHero, out Hero dataHero, out string failReason)
	{
		dataHero = null;
		if (worldHero == null)
		{
			failReason = "world hero argument null";
			return false;
		}
		var logicHero = ReadMember(worldHero, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty) as LogicHero;
		if (logicHero == null)
		{
			failReason = "world hero has no readable logic hero (CastleEliteStrategem.WorldHeroLogicHeroProperty) on " + worldHero.GetType().Name;
			return false;
		}
		dataHero = ReadMember(logicHero, GameSymbols.TowerBottomlessKnowledge.LogicHeroDataHeroMembers) as Hero;
		if (dataHero == null)
		{
			failReason = "logic hero has no readable data hero (TowerBottomlessKnowledge.LogicHeroDataHeroMembers)";
			return false;
		}
		failReason = null;
		return true;
	}

	/// <summary>
	/// Plunder rank 1..3 (HeroSkill.level is 1-based: Basic/Advanced/Expert, as the Bulwark runtime reads it).
	/// HeroSkills.list is an Il2CppSystem List, which is NOT a System.Collections.IEnumerable: it is walked by
	/// Count + indexer (the previous `is IEnumerable` test always failed, so every hero read as rank 0).
	/// </summary>
	private static int ReadPlunderLevel(Hero dataHero, out string info)
	{
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		if (skills == null)
		{
			info = "skills unreadable";
			return 0;
		}
		var list = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		if (list == null)
		{
			info = "skill list unreadable";
			return 0;
		}
		if (!TryListItems(list, out var items))
		{
			info = "skill list " + list.GetType().Name + " not walkable";
			return 0;
		}
		foreach (var skill in items)
		{
			if (skill == null)
				continue;
			var sid = ReadMember(skill, GameSymbols.DraconicDominion.HeroSkillSidMembers) as string;
			if (!string.Equals(sid?.Trim(), PlunderSkillSid, StringComparison.Ordinal))
				continue;
			if (ReadMember(skill, GameSymbols.DraconicDominion.HeroSkillLevelMembers) is not int level)
			{
				info = "skills=" + items.Count + " cove skill level unreadable";
				return 0;
			}
			info = "skills=" + items.Count + " cove skill raw level=" + level;
			return Math.Max(0, Math.Min(3, level));
		}
		info = "skills=" + items.Count + " no " + PlunderSkillSid;
		return 0;
	}

	private static bool TryListItems(object list, out List<object> items)
	{
		items = new List<object>();
		if (list is IEnumerable enumerable && list is not string)
		{
			foreach (var item in enumerable)
				items.Add(item);
			return true;
		}
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public;
		var type = list.GetType();
		var countProp = type.GetProperty("Count", flags);
		var indexer = type.GetProperty("Item", flags, null, null, new[] { typeof(int) }, null);
		if (countProp == null || indexer == null || countProp.GetValue(list) is not int count)
			return false;
		for (var i = 0; i < count; i++)
			items.Add(indexer.GetValue(list, new object[] { i }));
		return true;
	}

	/// <summary>Adds a resource to a side through the native resource wrapper; also used by GoldenEraGameplayOptions (monster gold).</summary>
	internal static bool Grant(int sideId, string resource, int amount, out int before, out int after, out string failReason)
	{
		before = after = -1;
		if (_resourceWrapperCtor == null || _addResourceMethod == null)
		{
			failReason = "Plunder resource path not registered";
			return false;
		}
		if (amount <= 0)
		{
			failReason = "non-positive amount " + amount;
			return false;
		}
		if (!Homm3BattleUnitLawOwnerRegistry.TryResolveGlobalDataSide(sideId, out var dataSide, out failReason))
		{
			failReason = "side " + sideId + " unresolved: " + failReason;
			return false;
		}
		var heap = ReadMember(dataSide, GameSymbols.SwashbucklerGold.SideResourceMembers) as ResHeap;
		if (heap == null)
		{
			failReason = "side " + sideId + " resource heap unreadable (SwashbucklerGold.SideResourceMembers)";
			return false;
		}
		var entry = FindResourceEntry(heap, resource);
		if (entry == null)
		{
			failReason = "side " + sideId + " has no '" + resource + "' resource entry";
			return false;
		}
		before = entry.value;
		var wrapper = _resourceWrapperCtor.Invoke(new object[] { heap });
		_addResourceMethod.Invoke(wrapper, new object[] { resource, amount });
		after = entry.value;
		if (after - before != amount)
		{
			failReason = "readback " + before + "->" + after + " is not +" + amount + " " + resource;
			return false;
		}
		return true;
	}

	private static Resource FindResourceEntry(ResHeap heap, string resource)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public;
		foreach (var prop in heap.GetType().GetProperties(flags))
		{
			if (prop.PropertyType != typeof(Resource) || prop.GetIndexParameters().Length != 0)
				continue;
			Resource entry;
			try { entry = prop.GetValue(heap) as Resource; }
			catch { continue; }
			if (entry != null && string.Equals(entry.name, resource, StringComparison.Ordinal))
				return entry;
		}
		return null;
	}

	private static int DeterministicIndex(string seed, int count)
	{
		unchecked
		{
			var hash = 2166136261u;
			foreach (var c in seed)
			{
				hash ^= c;
				hash *= 16777619u;
			}
			return (int)(hash % (uint)count);
		}
	}

	private static IntPtr NativeClassOf(Type managedType)
	{
		try
		{
			var store = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(store.TypeHandle);
			var field = store.GetField("NativeClassPtr", BindingFlags.Public | BindingFlags.Static);
			return field?.GetValue(null) is IntPtr ptr ? ptr : IntPtr.Zero;
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	private static bool IsNativeInstanceOf(object value, IntPtr expectedClass)
	{
		if (value is not Il2CppObjectBase obj || expectedClass == IntPtr.Zero)
			return false;
		var ptr = obj.Pointer;
		if (ptr == IntPtr.Zero)
			return false;
		var actual = IL2CPP.il2cpp_object_get_class(ptr);
		return actual != IntPtr.Zero && IL2CPP.il2cpp_class_is_assignable_from(expectedClass, actual);
	}

	private static bool HasReadableMember(Type type, string[] names, Type expected)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var prop = type.GetProperty(name, flags);
			if (prop?.GetMethod != null && prop.PropertyType == expected)
				return true;
			var field = type.GetField(name, flags);
			if (field != null && field.FieldType == expected)
				return true;
		}
		return false;
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop?.GetMethod != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj);
			}
			catch { }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	private static string JoinNames(MethodInfo[] methods)
	{
		var names = new string[methods.Length];
		for (var i = 0; i < methods.Length; i++)
			names[i] = methods[i].Name;
		return string.Join(",", names);
	}

	/// <summary>Per-step trace line; capped so a long session cannot flood the log.</summary>
	private static void Step(string message)
	{
		if (_loggedSteps >= StepLogCap)
			return;
		_loggedSteps++;
		_log?.LogInfo(LogPrefix + message + (_loggedSteps == StepLogCap ? ". (step log cap reached; later steps are silent)" : "."));
	}
}
