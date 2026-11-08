using System;
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

	private static readonly float[] DefaultLuckDistribution = { 0.05f, 0.1f, 0.15f, 0.2f, 0.25f };

	internal static float[] CopyLuckDistributionOrDefault()
	{
		try
		{
			var elw = Type.GetType("elw, Assembly-CSharp");
			var balance = elw?.GetMethod("mma")?.Invoke(null, Array.Empty<object>());
			var il2Arr = balance?.GetType().GetField("luckDistribution")?.GetValue(balance)
			             ?? balance?.GetType().GetProperty("luckDistribution")?.GetValue(balance, null);
			var lengthObj = il2Arr?.GetType().GetProperty("Length")?.GetValue(il2Arr, null);
			var length = lengthObj == null ? 0 : Convert.ToInt32(lengthObj);
			if (il2Arr == null || length == 0)
			{
				return (float[])DefaultLuckDistribution.Clone();
			}

			var getItem = il2Arr.GetType().GetMethod("get_Item", new[] { typeof(int) });
			var n = length;
			var copy = new float[n];
			for (var i = 0; i < n; i++)
			{
				copy[i] = Convert.ToSingle(getItem.Invoke(il2Arr, new object[] { i }));
			}

			return copy;
		}
		catch
		{
			return (float[])DefaultLuckDistribution.Clone();
		}
	}

	internal static bool TryGetDisableCrits()
	{
		try
		{
			var cje = Type.GetType("cje, Assembly-CSharp");
			var root = cje?.GetMethod("rjc")?.Invoke(null, Array.Empty<object>());
			var bwsj = root?.GetType().GetField("bwtx")?.GetValue(root)
			           ?? root?.GetType().GetProperty("bwtx")?.GetValue(root, null);
			var disableCrits = bwsj?.GetType().GetField("disableCrits")?.GetValue(bwsj)
			                   ?? bwsj?.GetType().GetProperty("disableCrits")?.GetValue(bwsj, null);
			return disableCrits != null && Convert.ToBoolean(disableCrits);
		}
		catch
		{
			return false;
		}
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
