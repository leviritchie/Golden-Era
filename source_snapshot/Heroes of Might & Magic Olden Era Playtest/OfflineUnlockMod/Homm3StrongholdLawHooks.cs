using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// Stronghold faction laws that change Warcry (law pass 2026-11-21, docs/faction_law_pass_20261121/stronghold.md;
/// law pass 2026-11-25, docs/faction_law_pass_20261125/build_stronghold.md).
/// Ranks are read once per battle when the Warcry side is armed (<see cref="Homm3StrongholdWarcryRuntime"/>).
/// War Festival (#33) pays weekly Gold from the side day start (<see cref="TryRegisterWarFestival"/>).
/// Fail closed: no law, or a read failure, gives rank 0 and the skill's current behaviour.
/// </summary>
internal static class Homm3StrongholdLawHooks
{
	internal const string FactionSid = "homm3_stronghold";
	/// <summary>Drums of Krewlod: the Warcry counter starts each battle at 1/2.</summary>
	internal const int DrumsOfKrewlod = 5;
	/// <summary>Smouldering Rage: a broken Warcry keeps 25%/50% of its counter.</summary>
	internal const int SmoulderingRage = 9;
	// law pass 2026-11-25: #12 Tribes United retired (the Warcry reaches every friendly creature natively). Its slot is
	// Pent-up Rage, a lawRules stored_fury entry (homm3_stronghold.json) with no lever in this file.
	/// <summary>Unending Warcry: waiting or defending no longer breaks the Warcry (law pass 2026-11-25).</summary>
	internal const int UnendingWarcry = 13;
	/// <summary>War Festival: 2500/5000 Gold at the first day of each week (law pass 2026-11-25).</summary>
	internal const int WarFestival = 33;

	internal static readonly int[] SmoulderPercentByLevel = { 0, 25, 50 };
	/// <summary>law pass 2026-11-25: War Festival (#33). Must match the display carrier in homm3_stronghold.json.</summary>
	internal static readonly int[] WarFestivalGoldByLevel = { 0, 2500, 5000 };

	/// <summary>Law level (0 = not taken) for the battle side's owner; tries each owner object in turn.</summary>
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

	internal static int Level(int[] table, int rank) => table == null || rank <= 0 ? 0 : table[Math.Min(rank, table.Length - 1)];

	// ---------------------------------------------------------------- War Festival (#33)

	private const string WarFestivalLog = "HoMM3 Stronghold War Festival: ";
	private static bool _festivalAttempted;
	private static bool _festivalActive;
	private static int _festivalLogged;
	private static PropertyInfo _sideDataProperty;
	/// <summary>Last paid session day per (data side object, side index): a duplicate day-start call in the same session
	/// pays nothing; a loaded save has new side objects and pays its own timeline (the Swashbuckler gold pattern).</summary>
	private static readonly Dictionary<(IntPtr Side, int Index), int> FestivalPaidDay = new();

	/// <summary>
	/// law pass 2026-11-25: War Festival (#33). Postfix on the side logic OnStartDay, priority Low so it runs after the
	/// <see cref="Homm3SwashbucklerGoldHook"/> postfix that caches the side logic <see cref="Homm3SwashbucklerGoldHook.TryReadSessionDay"/>
	/// reads (Rampart weekly income pattern). Called from <see cref="Homm3StrongholdWarcryRuntime.TryRegister"/>, which
	/// Plugin.cs runs after the Swashbuckler registration. A failure only drops War Festival's Gold.
	/// </summary>
	internal static void TryRegisterWarFestival(Harmony harmony, ManualLogSource log)
	{
		if (_festivalAttempted || harmony == null)
			return;
		_festivalAttempted = true;
		try
		{
			var sideLogicType = GameMember.FindType(GameSymbols.SwashbucklerGold.SideLogicTypeId, GameSymbols.SwashbucklerGold.SideLogicTypeHint)
			                    ?? throw new TypeLoadException("side logic type (SwashbucklerGold.SideLogicTypeHint)");
			_sideDataProperty = FindSideProperty(sideLogicType) ?? throw new MissingMemberException(sideLogicType.FullName, "Side property");
			var startDay = sideLogicType.GetMethod(GameSymbols.SwashbucklerGold.SideStartDayName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			               ?? throw new MissingMethodException(sideLogicType.FullName, GameSymbols.SwashbucklerGold.SideStartDayName);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3StrongholdLawHooks), startDay, null, nameof(PostfixSideStartDayWarFestival), Priority.Low);
			_festivalActive = true;
			log?.LogInfo(WarFestivalLog + "registered on " + sideLogicType.FullName + "." + startDay.Name + ".");
		}
		catch (Exception ex)
		{
			_festivalActive = false;
			log?.LogWarning(WarFestivalLog + "NOT registered (no weekly Gold from the law): " + ex.GetBaseException().Message);
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

	// law pass 2026-11-25: War Festival (#33)
	private static void PostfixSideStartDayWarFestival(object __instance)
	{
		if (!_festivalActive || __instance == null || _sideDataProperty == null || !_sideDataProperty.DeclaringType.IsInstanceOfType(__instance))
			return;
		DataSide side = null;
		try
		{
			side = _sideDataProperty.GetValue(__instance) as DataSide;
			if (side == null || side.status != DataSide.EStatus.Life)
				return;
			var sideIndex = side.index;
			// The first day of each week after the first (session day 8, 15, 22, ...); day 1 starts the game.
			if (!Homm3SwashbucklerGoldHook.TryReadSessionDay(sideIndex, out var day) || day <= 1 || (day - 1) % 7 != 0)
				return;
			var gold = Level(WarFestivalGoldByLevel, Rank(WarFestival, side));
			if (gold <= 0)
				return;
			var key = (side.Pointer, sideIndex);
			lock (FestivalPaidDay)
			{
				if (FestivalPaidDay.TryGetValue(key, out var paidDay) && paidDay == day)
					return;
				FestivalPaidDay[key] = day;
			}
			if (Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(side, "gold", out var res, out _, out var fail)
			    && Homm3RewardEconomyNativeAdapter.TryAddResourceValue(res, gold, out fail))
			{
				if (_festivalLogged++ < 40)
					Plugin.LogSource?.LogInfo(WarFestivalLog + "side " + sideIndex + " day " + day + ": +" + gold + " Gold.");
			}
			else if (_festivalLogged++ < 40)
			{
				Plugin.LogSource?.LogWarning(WarFestivalLog + "side " + sideIndex + " day " + day + ": adding " + gold + " Gold failed (" + fail + ").");
			}
		}
		catch (Exception ex)
		{
			if (_festivalLogged++ < 40)
				Plugin.LogSource?.LogWarning(WarFestivalLog + "side " + (side?.index.ToString() ?? "?") + " day start threw " + ex.GetBaseException().Message + " (no Gold paid).");
		}
	}
}
