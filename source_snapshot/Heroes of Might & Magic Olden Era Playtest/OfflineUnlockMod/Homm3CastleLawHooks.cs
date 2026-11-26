using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BattleHex = Hex.Session.Battle.Hex;

namespace OfflineUnlockMod;

/// <summary>
/// Castle faction laws that change Elite Strategem (law pass 2026-11-21, docs/faction_law_pass_20261121/castle.md;
/// law pass 2026-11-25, docs/faction_law_pass_20261125/build_castle.md).
/// <see cref="Homm3CastleEliteStrategemRuntime"/> reads Grand Strategem (#31) itself and, when a mode took effect,
/// notes the battle here (<see cref="NoteStrategemApplied"/>) before BattleLogic.Init runs.
/// At round 1 this adds the law buffs: Drilled Deployment (#20) to the Strategem owner's stacks, Ambush Doctrine (#8)
/// to the enemy stacks of an Ambush battle. At the battle result it pays Spoils of Command (#5): Gold when the owner
/// won a Strategem battle against neutral armies (<see cref="ObserveBeforeBattleResult"/>).
/// Fail closed: no law, a read failure or a missing surface leaves the battle as it was.
/// </summary>
internal static class Homm3CastleLawHooks
{
	internal const string FactionSid = "homm3_castle";
	/// <summary>Ambush Doctrine: enemy creatures lose 2/4 Initiative and Defence in round 1 of an Ambush.</summary>
	internal const int AmbushDoctrine = 8;
	/// <summary>Spoils of Command: after a won Strategem battle against neutral armies, gain 150/300 Gold.</summary>
	internal const int SpoilsOfCommand = 5;
	/// <summary>Drilled Deployment: +10%/+20% Damage in round 1 of a Strategem battle.</summary>
	internal const int DrilledDeployment = 20;
	/// <summary>Grand Strategem (one level): Spread Out, Compress and Ambush also work against hero armies on the map.</summary>
	internal const int GrandStrategem = 31;
	/// <summary>law pass 2026-11-25: Spoils of Command (#5) Gold by law level. Must match the law's display carrier.</summary>
	internal static readonly int[] SpoilsGoldByLevel = { 0, 150, 300 };
	internal const string DrilledBuffPrefix = "h3_law_castle_drilled_effect_";
	internal const string AmbushedBuffPrefix = "h3_law_castle_ambushed_effect_";

	private sealed class Pending
	{
		internal IntPtr TransferBattlePointer;
		internal TransferSide OwnerSide;
		internal bool Ambush;
		internal int Drilled;
		internal int Doctrine;
		internal object Logic;
		internal IntPtr HubPointer;
		internal object OwnerWrapper;
		internal bool Done;
		/// <summary>law pass 2026-11-25: Spoils of Command (#5) level, 0 when not taken or the opponent was not neutral.</summary>
		internal int Spoils;
		/// <summary>Owner's index in the Init TransferBattle sides (-1 unknown).</summary>
		internal int OwnerIndex = -1;
	}

	private static readonly object Gate = new();
	private static readonly List<Pending> Battles = new();
	private static bool _attempted;
	private static ManualLogSource _log;
	private static int _logged;

	private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
	private static string LogicBattleClone => At(GameSymbols.InfernoGating.LogicBattleCloneMembers, 0);
	private static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
	private static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
	private static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
	private static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
	private static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
	private static string SideWrapperTransferSide => At(GameSymbols.InfernoGating.SideWrapperTransferSideMembers, 0);
	private static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
	private static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);

	/// <summary>Law level (0 = not taken) for a Castle side; tries each owner object in turn.</summary>
	internal static int Rank(int lawIndex, params object[] owners)
	{
		if (owners == null)
			return 0;
		foreach (var owner in owners)
		{
			if (owner == null)
				continue;
			try
			{
				var rank = Homm3CustomFactionLawRuntime.CustomLawRank(owner, lawIndex, FactionSid);
				if (rank > 0)
					return rank;
			}
			catch
			{
				// fail closed: try the next owner
			}
		}
		return 0;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			Type logicType = null;
			foreach (var hint in GameSymbols.InfernoGating.BattleLogicTypeHints ?? Array.Empty<string>())
			{
				if (!string.IsNullOrWhiteSpace(hint) && hexAssembly.GetType(hint) is { } type)
				{
					logicType = type;
					break;
				}
			}
			if (logicType == null)
				throw new TypeLoadException("BattleLogic type not found");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			var hubsProperty = FindProperty(logicType, LogicHubs) ?? throw new MissingMemberException(logicType.FullName + "." + LogicHubs);
			var hubType = (FindProperty(hubsProperty.PropertyType, HubsRoundHub) ?? throw new MissingMemberException(hubsProperty.PropertyType.FullName + "." + HubsRoundHub)).PropertyType;
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
			Patch(harmony, init, nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, nameof(PostfixRoundStarted));
			_log?.LogInfo("HoMM3 Castle law hooks registered: Drilled Deployment / Ambush Doctrine round-1 buffs.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Castle law hooks NOT registered (Drilled Deployment and Ambush Doctrine do nothing): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Called by the Strategem runtime after a mode took effect on <paramref name="transferBattle"/> (before Init).
	/// Reads the round-1 law levels for the owner and remembers the battle when either is taken.
	/// </summary>
	internal static void NoteStrategemApplied(TransferBattle transferBattle, TransferSide ownerSide, bool ambush, bool opponentNeutral)
	{
		try
		{
			if (transferBattle == null || ownerSide == null)
				return;
			// law pass 2026-11-21: Drilled Deployment (#20), Ambush Doctrine (#8)
			var drilled = Rank(DrilledDeployment, ownerSide, ownerSide.logicHero);
			var doctrine = ambush ? Rank(AmbushDoctrine, ownerSide, ownerSide.logicHero) : 0;
			// law pass 2026-11-25: Spoils of Command (#5): only a battle against neutral armies pays.
			var spoils = opponentNeutral ? Rank(SpoilsOfCommand, ownerSide, ownerSide.logicHero) : 0;
			if (drilled <= 0 && doctrine <= 0 && spoils <= 0)
				return;
			lock (Gate)
			{
				Battles.RemoveAll(b => b.TransferBattlePointer == transferBattle.Pointer);
				Battles.Add(new Pending
				{
					TransferBattlePointer = transferBattle.Pointer,
					OwnerSide = ownerSide,
					Ambush = ambush,
					Drilled = Math.Min(drilled, 2),
					Doctrine = Math.Min(doctrine, 2),
					Spoils = Math.Min(spoils, SpoilsGoldByLevel.Length - 1),
				});
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			LogLimited("Strategem law note failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1)
	{
		try
		{
			if (__1 == null)
				return;
			Pending pending = null;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (battle.Logic == null && battle.TransferBattlePointer == __1.Pointer)
					{
						pending = battle;
						break;
					}
				}
			}
			if (pending == null)
				return;
			var hub = ReadProperty(ReadProperty(__instance, LogicHubs), HubsRoundHub) as Il2CppObjectBase;
			var clone = ReadProperty(__instance, LogicBattleClone) as TransferBattle;
			object wrapper = null;
			// The clone's sides are copies; match the owner by side order (Ambush already reordered the original).
			var ownerIndex = -1;
			if (__1.sides != null)
			{
				for (var i = 0; i < __1.sides.Length; i++)
				{
					if (__1.sides[i] != null && __1.sides[i].Pointer == pending.OwnerSide.Pointer)
						ownerIndex = i;
				}
			}
			if (clone?.sides != null && ownerIndex >= 0 && ownerIndex < clone.sides.Length && clone.sides[ownerIndex] != null)
				wrapper = FindSideWrapper(__instance, clone.sides[ownerIndex]);
			wrapper ??= FindSideWrapper(__instance, pending.OwnerSide);
			lock (Gate)
			{
				pending.OwnerIndex = ownerIndex;
				if (hub == null || wrapper == null)
				{
					LogLimited("round hub or owner side wrapper missing after Init; Strategem round-1 law buffs skipped.");
					if (pending.Spoils <= 0)
					{
						Battles.Remove(pending);
						return;
					}
					// law pass 2026-11-25: Spoils of Command (#5) only needs the battle result; keep the entry without buffs.
					pending.Drilled = 0;
					pending.Doctrine = 0;
					pending.Done = true;
					pending.Logic = __instance;
					return;
				}
				pending.Logic = __instance;
				pending.HubPointer = hub.Pointer;
				pending.OwnerWrapper = wrapper;
			}
		}
		catch (Exception ex)
		{
			LogLimited("Init postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			if (__instance is not Il2CppObjectBase hub || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args || args.roundNumber < 1)
				return;
			Pending pending = null;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (!battle.Done && battle.Logic != null && battle.HubPointer == hub.Pointer)
					{
						pending = battle;
						battle.Done = true;
						break;
					}
				}
				// law pass 2026-11-25: Spoils of Command (#5) keeps the entry until the battle result.
				if (pending != null && pending.Spoils <= 0)
					Battles.Remove(pending);
			}
			if (pending == null || pending.OwnerWrapper is not Il2CppObjectBase own)
				return;
			var hexes = ReadProperty(ReadProperty(pending.Logic, LogicGrid), GridHexes) as Il2CppReferenceArray<BattleHex>;
			if (hexes == null)
			{
				LogLimited("battle grid missing at round 1; Strategem law buffs skipped.");
				return;
			}
			int drilled = 0, ambushed = 0;
			foreach (var hex in hexes)
			{
				if (hex?.fieldObjects == null)
					continue;
				for (var i = 0; i < hex.fieldObjects.Count; i++)
				{
					var unit = hex.fieldObjects[i]?.TryCast<Unit>();
					if (unit == null || ReadProperty(unit, FieldObjectSide) is not Il2CppObjectBase wrapper)
						continue;
					var isOwner = wrapper.Pointer == own.Pointer;
					// law pass 2026-11-21: Drilled Deployment (#20): own stacks +10%/+20% Damage this round.
					if (isOwner && pending.Drilled > 0 && TryBuff(unit, DrilledBuffPrefix + pending.Drilled))
						drilled++;
					// law pass 2026-11-21: Ambush Doctrine (#8): enemy stacks -2/-4 Initiative and Defence this round.
					if (!isOwner && pending.Ambush && pending.Doctrine > 0 && TryBuff(unit, AmbushedBuffPrefix + pending.Doctrine))
						ambushed++;
				}
			}
			_log?.LogInfo("HoMM3 Castle Strategem laws at round " + args.roundNumber + ": Drilled Deployment L" + pending.Drilled + " on " + drilled
			              + " stack(s), Ambush Doctrine L" + pending.Doctrine + " on " + ambushed + " stack(s).");
		}
		catch (Exception ex)
		{
			LogLimited("RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// law pass 2026-11-25: Spoils of Command (#5). The battle is over: when the Strategem owner of this battle won and
	/// every opponent was a neutral army, add 150/300 Gold to the owner's kingdom. Once per battle; fail closed.
	/// Dispatched from the shared battle-result prefix, Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup.
	/// </summary>
	internal static void ObserveBeforeBattleResult(object battleLogic)
	{
		if (battleLogic == null)
			return;
		try
		{
			var logicPointer = (battleLogic as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
			Pending pending = null;
			lock (Gate)
			{
				if (Battles.Count == 0)
					return;
				foreach (var battle in Battles)
				{
					if (battle.Logic != null && (ReferenceEquals(battle.Logic, battleLogic)
					                             || (logicPointer != IntPtr.Zero && (battle.Logic as Il2CppObjectBase)?.Pointer == logicPointer)))
					{
						pending = battle;
						break;
					}
				}
				if (pending == null)
					return;
				Battles.Remove(pending);
			}
			if (pending.Spoils <= 0)
				return;
			var gold = SpoilsGoldByLevel[Math.Min(pending.Spoils, SpoilsGoldByLevel.Length - 1)];
			var transfer = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
			var started = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle;
			var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
			if (result == null)
			{
				LogLimited("Spoils of Command skipped: battle result unreadable.");
				return;
			}
			var winner = result.winnerIndex;
			var ownerWon = winner >= 0 && winner == pending.OwnerIndex;
			if (!ownerWon && winner >= 0)
			{
				ownerWon = (started?.sides != null && winner < started.sides.Length && started.sides[winner]?.Pointer == pending.OwnerSide.Pointer)
				           || (transfer?.sides != null && winner < transfer.sides.Length && transfer.sides[winner]?.Pointer == pending.OwnerSide.Pointer);
			}
			if (!ownerWon)
				return;
			object logicHero = null;
			if (transfer?.sides != null && winner < transfer.sides.Length)
				logicHero = transfer.sides[winner]?.logicHero;
			logicHero ??= pending.OwnerSide.logicHero;
			if (!TryAddGold(logicHero, gold, out var fail))
			{
				LogLimited("Spoils of Command " + gold + " Gold failed closed: " + fail);
				return;
			}
			_log?.LogInfo("HoMM3 Castle Spoils of Command L" + pending.Spoils + ": +" + gold + " Gold after a won Strategem battle against neutrals.");
		}
		catch (Exception ex)
		{
			LogLimited("Spoils of Command failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static bool TryAddGold(object logicHero, int gold, out string failReason)
	{
		if (logicHero == null)
		{
			failReason = "owner has no hero";
			return false;
		}
		if (!Homm3CustomFactionLawRuntime.TryResolveDataSideFromLogicHeroExplained(logicHero, out var dataSide, out var pathFail))
		{
			var dataHero = Homm3DungeonCaptivesRuntime.ResolveDataHero(logicHero);
			if (dataHero == null || !Homm3SwashbucklerGoldHook.TryGetDayStartSide(dataHero.sideId, out var side))
			{
				failReason = "hero side unresolved (" + pathFail + ")";
				return false;
			}
			dataSide = side;
		}
		if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(dataSide, out var goldResource, out _, out var goldFail))
		{
			failReason = "gold resource unresolved (" + goldFail + ")";
			return false;
		}
		return Homm3RewardEconomyNativeAdapter.TryAddResourceValue(goldResource, gold, out failReason);
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cur = obj.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				var property = cur.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj);
				var field = cur.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
				var method = cur.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null)
					return method.Invoke(obj, null);
			}
		}
		return null;
	}

	private static bool TryBuff(Unit unit, string sid)
	{
		if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, sid, unit, 1, 1, 0, true, out _, out var fail))
			return true;
		LogLimited("law buff " + sid + " failed: " + fail);
		return false;
	}

	private static object FindSideWrapper(object logic, TransferSide side)
	{
		if (side == null)
			return null;
		if (ReadProperty(ReadProperty(logic, LogicState), StateSideWrappers) is not System.Collections.IEnumerable wrappers)
			return null;
		foreach (var wrapper in wrappers)
		{
			if (ReadProperty(wrapper, SideWrapperTransferSide) is TransferSide ts && ts.Pointer == side.Pointer)
				return wrapper;
		}
		return null;
	}

	private static readonly Dictionary<(Type, string), PropertyInfo> PropertyCache = new();

	private static PropertyInfo FindProperty(Type type, string name)
	{
		if (type == null || string.IsNullOrEmpty(name))
			return null;
		lock (PropertyCache)
		{
			if (PropertyCache.TryGetValue((type, name), out var cached))
				return cached;
			PropertyInfo found = null;
			for (var cur = type; cur != null && found == null; cur = cur.BaseType)
				found = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			PropertyCache[(type, name)] = found;
			return found;
		}
	}

	private static object ReadProperty(object obj, string name)
	{
		if (obj == null)
			return null;
		var property = FindProperty(obj.GetType(), name);
		if (property != null)
			return property.GetValue(obj);
		var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		return method?.Invoke(obj, null);
	}

	private static void Patch(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = typeof(Homm3CastleLawHooks).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (postfix == null)
			throw new MissingMethodException("postfix missing for " + target?.DeclaringType?.FullName + "." + target?.Name);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + target?.DeclaringType?.FullName + "." + target?.Name + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 40)
			_log?.LogWarning("HoMM3 Castle law hooks: " + message);
	}
}
