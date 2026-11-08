using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Hunting Grounds hero-portrait meter (shared Homm3HeroSkillMeterHud): fill = trophies / cap, tick marks at the
/// enemy-penalty milestones, a distinct "restock used" state when full (spent fill colour, dimmed icon), and the
/// details on hover in the native tooltip. HUD only: reads Homm3FortressHuntingGroundsHook.TryReadMeterState; the
/// trophy buff stays the saved state. tools/homm3_hero_skill_meter_mockup.py parses <see cref="Layout"/> and checks
/// <see cref="Milestones"/> against the overlay.
/// </summary>
internal static class Homm3FortressHuntingGroundsMeter
{
	internal static class Layout
	{
		internal const string MeterKey = "fortress_hunting_grounds";
		internal const int MeterOrder = 20;
		internal static readonly string[] IconKeyByLevel = { "skill_faction_homm3_fortress", "skill_faction_homm3_fortress", "skill_faction_homm3_fortress_2", "skill_faction_homm3_fortress_3" };
		internal static readonly Color FillColor = new(0.78f, 0.60f, 0.26f, 1f);
		internal static readonly Color SpentFillColor = new(0.56f, 0.54f, 0.50f, 1f);
		internal const string TooltipHeadingColor = "#D6BC7C";
		internal const string TooltipNoteColor = "#B4ADA3";
	}

	/// <summary>
	/// (trophies, -Initiative, -Speed) per skill level 1..3. Must match HOMM3_FORTRESS_HUNTING_GROUNDS_MILESTONES in
	/// tools/release_port/apply_release_core_overlay.py (the Core trophy buffs carry the real penalty); caps are
	/// Homm3FortressHuntingGroundsHook.CapByLevel.
	/// </summary>
	internal static readonly int[][][] Milestones =
	{
		Array.Empty<int[]>(),
		new[] { new[] { 3, 1, 0 }, new[] { 6, 1, 1 } },
		new[] { new[] { 2, 1, 0 }, new[] { 5, 1, 1 } },
		new[] { new[] { 2, 1, 0 }, new[] { 4, 1, 1 }, new[] { 6, 2, 1 } },
	};

	private static bool _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		_registered = Homm3HeroSkillMeterHud.Register(new Homm3HeroSkillMeterSpec
		{
			Key = Layout.MeterKey,
			Order = Layout.MeterOrder,
			IconKey = Layout.IconKeyByLevel[1],
			FillColor = Layout.FillColor,
			SpentFillColor = Layout.SpentFillColor,
			Read = ReadMeter,
		}, harmony, log);
		if (!_registered)
			log?.LogWarning("HoMM3 Fortress Hunting Grounds meter not registered (fail closed, no meter; trophies unaffected).");
	}

	internal static void NotifyStateChanged(string reason)
	{
		if (_registered)
			Homm3HeroSkillMeterHud.NotifyStateChanged("hunting grounds " + reason);
	}

	private static bool ReadMeter(object logicHero, out Homm3HeroSkillMeterState state, out string failReason)
	{
		state = null;
		if (!Homm3FortressHuntingGroundsHook.TryReadMeterState(logicHero, out var level, out var trophies, out var buffLevel, out failReason))
			return false;
		if (level <= 0)
			return true;
		state = BuildState(level, trophies, buffLevel > 0 ? buffLevel : level);
		return true;
	}

	internal static void Penalty(int level, int trophies, out int initiative, out int speed)
	{
		initiative = speed = 0;
		foreach (var m in Milestones[Math.Max(0, Math.Min(3, level))])
		{
			if (trophies >= m[0])
			{
				initiative = m[1];
				speed = m[2];
			}
		}
	}

	internal static string PenaltyText(int initiative, int speed)
	{
		var parts = new List<string>();
		if (initiative != 0)
			parts.Add("-" + initiative + " Initiative");
		if (speed != 0)
			parts.Add("-" + speed + " Speed");
		return parts.Count == 0 ? "no penalty yet" : string.Join(" and ", parts);
	}

	/// <param name="level">Current skill level (cap, ticks, next milestone).</param>
	/// <param name="penaltyLevel">Level the trophy buff was recorded at (its Core bonuses are the live penalty).</param>
	internal static Homm3HeroSkillMeterState BuildState(int level, int trophies, int penaltyLevel)
	{
		level = Math.Max(1, Math.Min(3, level));
		var cap = Homm3FortressHuntingGroundsHook.CapByLevel[level];
		var shown = Math.Max(0, Math.Min(trophies, cap));
		var full = shown >= cap;
		var ticks = new List<float>();
		foreach (var m in Milestones[level])
		{
			if (m[0] > 0 && m[0] < cap)
				ticks.Add((float)m[0] / cap);
		}
		Penalty(penaltyLevel, shown, out var ini, out var spd);

		var sb = new StringBuilder();
		sb.Append("<color=").Append(Layout.TooltipHeadingColor).Append(">Hunting Grounds</color>\n");
		sb.Append("Trophies: ").Append(shown).Append(" / ").Append(cap).Append(full ? " (full)" : "").Append('\n');
		sb.Append("Enemy units in this hero's battles: ").Append(PenaltyText(ini, spd)).Append('\n');
		if (full)
		{
			sb.Append("This week's restock: used");
		}
		else
		{
			int[] next = null;
			foreach (var m in Milestones[level])
			{
				if (m[0] > shown)
				{
					next = m;
					break;
				}
			}
			sb.Append("Next: ");
			if (next != null && next[0] < cap)
				sb.Append(PenaltyText(next[1], next[2])).Append(" at ").Append(next[0]);
			else if (next != null)
				sb.Append(PenaltyText(next[1], next[2])).Append(" and the restock at ").Append(cap);
			else
				sb.Append("the restock at ").Append(cap);
			sb.Append("\nThis week's restock: not used yet (fill the meter to restock the weekly sites you visited)");
		}
		sb.Append("\n<color=").Append(Layout.TooltipNoteColor).Append(">Win battles to add Trophies. Resets at the start of each week.</color>");

		return new Homm3HeroSkillMeterState
		{
			Fill = (float)shown / cap,
			Ticks = ticks.ToArray(),
			Spent = full,
			IconKey = Layout.IconKeyByLevel[level],
			Tooltip = sb.ToString(),
			LogSummary = "level=" + level + " trophies=" + shown + "/" + cap + " penalty=-" + ini + "ini/-" + spd + "spd" + (full ? " restock used" : "")
				+ " fill=" + ((float)shown / cap).ToString("0.000", CultureInfo.InvariantCulture),
		};
	}
}
