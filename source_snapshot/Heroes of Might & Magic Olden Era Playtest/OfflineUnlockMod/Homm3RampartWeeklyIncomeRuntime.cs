using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using DataBuff = Hex.Session.Data.Buff;
using DataBuffDuration = Hex.Session.Data.BuffDuration;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// Rampart weekly town income (building pass 2026-11-22, docs/building_pass_20261122/rampart.md), paid at a side's
/// first day of each week (session day 8, 15, 22, ...; day 1 starts the game and pays nothing):
/// - Treasury (<c>Build_Rampart_Treasury</c>): floor(10% of the gold the side held when its day start began), per
///   owned Rampart city with the row, uncapped (HoMM3). Computed on the balance before that day's income (prefix
///   snapshot), as HoMM3 computes it on the start-of-week balance.
/// - Mystic Pond (<c>Build_Mystic_Pond</c>): per owned Rampart city with the row, 1-4 (uniform) of one of Mercury /
///   Crystals / Gemstones. The roll is a hash of side, week and town ordinal, so a reload re-rolls nothing.
///
/// Exactly once, across save and load: each side keeps a hidden, bonus-less side buff <see cref="StoreBuffSid"/> (Core
/// logic_side_buffs row, same carrier pattern as <see cref="Homm3FactoryLogisticsState"/>) whose durations hold
/// [VER, WEEK = last paid week index, SUM]. At a payday the store is written and read back first; only then is the
/// income added. A store that fails its checks is never overwritten and that side gets no weekly income (fail
/// closed, logged). The write happens in the side OnStartDay postfix, the same safe point the Factory store uses.
/// </summary>
internal static class Homm3RampartWeeklyIncomeRuntime
{
	internal const string PondSid = "Build_Mystic_Pond";
	internal const string TreasurySid = "Build_Rampart_Treasury";
	internal const string RampartCitySid = "homm3_rampart_city";
	internal const string StoreBuffSid = "homm3_rampart_income_store";
	private const string LogPrefix = "HoMM3 Rampart weekly income: ";
	private const int TreasuryPercent = 10;
	private static readonly string[] PondResources = { "mercury", "crystals", "gemstones" };

	private const int StoreVersion = 1;
	private const int RecMarker = 0x40000000;
	private const int RecTypeShift = 26;
	private const int RecDataMask = 0x3FFFFFF;
	private const int TVer = 1, TWeek = 2, TSum = 15;

	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _active;
	private static int _logged;
	private static PropertyInfo _sideDataProperty;
	private static readonly Dictionary<int, int> GoldAtDayStart = new();
	private static readonly HashSet<int> BlockedSides = new();

	private static void Info(string message)
	{
		if (_logged++ < 160)
			_log?.LogInfo(LogPrefix + message);
	}

	private static void Warn(string message)
	{
		if (_logged++ < 160)
			_log?.LogWarning(LogPrefix + message);
	}

	/// <summary>Register after <see cref="Homm3SwashbucklerGoldHook"/>: the postfix reads the day it caches.</summary>
	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			var sideLogicType = GameMember.FindType(GameSymbols.SwashbucklerGold.SideLogicTypeId, GameSymbols.SwashbucklerGold.SideLogicTypeHint)
			                    ?? throw new TypeLoadException("side logic type (SwashbucklerGold.SideLogicTypeHint)");
			_sideDataProperty = FindSideProperty(sideLogicType) ?? throw new MissingMemberException(sideLogicType.FullName, "Side property");
			var startDay = sideLogicType.GetMethod(GameSymbols.SwashbucklerGold.SideStartDayName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			               ?? throw new MissingMethodException(sideLogicType.FullName, GameSymbols.SwashbucklerGold.SideStartDayName);
			// Postfix priority Low: runs after the Swashbuckler postfix, which caches the side logic the day read uses.
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3RampartWeeklyIncomeRuntime), startDay, nameof(PrefixSideStartDay), nameof(PostfixSideStartDay), Priority.Low);
			_active = true;
			_log?.LogInfo(LogPrefix + "registered on " + sideLogicType.FullName + "." + startDay.Name + ".");
		}
		catch (Exception ex)
		{
			_active = false;
			_log?.LogWarning(LogPrefix + "NOT registered (no Mystic Pond or Treasury income): " + ex.GetBaseException().Message);
		}
	}

	private static PropertyInfo FindSideProperty(Type type)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in GameSymbols.SwashbucklerGold.SideDataProperties)
		{
			var p = string.IsNullOrEmpty(name) ? null : type.GetProperty(name, flags);
			if (p != null && p.PropertyType == typeof(DataSide))
				return p;
		}
		PropertyInfo match = null;
		foreach (var p in type.GetProperties(flags))
		{
			if (p.PropertyType != typeof(DataSide) || p.GetIndexParameters().Length != 0 || p.GetMethod == null)
				continue;
			if (match != null)
				return null;
			match = p;
		}
		return match;
	}

	private static DataSide SideOf(object sideLogic)
	{
		if (sideLogic == null || _sideDataProperty == null || !_sideDataProperty.DeclaringType.IsInstanceOfType(sideLogic))
			return null;
		return _sideDataProperty.GetValue(sideLogic) as DataSide;
	}

	private static bool TryReadGold(DataSide side, out int gold)
	{
		gold = 0;
		if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(side, "gold", out _, out var info, out _))
			return false;
		gold = info.Value;
		return true;
	}

	private static void PrefixSideStartDay(object __instance)
	{
		if (!_active)
			return;
		try
		{
			var side = SideOf(__instance);
			if (side == null)
				return;
			if (TryReadGold(side, out var gold))
				GoldAtDayStart[side.index] = gold;
			else
				GoldAtDayStart.Remove(side.index);
		}
		catch
		{
			// No snapshot: the postfix falls back to refusing the Treasury share for this day (logged there).
		}
	}

	private static void PostfixSideStartDay(object __instance)
	{
		if (!_active)
			return;
		DataSide side = null;
		try
		{
			side = SideOf(__instance);
			if (side == null || side.status != DataSide.EStatus.Life)
				return;
			var sideIndex = side.index;
			if (!Homm3SwashbucklerGoldHook.TryReadSessionDay(sideIndex, out var day) || day <= 1 || (day - 1) % 7 != 0)
				return;
			var week = (day - 1) / 7;

			var treasuries = Homm3TownBuildingReader.SideBuildingCount(side, TreasurySid, RampartCitySid);
			var ponds = Homm3TownBuildingReader.SideBuildingCount(side, PondSid, RampartCitySid);
			if (treasuries <= 0 && ponds <= 0)
				return;
			if (BlockedSides.Contains(sideIndex))
				return;

			if (!TryReadStore(side, out var paidWeek, out var storeFail))
			{
				BlockedSides.Add(sideIndex);
				Warn("side " + sideIndex + ": stored income record rejected (" + storeFail + "); this side gets no weekly Pond/Treasury income this session and the record is left untouched.");
				return;
			}
			if (paidWeek >= week)
			{
				Info("side " + sideIndex + " day " + day + ": week " + week + " already paid (stored); skipped.");
				return;
			}

			// Compute first, store second, pay last: a failed store pays nothing.
			var treasuryGold = 0;
			if (treasuries > 0)
			{
				if (GoldAtDayStart.TryGetValue(sideIndex, out var gold) && gold > 0)
					treasuryGold = checked((int)Math.Min(int.MaxValue, (long)gold * TreasuryPercent / 100 * treasuries));
				else if (!GoldAtDayStart.ContainsKey(sideIndex))
					Warn("side " + sideIndex + ": gold before the day start was unreadable; no Treasury share this week.");
			}
			var pond = new Dictionary<string, int>(StringComparer.Ordinal);
			for (var town = 0; town < ponds; town++)
			{
				var roll = Hash(sideIndex, week, town);
				var resource = PondResources[(int)(roll % (uint)PondResources.Length)];
				var amount = 1 + (int)((roll / (uint)PondResources.Length) % 4u);
				pond[resource] = (pond.TryGetValue(resource, out var have) ? have : 0) + amount;
			}

			if (!TryWriteStore(side, week, out var writeFail))
			{
				BlockedSides.Add(sideIndex);
				Warn("side " + sideIndex + ": could not store the paid week (" + writeFail + "); no weekly income is paid this session so it cannot be paid twice.");
				return;
			}
			var paid = new List<string>();
			if (treasuryGold > 0)
				paid.Add(Add(side, "gold", treasuryGold));
			foreach (var pair in pond)
				paid.Add(Add(side, pair.Key, pair.Value));
			Info("side " + sideIndex + " day " + day + " (week " + week + "): treasuries=" + treasuries + " ponds=" + ponds + " -> " + string.Join(", ", paid) + ".");
		}
		catch (Exception ex)
		{
			Warn("side " + (side?.index.ToString() ?? "?") + " day-start income threw " + ex.GetBaseException().Message + ".");
		}
	}

	private static string Add(DataSide side, string resource, int amount)
	{
		if (Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(side, resource, out var res, out _, out var fail)
		    && Homm3RewardEconomyNativeAdapter.TryAddResourceValue(res, amount, out fail))
			return "+" + amount + " " + resource;
		Warn("side " + side.index + ": adding " + amount + " " + resource + " failed (" + fail + "); the week is stored as paid.");
		return "FAILED " + amount + " " + resource;
	}

	private static uint Hash(int side, int week, int town)
	{
		unchecked
		{
			var h = 2166136261u;
			foreach (var v in new[] { 0x52504E44, side, week, town })
			{
				for (var b = 0; b < 4; b++)
				{
					h ^= ((uint)v >> (8 * b)) & 0xFF;
					h *= 16777619u;
				}
			}
			return h;
		}
	}

	// ---------------------------------------------------------------- store

	private static int Rec(int type, int data) => RecMarker | (type << RecTypeShift) | (data & RecDataMask);

	private static int Checksum(IReadOnlyList<int> records, int count)
	{
		unchecked
		{
			var h = 2166136261u;
			for (var i = 0; i < count; i++)
			{
				var v = (uint)records[i];
				for (var b = 0; b < 4; b++)
				{
					h ^= (v >> (8 * b)) & 0xFF;
					h *= 16777619u;
				}
			}
			return (int)(h & RecDataMask);
		}
	}

	private static DataBuff FindStore(DataSide side)
	{
		var list = side?.buffs?.list;
		if (list == null)
			return null;
		for (var i = 0; i < list.Count; i++)
		{
			var buff = list[i];
			if (buff != null && string.Equals(Homm3TowerArtificingRuntime.ReadMember(buff, GameSymbols.DungeonCaptives.DataBuffSidMembers) as string, StoreBuffSid, StringComparison.Ordinal))
				return buff;
		}
		return null;
	}

	/// <summary>Last paid week index; -1 when the side has no store yet. False when a store exists but fails its checks.</summary>
	private static bool TryReadStore(DataSide side, out int paidWeek, out string fail)
	{
		paidWeek = -1;
		fail = null;
		if (side?.buffs?.list == null)
		{
			fail = "side buff list unreadable";
			return false;
		}
		var carrier = FindStore(side);
		if (carrier == null)
			return true;
		var durations = carrier.durations;
		if (durations == null || durations.Length != 3)
		{
			fail = "carrier holds " + (durations?.Length ?? 0) + " records, expected 3";
			return false;
		}
		var raws = new List<int>(3);
		for (var i = 0; i < durations.Length; i++)
		{
			if (durations[i] == null)
			{
				fail = "record " + i + " is null";
				return false;
			}
			raws.Add(durations[i].leftValue);
		}
		foreach (var raw in raws)
		{
			if (raw < 0 || (raw & RecMarker) == 0)
			{
				fail = "not an income record";
				return false;
			}
		}
		if (((raws[0] >> RecTypeShift) & 0xF) != TVer || (raws[0] & RecDataMask) != StoreVersion)
		{
			fail = "unknown version";
			return false;
		}
		if (((raws[1] >> RecTypeShift) & 0xF) != TWeek)
		{
			fail = "no week record";
			return false;
		}
		if (((raws[2] >> RecTypeShift) & 0xF) != TSum || (raws[2] & RecDataMask) != Checksum(raws, 2))
		{
			fail = "checksum mismatch";
			return false;
		}
		paidWeek = raws[1] & RecDataMask;
		return true;
	}

	private static bool TryWriteStore(DataSide side, int week, out string fail)
	{
		fail = null;
		if (week < 0 || week > RecDataMask)
		{
			fail = "week " + week + " does not fit";
			return false;
		}
		var records = new List<int> { Rec(TVer, StoreVersion), Rec(TWeek, week) };
		records.Add(Rec(TSum, Checksum(records, records.Count)));
		var durations = new Il2CppReferenceArray<DataBuffDuration>(records.Count);
		for (var i = 0; i < records.Count; i++)
			durations[i] = new DataBuffDuration(EBuffDurationType.Infinite, records[i]);
		var carrier = FindStore(side);
		if (carrier == null)
		{
			carrier = new DataBuff();
			if (!TryWriteSid(carrier))
			{
				fail = "Buff sid member not writable";
				return false;
			}
			carrier.durations = durations;
			carrier.effectsCount = durations.Length;
			carrier.wasApplied = false;
			side.buffs.list.Add(carrier);
		}
		else
		{
			carrier.durations = durations;
			carrier.effectsCount = durations.Length;
		}
		if (!TryReadStore(side, out var back, out var readFail) || back != week)
		{
			fail = "read-back mismatch (" + (readFail ?? "week " + back) + ")";
			return false;
		}
		return true;
	}

	private static bool TryWriteSid(DataBuff buff)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in GameSymbols.DungeonCaptives.DataBuffSidMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var prop = typeof(DataBuff).GetProperty(name, flags);
			if (prop != null && prop.PropertyType == typeof(string) && prop.CanWrite)
			{
				prop.SetValue(buff, StoreBuffSid);
				if (string.Equals(prop.GetValue(buff) as string, StoreBuffSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}
}
