using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BattleHex = Hex.Session.Battle.Hex;

namespace OfflineUnlockMod;

/// <summary>
/// Bulwark law pass 2026-11-21 (docs/faction_law_pass_20261121/bulwark.md): the faction laws that act on Runes.
/// <see cref="Homm3BulwarkRunesRuntime"/> reads the levels through the helpers here; this class also owns the battle
/// grid reads the laws need: Runes Carved in Advance (#7) grants its levels at round 1, and Shared Runes (#12) finds
/// the adjacent friendly stacks. Fail closed: no law, an unreadable owner or a missing surface leaves Runes as they were.
/// </summary>
internal static class Homm3BulwarkLawHooks
{
	internal const string FactionSid = "homm3_bulwark";
	/// <summary>Runes Carved in Advance: Bulwark creatures start each battle at Rune Level 1/2.</summary>
	internal const int CarvedInAdvanceLaw = 7;
	/// <summary>Clan Oath: Defend gives 4/5 Rune Levels; at both levels the first damage taken in an action gives 3.</summary>
	internal const int ClanOathLaw = 8;
	/// <summary>Shared Runes: reaching Rune Level 3/6/9/12 gives each adjacent friendly stack 1 Rune Level.</summary>
	internal const int SharedRunesLaw = 12;
	/// <summary>Elder Runes: with Expert Runes the Rune Level limit is 12; levels 10-12 carry the law buffs below.</summary>
	internal const int ElderRunesLaw = 30;

	internal const int ElderCapBonus = 3;
	internal const int MaxRuneLevel = Homm3BulwarkRunesRuntime.CapExpert + ElderCapBonus;
	/// <summary>law_overrides/homm3_bulwark.json lawBuffs h3_law_bulwark_rune_level_10..12.</summary>
	internal const string ElderBuffSidPrefix = "h3_law_bulwark_rune_level_";

	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _live;
	private static int _logged;
	private static MethodInfo _hexDistance;
	private static readonly object Gate = new();
	private static readonly List<BattleRecord> Battles = new();

	private sealed class BattleRecord
	{
		internal object Logic;
		internal IntPtr HubPointer;
		internal bool RoundOneDone;
		internal int LastRound;
		/// <summary>Clan March: hex of each stack at the last round start.</summary>
		internal readonly Dictionary<IntPtr, IntPtr> Positions = new();
	}

	private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
	private static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
	private static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
	private static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
	private static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
	private static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
	private static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);
	private static string StatePathfinder => At(GameSymbols.RampartAvengerStrike.StatePathfinderMembers, 0);

	// ------------------------------------------------------------------ law levels

	internal static int Rank(object logicHero, int lawIndex)
	{
		if (logicHero == null)
			return 0;
		try
		{
			return Math.Max(0, Homm3CustomFactionLawRuntime.CustomLawRank(logicHero, lawIndex, FactionSid));
		}
		catch
		{
			return 0;
		}
	}

	// law pass 2026-11-21: Elder Runes (#30): cap + 3. law pass 2026-11-25: Elder Runes (#30) applies only to the Expert cap
	// (9 -> 12); the gate is in Homm3BulwarkRunesRuntime where the cap is resolved.
	internal static int CapBonus(object logicHero) => Rank(logicHero, ElderRunesLaw) > 0 ? ElderCapBonus : 0;

	// law pass 2026-11-21: Clan Oath (#8): Defend 3 -> 4/5.
	internal static int DefendGain(int clanOathLevel, int baseGain)
	{
		return clanOathLevel > 0 ? Math.Max(baseGain, Homm3BulwarkRunesRuntime.GainForDefend() + Math.Min(clanOathLevel, 2)) : baseGain;
	}

	// law pass 2026-11-25: Clan Oath (#8): first damage taken in an action 2 -> 3 at both levels (was level 2 only).
	internal static int DamageGain(int clanOathLevel, int baseGain)
	{
		return clanOathLevel >= 1 ? Math.Max(baseGain, Homm3BulwarkRunesRuntime.GainForDamageTakenOncePerAction() + 1) : baseGain;
	}

	internal static bool IsShareThreshold(int threshold) => threshold > 0 && threshold % 3 == 0;

	// ------------------------------------------------------------------ battle surfaces

	/// <summary>Called from <see cref="Homm3BulwarkRunesRuntime.TryRegister"/>; fail closed (Carved at round 1 and
	/// Shared Runes need the grid; the rest of the laws work without it).</summary>
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
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher)
			                   ?? throw new MissingMethodException("RoundStarted dispatcher");
			var stateType = (FindProperty(logicType, LogicState) ?? throw new MissingMemberException(logicType.FullName + "." + LogicState)).PropertyType;
			var pathfinderType = (FindProperty(stateType, StatePathfinder) ?? throw new MissingMemberException(stateType.FullName + "." + StatePathfinder)).PropertyType;
			_hexDistance = FindStaticMethod(pathfinderType, GameSymbols.RampartAvengerStrike.HexDistance.NameHints, 2)
			               ?? throw new MissingMethodException("hex distance");
			Patch(harmony, init, nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, nameof(PostfixRoundStarted));
			_live = true;
			_log?.LogInfo("HoMM3 Bulwark law hooks registered: Runes Carved in Advance at round 1, Shared Runes adjacency.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Bulwark law hooks NOT registered (Carved in Advance waits for each stack's first Rune event; Shared Runes does nothing): "
			                 + ex.GetBaseException().Message);
		}
	}

	private static void PostfixBattleLogicInit(object __instance)
	{
		try
		{
			var hub = ReadProperty(ReadProperty(__instance, LogicHubs), HubsRoundHub) as Il2CppObjectBase;
			if (hub == null)
				return;
			lock (Gate)
			{
				Battles.RemoveAll(b => b.HubPointer == hub.Pointer);
				Battles.Add(new BattleRecord { Logic = __instance, HubPointer = hub.Pointer });
				while (Battles.Count > 4)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			LogLimited("Init postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	// law pass 2026-11-21: Runes Carved in Advance (#7): every eligible stack gets its levels at round 1.
	// Runes subskills (2026-11-25): Elder Mark at round 1 (before the grants), Clan March every later round.
	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			if (__instance is not Il2CppObjectBase hub || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args || args.roundNumber < 1)
				return;
			BattleRecord record = null;
			var firstRound = false;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (battle.HubPointer == hub.Pointer && args.roundNumber > battle.LastRound)
					{
						battle.LastRound = args.roundNumber;
						firstRound = !battle.RoundOneDone;
						battle.RoundOneDone = true;
						record = battle;
						break;
					}
				}
			}
			if (record == null)
				return;
			var units = new List<Unit>();
			var marched = new List<Unit>();
			foreach (var (unit, hex) in EnumerateUnits(record.Logic))
			{
				if (units.Exists(u => u.Pointer == unit.Pointer))
					continue;
				units.Add(unit);
				if (record.Positions.TryGetValue(unit.Pointer, out var previous) && previous != hex.Pointer)
					marched.Add(unit);
				record.Positions[unit.Pointer] = hex.Pointer;
			}
			if (!firstRound)
			{
				var moved = 0;
				foreach (var unit in marched)
				{
					if (Homm3FortressPredatorInstinctRuntime.IsAlive(unit) && Homm3BulwarkRunesRuntime.ApplyClanMarch(unit))
						moved++;
				}
				if (moved > 0)
					_log?.LogInfo("HoMM3 Bulwark Clan March: " + moved + " stack(s) at round " + args.roundNumber + ".");
				return;
			}
			Homm3BulwarkRuneSubskills.GrantElderMarks(units);
			var granted = 0;
			foreach (var unit in units)
			{
				if (Homm3BulwarkRunesRuntime.ApplyCarvedInAdvance(unit))
					granted++;
			}
			if (granted > 0)
				_log?.LogInfo("HoMM3 Bulwark Runes Carved in Advance: " + granted + " stack(s) at round " + args.roundNumber + ".");
			// building pass 2026-11-22: Altar of the Runes, after Carved so the Carved fold is never doubled.
			var altar = Homm3BulwarkAltarRunesRuntime.GrantRoundOne(units);
			if (altar > 0)
				_log?.LogInfo("HoMM3 Bulwark Altar of the Runes: " + altar + " stack(s) at round " + args.roundNumber + ".");
		}
		catch (Exception ex)
		{
			LogLimited("RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// law pass 2026-11-21: Shared Runes (#12). Living stacks on <paramref name="unit"/>'s side standing next to any of
	/// its hexes (all six neighbours). Empty when the grid cannot be read.
	/// </summary>
	internal static List<Unit> AdjacentFriendlyUnits(object unit)
	{
		var result = new List<Unit>();
		if (!_live || unit is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return result;
		try
		{
			var self = il2Cpp as Unit ?? il2Cpp.TryCast<Unit>();
			if (self == null)
				return result;
			var side = ReadProperty(self, FieldObjectSide) as Il2CppObjectBase;
			if (side == null)
				return result;
			List<BattleRecord> battles;
			lock (Gate)
				battles = new List<BattleRecord>(Battles);
			for (var b = battles.Count - 1; b >= 0; b--)
			{
				var own = new List<BattleHex>();
				var others = new Dictionary<IntPtr, (Unit Unit, List<BattleHex> Hexes)>();
				foreach (var (other, hex) in EnumerateUnits(battles[b].Logic))
				{
					if (other.Pointer == self.Pointer)
					{
						own.Add(hex);
						continue;
					}
					if (ReadProperty(other, FieldObjectSide) is not Il2CppObjectBase otherSide || otherSide.Pointer != side.Pointer)
						continue;
					if (!others.TryGetValue(other.Pointer, out var entry))
						others[other.Pointer] = entry = (other, new List<BattleHex>());
					entry.Hexes.Add(hex);
				}
				if (own.Count == 0)
					continue;
				foreach (var entry in others.Values)
				{
					if (Homm3FortressPredatorInstinctRuntime.IsAlive(entry.Unit) && AnyAdjacent(own, entry.Hexes))
						result.Add(entry.Unit);
				}
				return result;
			}
		}
		catch (Exception ex)
		{
			LogLimited("adjacency read failed closed: " + ex.GetBaseException().Message);
			result.Clear();
		}
		return result;
	}

	/// <summary>
	/// Runes subskills (2026-11-25): Frost Tempo. The living enemy creature (no war machines) closest to
	/// <paramref name="unit"/> by hex distance. Null when the grid cannot be read.
	/// </summary>
	internal static Unit NearestEnemy(object unit)
	{
		if (!_live || unit is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		try
		{
			var self = il2Cpp as Unit ?? il2Cpp.TryCast<Unit>();
			var side = self == null ? null : ReadProperty(self, FieldObjectSide) as Il2CppObjectBase;
			if (side == null)
				return null;
			List<BattleRecord> battles;
			lock (Gate)
				battles = new List<BattleRecord>(Battles);
			for (var b = battles.Count - 1; b >= 0; b--)
			{
				var own = new List<BattleHex>();
				var enemies = new List<(Unit Unit, BattleHex Hex)>();
				foreach (var (other, hex) in EnumerateUnits(battles[b].Logic))
				{
					if (other.Pointer == self.Pointer)
						own.Add(hex);
					else if (ReadProperty(other, FieldObjectSide) is Il2CppObjectBase otherSide && otherSide.Pointer != side.Pointer)
						enemies.Add((other, hex));
				}
				if (own.Count == 0)
					continue;
				Unit nearest = null;
				var best = int.MaxValue;
				foreach (var (other, hex) in enemies)
				{
					if (!Homm3FortressPredatorInstinctRuntime.IsAlive(other)
					    || Homm3BulwarkRunesRuntime.IsWarMachineExcluded(Homm3BulwarkRunesRuntime.TryResolveBattleUnitSid(other)))
						continue;
					foreach (var from in own)
					{
						var distance = Distance(from, hex);
						if (distance < best)
						{
							best = distance;
							nearest = other;
						}
					}
				}
				return nearest;
			}
		}
		catch (Exception ex)
		{
			LogLimited("enemy read failed closed: " + ex.GetBaseException().Message);
		}
		return null;
	}

	private static IEnumerable<(Unit Unit, BattleHex Hex)> EnumerateUnits(object logic)
	{
		if (ReadProperty(ReadProperty(logic, LogicGrid), GridHexes) is not Il2CppReferenceArray<BattleHex> hexes)
			yield break;
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				if (unit != null)
					yield return (unit, hex);
			}
		}
	}

	private static bool AnyAdjacent(List<BattleHex> a, List<BattleHex> b)
	{
		foreach (var x in a)
		{
			foreach (var y in b)
			{
				if (Distance(x, y) == 1)
					return true;
			}
		}
		return false;
	}

	private static int Distance(BattleHex a, BattleHex b)
	{
		if (a == null || b == null || _hexDistance == null)
			return int.MaxValue;
		if (a.Pointer == b.Pointer)
			return 0;
		try
		{
			return (int)_hexDistance.Invoke(null, new object[] { a, b });
		}
		catch
		{
			return int.MaxValue;
		}
	}

	// ------------------------------------------------------------------ reflection

	private static MethodInfo FindStaticMethod(Type type, string[] names, int parameterCount)
	{
		if (type == null)
			return null;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
			{
				if (method.Name == name && method.GetParameters().Length == parameterCount)
					return method;
			}
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
		var postfix = typeof(Homm3BulwarkLawHooks).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (postfix == null)
			throw new MissingMethodException("postfix missing for " + target?.DeclaringType?.FullName + "." + target?.Name);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + target?.DeclaringType?.FullName + "." + target?.Name + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 40)
			_log?.LogWarning("HoMM3 Bulwark law hooks: " + message);
	}
}
