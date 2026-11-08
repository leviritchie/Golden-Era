using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace OfflineUnlockMod;

/// <summary>
/// Shared Split Assembly math for combat plans and adventure army-strip HUD.
/// Counts distinct manifest-owned Natural/Industrial lines; overclock adds +1
/// effective line; Expert gates the fourth tier.
/// </summary>
internal static class Homm3FactorySplitAssemblyEvaluator
{
	internal const string FactoryFactionSid = "homm3_factory";
	internal const string FactorySkillSid = "skill_faction_homm3_factory";
	internal const string NaturalBranch = "natural";
	internal const string IndustrialBranch = "industrial";
	internal const string NaturalOverclockSubSkillSid = "sub_skill_faction_homm3_factory_gantry_reserve";
	internal const string IndustrialOverclockSubSkillSid = "sub_skill_faction_homm3_factory_industrial_tempo";

	internal sealed class Snapshot
	{
		internal int Rank;
		internal int NaturalEffective;
		internal int IndustrialEffective;
		internal int NaturalTier;
		internal int IndustrialTier;
		internal int RankCap;
		internal bool NaturalOverclock;
		internal bool IndustrialOverclock;
		internal string NaturalLines = string.Empty;
		internal string IndustrialLines = string.Empty;
	}

	internal static int ResolveRankCap(int rank)
	{
		if (rank >= 3)
			return 4;
		if (rank == 2)
			return 3;
		if (rank == 1)
			return 2;
		return 0;
	}

	internal static int ResolveUnlockedTiers(int effectiveLines, int rank)
	{
		var tiers = Math.Max(0, Math.Min(4, effectiveLines));
		if (tiers >= 4 && rank < 3)
			tiers = 3;
		return tiers;
	}

	internal static bool TryEvaluate(
		IEnumerable<string> unitConfigSids,
		int rank,
		bool naturalOverclock,
		bool industrialOverclock,
		out Snapshot snapshot,
		out string failReason)
	{
		snapshot = null;
		failReason = null;
		if (rank < 1 || rank > 3)
		{
			failReason = "Factory skill level outside Basic/Advanced/Expert range: " + rank;
			return false;
		}
		if (unitConfigSids == null)
		{
			failReason = "unit config SID enumeration missing";
			return false;
		}

		if (!TryCountRepresentedLines(unitConfigSids, out var naturalLines, out var industrialLines, out failReason))
			return false;

		var naturalEffective = naturalLines.Count + (naturalOverclock ? 1 : 0);
		var industrialEffective = industrialLines.Count + (industrialOverclock ? 1 : 0);
		var naturalTier = ResolveUnlockedTiers(naturalEffective, rank);
		var industrialTier = ResolveUnlockedTiers(industrialEffective, rank);
		snapshot = new Snapshot
		{
			Rank = rank,
			NaturalEffective = naturalEffective,
			IndustrialEffective = industrialEffective,
			NaturalTier = naturalTier,
			IndustrialTier = industrialTier,
			RankCap = ResolveRankCap(rank),
			NaturalOverclock = naturalOverclock,
			IndustrialOverclock = industrialOverclock,
			NaturalLines = string.Join(",", naturalLines.OrderBy(value => value, StringComparer.Ordinal)),
			IndustrialLines = string.Join(",", industrialLines.OrderBy(value => value, StringComparer.Ordinal)),
		};
		return true;
	}

	internal static bool TryCountRepresentedLines(
		IEnumerable<string> unitConfigSids,
		out HashSet<string> naturalLines,
		out HashSet<string> industrialLines,
		out string failReason)
	{
		naturalLines = new HashSet<string>(StringComparer.Ordinal);
		industrialLines = new HashSet<string>(StringComparer.Ordinal);
		failReason = null;
		if (unitConfigSids == null)
		{
			failReason = "unit config SID enumeration missing";
			return false;
		}

		foreach (var rawSid in unitConfigSids)
		{
			var sid = NormalizeSid(rawSid);
			if (sid == null)
			{
				failReason = "unit has empty configSid";
				return false;
			}
			if (!Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(sid, out var factionSid)
			    || !string.Equals(factionSid, FactoryFactionSid, StringComparison.Ordinal))
				continue;
			if (!Homm3CustomFactionRegistry.TryGetManifestUnitBranch(sid, out var baseSid, out var branchFamily))
			{
				failReason = "Factory unit has no manifest-owned branch mapping: " + sid;
				return false;
			}
			baseSid = NormalizeSid(baseSid);
			branchFamily = NormalizeSid(branchFamily);
			if (baseSid == null)
			{
				failReason = "Factory unit branch mapping has empty canonical base SID: " + sid;
				return false;
			}
			if (string.Equals(branchFamily, NaturalBranch, StringComparison.Ordinal))
				naturalLines.Add(baseSid);
			else if (string.Equals(branchFamily, IndustrialBranch, StringComparison.Ordinal))
				industrialLines.Add(baseSid);
			else
			{
				failReason = "Factory unit line has unsupported branch: " + sid + " -> " + (branchFamily ?? "null");
				return false;
			}
		}
		return true;
	}

	internal static string BuildTooltipText(Snapshot snapshot)
	{
		if (snapshot == null)
			return string.Empty;
		var sb = new StringBuilder(256);
		sb.Append("Split Assembly");
		sb.Append('\n');
		sb.Append(RankLabel(snapshot.Rank));
		sb.Append(" magnitude");
		sb.Append('\n');
		sb.Append("Natural ");
		sb.Append(snapshot.NaturalTier);
		sb.Append('/');
		sb.Append(snapshot.RankCap);
		if (snapshot.NaturalOverclock)
			sb.Append(" (+1 Natural line)");
		sb.Append('\n');
		AppendNaturalBonuses(sb, snapshot);
		sb.Append("Industrial ");
		sb.Append(snapshot.IndustrialTier);
		sb.Append('/');
		sb.Append(snapshot.RankCap);
		if (snapshot.IndustrialOverclock)
			sb.Append(" (+1 Industrial line)");
		sb.Append('\n');
		AppendIndustrialBonuses(sb, snapshot);
		return sb.ToString().TrimEnd();
	}

	private static void AppendNaturalBonuses(StringBuilder sb, Snapshot snapshot)
	{
		var mag = MagnitudeLabel(snapshot.Rank);
		if (snapshot.NaturalTier >= 1)
			sb.Append("  ").Append(mag).Append(" ranged damage\n");
		if (snapshot.NaturalTier >= 2)
			sb.Append("  ").Append(mag).Append(" less damage taken\n");
		if (snapshot.NaturalTier >= 3)
			sb.Append("  +1 start Focus\n");
		if (snapshot.NaturalTier >= 4)
			sb.Append("  Carapace on all units\n");
		if (snapshot.NaturalTier <= 0)
			sb.Append("  (no Natural bonuses)\n");
	}

	private static void AppendIndustrialBonuses(StringBuilder sb, Snapshot snapshot)
	{
		var mag = MagnitudeLabel(snapshot.Rank);
		if (snapshot.IndustrialTier >= 1)
			sb.Append("  ").Append(mag).Append(" melee damage\n");
		if (snapshot.IndustrialTier >= 2)
			sb.Append("  ").Append(snapshot.Rank >= 3 ? "+2" : "+1").Append(" Speed\n");
		if (snapshot.IndustrialTier >= 3)
			sb.Append("  ").Append(snapshot.Rank >= 3 ? "+2" : "+1").Append(" Initiative\n");
		if (snapshot.IndustrialTier >= 4)
			sb.Append("  Field Triage\n");
		if (snapshot.IndustrialTier <= 0)
			sb.Append("  (no Industrial bonuses)\n");
	}

	private static string RankLabel(int rank)
	{
		return rank switch
		{
			1 => "Basic",
			2 => "Advanced",
			3 => "Expert",
			_ => "Rank " + rank,
		};
	}

	private static string MagnitudeLabel(int rank)
	{
		return rank switch
		{
			1 => "5%",
			2 => "10%",
			3 => "15%",
			_ => "?",
		};
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}
}
