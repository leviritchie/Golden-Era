using System;
using System.Collections.Generic;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Player notices of the Logistics Network (UX pass 2026-11-16, items 18, 19 and 22), all on the shared result banner
/// (<see cref="Homm3DungeonWarCaptivesWindow.ShowBanner"/>, the banner the runtime already uses on a viewer failure):
/// - day/week-start digest: remote builds finished, switches applied and weekly switches available again, collected where
///   <see cref="Homm3FactoryLogisticsRuntime.Maintain"/> applies pending changes and shown once the side's day start is done;
/// - capture loss: what a captured building lost and where, shown as soon as it is safe;
/// - one-line hints (a hero without the skill visiting an owned building).
/// Native hooks only queue text here; <see cref="Tick"/> (runtime host, every frame) shows it at a safe point: no battle,
/// no Logistics panel open. Local human sides only (the runtime keeps state for nothing else). Proof tier: build only.
/// </summary>
internal static class Homm3FactoryLogisticsDigest
{
	private const int MaxLines = 7;
	private const float SettleSeconds = 0.75f;

	private sealed class Pending
	{
		internal readonly List<string> Lines = new();
		internal float LastNote;
	}

	private static readonly Dictionary<int, Pending> DayLines = new();
	private static readonly List<string> Urgent = new();
	private static readonly Dictionary<int, int> LastWeekBySide = new();
	private static float _urgentSince;
	private static float _nextBattleCheck;
	private static bool _battleActive;

	/// <summary>Called by the runtime's single session reset.</summary>
	internal static void Clear()
	{
		DayLines.Clear();
		Urgent.Clear();
		LastWeekBySide.Clear();
	}

	// ---------------------------------------------------------------- notes (safe from native hooks: text only)

	internal static void NoteRemoteBuild(int side, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig config, int objectId, int code, int level) =>
		AddDay(side, "Remote build finished: " + EnhancementName(config, code) + " L" + level + " at " + BuildingLabel(world, config, objectId) + ", now active.");

	internal static void NoteSwitch(int side, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig config, int objectId, int code) =>
		AddDay(side, "Switch applied: " + EnhancementName(config, code) + " is now active at " + BuildingLabel(world, config, objectId) + ".");

	/// <summary>Capture loss: every enhancement on the building is gone (DECISIONS.md #22). Shown at the next safe point.</summary>
	internal static void NoteCaptureLoss(Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig config, Homm3FactoryLogisticsState.ObjectState o)
	{
		var lost = new List<string>();
		foreach (var pair in o.Built)
		{
			var level = Math.Max(pair.Value.Level, 0);
			if (level > 0)
				lost.Add(EnhancementName(config, pair.Key) + " L" + level);
			else if (pair.Value.PendingLevel > 0)
				lost.Add(EnhancementName(config, pair.Key) + " (under construction)");
		}
		var where = BuildingLabel(world, config, o.ObjectId);
		var text = lost.Count == 0
			? "Logistics Network: " + where + " was captured; its Upgrade Center is lost."
			: "Logistics Network: " + where + " was captured. Destroyed: " + string.Join(", ", lost) + ".";
		Show(text);
	}

	/// <summary>A one-line notice shown at the next safe point (replaces nothing queued; several are joined).</summary>
	internal static void Show(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return;
		if (Urgent.Count == 0)
			_urgentSince = Time.realtimeSinceStartup;
		if (!Urgent.Contains(text))
			Urgent.Add(text);
	}

	/// <summary>
	/// Side day start (postfix, after Maintain applied pending changes): notes the weekly switch reset on the first day of
	/// a new week and lets <see cref="Tick"/> show the day's lines.
	/// </summary>
	internal static void OnSideDayStarted(int side, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsState.SideState state)
	{
		if (world == null || state == null)
			return;
		var firstSeen = !LastWeekBySide.TryGetValue(side, out var lastWeek);
		LastWeekBySide[side] = world.WeekId;
		if (firstSeen || lastWeek == world.WeekId)
			return;
		var reset = 0;
		foreach (var o in state.Objects.Values)
		{
			if (o.SwitchWeek != 0 && o.SwitchWeek != world.WeekId && o.Built.Count > 1)
				reset++;
		}
		if (reset > 0)
			AddDay(side, "New week: the weekly switch is available again on " + reset + (reset == 1 ? " building." : " buildings."));
	}

	private static void AddDay(int side, string line)
	{
		if (!DayLines.TryGetValue(side, out var p))
			DayLines[side] = p = new Pending();
		p.Lines.Add(line);
		p.LastNote = Time.realtimeSinceStartup;
	}

	// ---------------------------------------------------------------- display (runtime host tick)

	internal static void Tick()
	{
		if (DayLines.Count == 0 && Urgent.Count == 0)
			return;
		var now = Time.realtimeSinceStartup;
		if (Homm3FactoryLogisticsUpgradePanel.IsOpen || Homm3FactoryLogisticsViewer.IsOpen)
			return;
		if (now >= _nextBattleCheck)
		{
			_nextBattleCheck = now + 0.5f;
			_battleActive = TempleSwordsmanBillboardPrototype.IsBattleViewActive();
		}
		if (_battleActive)
			return;
		try
		{
			var lines = new List<string>();
			if (Urgent.Count > 0 && now - _urgentSince >= SettleSeconds)
			{
				lines.AddRange(Urgent);
				Urgent.Clear();
			}
			var ready = new List<int>();
			foreach (var pair in DayLines)
			{
				if (now - pair.Value.LastNote >= SettleSeconds)
					ready.Add(pair.Key);
			}
			var day = new List<string>();
			foreach (var side in ready)
			{
				day.AddRange(DayLines[side].Lines);
				DayLines.Remove(side);
			}
			if (day.Count > 0)
			{
				if (Homm3FactoryLogisticsEffects.TryReadDay(out var d, out _, out _))
					lines.Add("Logistics Network, day " + d + ":");
				else
					lines.Add("Logistics Network:");
				lines.AddRange(day);
			}
			if (lines.Count == 0)
				return;
			if (lines.Count > MaxLines)
			{
				var more = lines.Count - (MaxLines - 1);
				lines.RemoveRange(MaxLines - 1, lines.Count - (MaxLines - 1));
				lines.Add("... and " + more + " more (open the Logistics Network spell).");
			}
			// The banner wraps long lines (760 px plate); size it for the wrapped line count.
			var rows = 0;
			foreach (var line in lines)
				rows += Math.Max(1, (int)Math.Ceiling(Homm3FactoryLogisticsUi.TextWidth(line, 18f) / 680f));
			Homm3DungeonWarCaptivesWindow.ShowBanner(string.Join("\n", lines), rows);
			Homm3FactoryLogisticsRuntime.LogEvent("notice shown: " + string.Join(" | ", lines));
		}
		catch (Exception ex)
		{
			DayLines.Clear();
			Urgent.Clear();
			Homm3FactoryLogisticsRuntime.LogOncePerDay("digest", "notice banner failed: " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- labels

	internal static string EnhancementName(Homm3FactoryLogisticsConfig config, int code) => config?.Get(code)?.Name ?? "an enhancement";

	/// <summary>"Gem Pond (12, 40)" / "Gremlin Dwelling (3, 5)": the building's player-facing name and its map tile.</summary>
	internal static string BuildingLabel(Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig config, int objectId)
	{
		var name = "Building";
		try
		{
			if (world.Mines.TryGetValue(objectId, out var mine))
				name = Homm3FactoryLogisticsEffects.MineDisplayName(Homm3FactoryLogisticsEffects.MineResource(mine));
			else if (world.Dwellings.TryGetValue(objectId, out var dwelling) && config != null
			         && Homm3FactoryLogisticsEffects.TryReadDwellingUnit(dwelling, config, out var unitSid, out _, out _, out _) && unitSid != null)
				name = Homm3UnitDisplayNames.Resolve(unitSid) + " Dwelling";
			if (Homm3FactoryLogisticsEffects.TryGetTile(world, objectId, out var x, out var y, out _))
				name += " (" + x + ", " + y + ")";
		}
		catch
		{
			// Label only: a failed read keeps the generic name.
		}
		return name;
	}
}
