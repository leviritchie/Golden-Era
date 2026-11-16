using System;
using System.Reflection;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Mirrors <c>DamageCalculatorUtility.RollCritDamageMultiplier</c> (see game sources / demo decompilation):
/// luck drives a single Bernoulli trial; on success positive luck applies <c>1.5f + crit</c>, negative luck applies <c>0.5f</c>.
/// Base chance comes from <see cref="BattleBalanceConfig.luckDistribution"/> at index <c>|luck| - 1</c>, plus per-point modifiers.
/// </summary>
internal static class LuckCritMixture
{
	private static bool _loggedCritUnresolved;
	private static bool _loggedLuckDistributionUnresolved;
	private static bool _loggedDisableCritsUnresolved;

	/// <summary>
	/// Fallback when the live table cannot be read: <c>BattleBalanceConfig.luckDistribution</c> is
	/// [0.08, 0.16, 0.24, 0.32, 0.40] in the 25672315 and 26297049 cores (port 26297049 lane finding
	/// plugin_behavior:luck-histogram-stale-distribution; the old 0.05..0.25 table was never the game's).
	/// </summary>
	internal static readonly float[] DefaultLuckDistribution = { 0.08f, 0.16f, 0.24f, 0.32f, 0.40f };

	/// <summary>
	/// Live luck table from the config root's <see cref="BattleBalanceConfig"/>. 26297049 added the
	/// LuckRandomness anti-streak accumulator, which makes each strike's odds depend on the previous rolls, so the
	/// histogram's luck split built from this table is the average odds, not the next strike's.
	/// </summary>
	internal static float[] CopyLuckDistributionOrDefault()
	{
		try
		{
			var balance = ReadConfigRootMember<BattleBalanceConfig>();
			var table = balance?.luckDistribution;
			if (table != null && table.Length > 0)
			{
				var copy = new float[table.Length];
				for (var i = 0; i < copy.Length; i++)
					copy[i] = table[i];
				return copy;
			}
			LogOnce(ref _loggedLuckDistributionUnresolved, "LuckCritMixture: BattleBalanceConfig.luckDistribution unresolved on "
				+ GameBuild.Describe() + "; using the 0.08..0.40 fallback table.");
		}
		catch (Exception ex)
		{
			LogOnce(ref _loggedLuckDistributionUnresolved, "LuckCritMixture: BattleBalanceConfig.luckDistribution read failed ("
				+ ex.GetType().Name + ": " + ex.Message + "); using the 0.08..0.40 fallback table.");
		}
		return (float[])DefaultLuckDistribution.Clone();
	}

	internal static bool TryGetDisableCrits()
	{
		try
		{
			var promo = ReadConfigRootMember<PromoToolsConfig>();
			if (promo != null)
				return promo.disableCrits;
			LogOnce(ref _loggedDisableCritsUnresolved, "LuckCritMixture: PromoToolsConfig.disableCrits unresolved on "
				+ GameBuild.Describe() + "; forecast assumes crits are enabled.");
		}
		catch (Exception ex)
		{
			LogOnce(ref _loggedDisableCritsUnresolved, "LuckCritMixture: PromoToolsConfig.disableCrits read failed ("
				+ ex.GetType().Name + ": " + ex.Message + "); forecast assumes crits are enabled.");
		}
		return false;
	}

	/// <summary>
	/// The config root (scoped <see cref="GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames"/> and
	/// <see cref="GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers"/>) holds exactly one instance member of each
	/// real-named config type (Golden Era, 25672315 and 26297049 indexes), so the member is picked by its type.
	/// </summary>
	private static T ReadConfigRootMember<T>() where T : class
	{
		var rootType = GameMember.FindTypeFromHints("luckCritMixture.configRoot", GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		if (rootType == null)
			return null;
		object root = null;
		const BindingFlags staticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var member in GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers)
		{
			if (string.IsNullOrEmpty(member))
				continue;
			root = rootType.GetProperty(member, staticFlags)?.GetValue(null) ?? rootType.GetField(member, staticFlags)?.GetValue(null);
			if (root != null)
				break;
		}
		if (root == null)
			return null;
		PropertyInfo match = null;
		foreach (var property in rootType.GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			if (property.PropertyType != typeof(T) || !property.CanRead || property.GetIndexParameters().Length != 0)
				continue;
			if (match != null)
				throw new InvalidOperationException("config root has more than one " + typeof(T).Name + " member (" + match.Name + ", " + property.Name + ")");
			match = property;
		}
		return match?.GetValue(root) as T;
	}

	private static void LogOnce(ref bool logged, string message)
	{
		if (logged)
			return;
		logged = true;
		Plugin.LogSource?.LogWarning(message);
	}

	/// <summary>
	/// Probability that <c>RollCritDamageMultiplier</c> returns the special multiplier (crit or anti-crit), not 1f.
	/// </summary>
	internal static float SpecialOutcomeProbability(UnitStat stats, float[] luckDistribution, bool disableCrits)
	{
		if (stats == null || disableCrits || stats.luck == 0)
		{
			return 0f;
		}

		if (luckDistribution == null || luckDistribution.Length == 0)
		{
			luckDistribution = DefaultLuckDistribution;
		}

		var idx = Mathf.Abs(stats.luck) - 1;
		idx = Mathf.Clamp(idx, 0, luckDistribution.Length - 1);
		var num = luckDistribution[idx];
		num = stats.luck <= 0
			? num + stats.anticritChanceModifier * Mathf.Abs(stats.luck)
			: num + stats.critChanceModifier * Mathf.Abs(stats.luck);

		if (num <= 0f)
		{
			return 0f;
		}

		if (num >= 1f)
		{
			return 1f;
		}

		return num;
	}

	/// <summary>
	/// Mixture: final total damage = base total × multiplier, where multiplier is 1f or the special value.
	/// </summary>
	internal static DamageDistribution.HistogramSnapshot ApplyToTotalDamageHistogram(
		DamageDistribution.HistogramSnapshot baseDamage,
		UnitStat strikerCombatStats,
		float[] luckDistribution,
		bool disableCrits)
	{
		var combined = ApplyToTotalDamageHistogramSplit(
			baseDamage,
			strikerCombatStats,
			luckDistribution,
			disableCrits,
			out _);
		return combined;
	}

	/// <param name="specialDamageOnly">Non-null (possibly empty) when <paramref name="combined"/> is non-empty and
	/// a positive special probability exists; unnormalized, sums to <c>p</c>, same support as <paramref name="combined"/>.</param>
	internal static DamageDistribution.HistogramSnapshot ApplyToTotalDamageHistogramSplit(
		DamageDistribution.HistogramSnapshot baseDamage,
		UnitStat strikerCombatStats,
		float[] luckDistribution,
		bool disableCrits,
		out DamageDistribution.HistogramSnapshot specialDamageOnly)
	{
		specialDamageOnly = new DamageDistribution.HistogramSnapshot(Array.Empty<float>(), 0, 0);
		if (baseDamage.IsEmpty || strikerCombatStats == null)
		{
			return baseDamage;
		}

		var p = SpecialOutcomeProbability(strikerCombatStats, luckDistribution, disableCrits);
		if (p <= 0f)
		{
			return baseDamage;
		}

		var luck = strikerCombatStats.luck;
		float specialMult;
		if (luck > 0)
		{
			// Audit B5: UnitStat.crit is field_Public_Single_0 on live Golden Era; read by name.
			if (!DeobfInteropCompat.TryGetSingleMember(strikerCombatStats, out var crit, GameSymbols.LiveRenamedMembers.UnitStatCrit))
			{
				if (!_loggedCritUnresolved)
				{
					_loggedCritUnresolved = true;
					Plugin.LogSource?.LogWarning("LuckCritMixture: UnitStat crit unresolved ("
						+ string.Join("/", GameSymbols.LiveRenamedMembers.UnitStatCrit) + "); forecast omits lucky-strike outcomes.");
				}
				return baseDamage;
			}
			specialMult = 1.5f + crit;
		}
		else
		{
			specialMult = 0.5f;
		}

		var minB = baseDamage.MinOutcome;
		var minO = int.MaxValue;
		var maxO = int.MinValue;

		for (var i = 0; i < baseDamage.Probabilities.Length; i++)
		{
			if (baseDamage.Probabilities[i] <= 0f)
			{
				continue;
			}

			var b = minB + i;
			var oNorm = b;
			var oSpec = Mathf.RoundToInt(b * specialMult);
			minO = Mathf.Min(minO, Mathf.Min(oNorm, oSpec));
			maxO = Mathf.Max(maxO, Mathf.Max(oNorm, oSpec));
		}

		if (minO > maxO)
		{
			return baseDamage;
		}

		var width = maxO - minO + 1;
		var acc = new float[width];
		var accSpec = new float[width];
		var q = 1f - p;

		for (var i = 0; i < baseDamage.Probabilities.Length; i++)
		{
			var pi = baseDamage.Probabilities[i];
			if (pi <= 0f)
			{
				continue;
			}

			var b = minB + i;
			acc[b - minO] += pi * q;
			var spl = Mathf.RoundToInt(b * specialMult);
			acc[spl - minO] += pi * p;
			accSpec[spl - minO] += pi * p;
		}

		specialDamageOnly = new DamageDistribution.HistogramSnapshot(
			accSpec,
			minO,
			maxO);
		return new DamageDistribution.HistogramSnapshot(
			acc,
			minO,
			maxO);
	}
}
