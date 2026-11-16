using System;
using System.Globalization;

namespace OfflineUnlockMod;

/// <summary>
/// Shared player-facing vocabulary of the Logistics Network (UX pass 2026-11-16, item 3). Every panel text that a player
/// reads goes through these helpers so the words stay the same everywhere:
/// - range is shown in days of travel, one decimal, 1 day = 200 MP (vanilla base hero movement); never raw MP or levels;
/// - "Upgrade Center N" (per-building marker from a skilled hero's visit) and "Command Center N" (Mobile Command Center);
/// - "powered level" = enhancement level plus Power Station levels;
/// - "Replaces output" / "Adds to output" = whether the active enhancement stops the building's own production.
/// Debug logs may keep MP. Pure helpers: no game state, no native calls.
/// </summary>
internal static class Homm3FactoryLogisticsPanelInfo
{
	/// <summary>Movement points in one day of travel (vanilla base hero movement).</summary>
	internal const double MpPerDay = 200.0;

	internal const string ReplacesOutputTag = "Replaces output";
	internal const string AddsToOutputTag = "Adds to output";

	/// <summary>"1.0 day" / "1.5 days" for a movement-point amount (one decimal).</summary>
	internal static string Days(double mp)
	{
		var days = Math.Max(0.0, mp) / MpPerDay;
		var text = days.ToString("0.0", CultureInfo.InvariantCulture);
		return text + (text == "1.0" ? " day" : " days");
	}

	/// <summary>Network range in days for a logistics level ("1.0 day" at the base level 2 x 100 MP).</summary>
	internal static string RangeDays(int logisticsLevel, int mpPerLevel) => Days((double)logisticsLevel * mpPerLevel);

	/// <summary>"Upgrade Center N" or "Command Center N" (the remote build level and where it comes from).</summary>
	internal static string RemoteCenter(int level, bool viaCommandCenter) => (viaCommandCenter ? "Command Center " : "Upgrade Center ") + level;

	/// <summary>True when an enhancement with this effect stops the building's own production (mines: resource; dwellings: units).</summary>
	internal static bool ReplacesOutput(string effect) =>
		effect is "export" or "warehouse" or "rail_station" or "power_station" or "synthesizer" or "arcane" or "mercenary" or "support";

	/// <summary>"Replaces output" / "Adds to output" for an enhancement id; null when the config or the id is unknown.</summary>
	internal static string OutputTag(string enhancementId)
	{
		if (enhancementId == null || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
			return null;
		var e = config.Get(enhancementId);
		return e == null ? null : ReplacesOutput(e.Effect) ? ReplacesOutputTag : AddsToOutputTag;
	}

	/// <summary>"Export Office L2" or, with Power Station levels, "Export Office L2 (powered 4)".</summary>
	internal static string LevelText(string name, int level, int powerBonus) =>
		(name ?? "Enhancement") + " L" + level + (powerBonus > 0 ? " (powered " + (level + powerBonus) + ")" : "");
}
