using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class DamageDistribution
{
	internal readonly struct ForecastValues
	{
		public readonly int DamageMin;
		public readonly int DamageMax;
		public readonly int KillMin;
		public readonly int KillMax;

		public ForecastValues(int damageMin, int damageMax, int killMin, int killMax)
		{
			DamageMin = damageMin;
			DamageMax = damageMax;
			KillMin = killMin;
			KillMax = killMax;
		}
	}

	internal static class ForecastReader
	{
		private sealed class Accessors
		{
			public MemberAccessor DamageMin;
			public MemberAccessor DamageMax;
			public MemberAccessor KillMin;
			public MemberAccessor KillMax;
		}

		private sealed class MemberAccessor
		{
			public FieldInfo Field;
			public PropertyInfo Property;

			public object GetValue(object target)
			{
				if (Field != null)
				{
					return Field.GetValue(target);
				}
				return Property?.GetValue(target, null);
			}
		}

		private static readonly Dictionary<Type, Accessors> Cache = new();

		internal static bool TryRead(object forecast, out ForecastValues values)
		{
			values = default;
			if (forecast == null)
			{
				return false;
			}

			var type = forecast.GetType();
			if (!Cache.TryGetValue(type, out var accessors))
			{
				accessors = ResolveAccessors(type);
				Cache[type] = accessors;
			}
			if (accessors?.DamageMin == null || accessors.DamageMax == null || accessors.KillMin == null || accessors.KillMax == null)
			{
				return false;
			}

			try
			{
				values = new ForecastValues(
					Convert.ToInt32(accessors.DamageMin.GetValue(forecast)),
					Convert.ToInt32(accessors.DamageMax.GetValue(forecast)),
					Convert.ToInt32(accessors.KillMin.GetValue(forecast)),
					Convert.ToInt32(accessors.KillMax.GetValue(forecast)));
				return true;
			}
			catch
			{
				return false;
			}
		}

		internal static bool CanResolveType(Type type)
		{
			return type != null && ResolveAccessors(type) != null;
		}

		private static Accessors ResolveAccessors(Type type)
		{
			foreach (var group in GameSymbols.DamageForecast.FieldGroups)
			{
				var accessors = ResolveByNames(type, group);
				if (accessors != null)
					return accessors;
			}
			return null;
		}

		private static Accessors ResolveByNames(Type type, string[] names)
		{
			if (names == null || names.Length < 4)
				return null;
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var a = ResolveMember(type, names[0], flags);
			var b = ResolveMember(type, names[1], flags);
			var c = ResolveMember(type, names[2], flags);
			var d = ResolveMember(type, names[3], flags);
			if (a == null || b == null || c == null || d == null)
			{
				return null;
			}
			return new Accessors { DamageMin = a, DamageMax = b, KillMin = c, KillMax = d };
		}

		private static MemberAccessor ResolveMember(Type type, string name, BindingFlags flags)
		{
			var field = type.GetField(name, flags);
			if (field != null)
			{
				return new MemberAccessor { Field = field };
			}
			var property = type.GetProperty(name, flags);
			return property != null && property.GetIndexParameters().Length == 0
				? new MemberAccessor { Property = property }
				: null;
		}
	}

	internal sealed class HistogramSnapshot
	{
		public readonly float[] Probabilities;
		public readonly int MinOutcome;
		public readonly int MaxOutcome;

		/// <summary>Per bar: share of that kill count's probability mass that came from the luck/crit special
		/// total-damage branch. Same length as <see cref="Probabilities"/>, or null (no crit/luck in model).</summary>
		public readonly float[] LuckSharePerBin;

		public HistogramSnapshot(float[] probabilities, int minOutcome, int maxOutcome, float[] luckSharePerBin = null)
		{
			Probabilities = probabilities;
			MinOutcome = minOutcome;
			MaxOutcome = maxOutcome;
			LuckSharePerBin = luckSharePerBin;
		}

		internal bool IsEmpty => Probabilities == null || Probabilities.Length == 0;
	}

	internal sealed class DamageReceiverContext
	{
		internal readonly object NativeTarget;
		internal readonly object UnitDataOwner;
		internal readonly int DtoKillMin;
		internal readonly int DtoKillMax;
		internal DamageKillMapping.KillCapInfo CapInfo;

		internal DamageReceiverContext(object nativeTarget, object unitDataOwner, ForecastValues forecastValues)
		{
			NativeTarget = nativeTarget;
			UnitDataOwner = unitDataOwner;
			DtoKillMin = forecastValues.KillMin;
			DtoKillMax = forecastValues.KillMax;
		}
	}

	/// <summary>
	/// Keep only [first..last] with positive mass so the histogram X-axis does not start at 0
	/// when the PMF is 0 for low kill counts.
	/// </summary>
	internal static HistogramSnapshot TrimToNonZeroSupport(
		HistogramSnapshot h,
		float euo = 1E-7f
	)
	{
		if (h.IsEmpty
		    || h.Probabilities == null)
		{
			return h;
		}
		var p = h.Probabilities;
		var n = p.Length;
		var lo = 0;
		var hi = n - 1;
		while (lo <= hi
		       && p[lo] <= euo)
		{
			lo++;
		}
		while (hi >= lo
		       && p[hi] <= euo)
		{
			hi--;
		}
		if (lo > hi)
		{
			return new HistogramSnapshot(
				Array.Empty<float>(),
				0,
				0
			);
		}
		var m = hi - lo + 1;
		var q = new float[m];
		Array.Copy(
			p,
			lo,
			q,
			0,
			m
		);
		float[] qLuck = null;
		if (h.LuckSharePerBin != null
		    && h.LuckSharePerBin.Length == p.Length)
		{
			qLuck = new float[m];
			Array.Copy(
				h.LuckSharePerBin,
				lo,
				qLuck,
				0,
				m
			);
		}
		var newMin = h.MinOutcome + lo;
		return new HistogramSnapshot(
			q,
			newMin,
			newMin + m - 1,
			qLuck
		);
	}

	/// <summary>
	/// Maps total damage to kills. Base damage PMF follows HoMM3-style per-creature rolls (see <c>HOMM3_damage_rolls.md</c>).
	/// </summary>
	internal static HistogramSnapshot BuildDamageHistogram(
		object forecast,
		int strikerStackCount,
		int convolutionMaxUnits,
		UnitStat strikerCombatStats,
		float[] luckDistribution,
		bool disableCrits)
	{
		if (forecast == null || strikerStackCount <= 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		if (!ForecastReader.TryRead(forecast, out var values)
		    || values.DamageMin < 0
		    || values.DamageMax < values.DamageMin)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var baseDamage = Homm3BaseDamageHistogram(
			values.DamageMin,
			values.DamageMax,
			strikerStackCount,
			convolutionMaxUnits);
		if (baseDamage.IsEmpty)
		{
			return baseDamage;
		}

		var combined = LuckCritMixture.ApplyToTotalDamageHistogramSplit(
			baseDamage,
			strikerCombatStats,
			luckDistribution,
			disableCrits,
			out var specialDamage);
		return AttachSpecialShare(combined, specialDamage);
	}

	internal static HistogramSnapshot BuildKillHistogram(
		object forecast,
		int strikerStackCount,
		int receiverStackCount,
		int convolutionMaxUnits,
		UnitStat strikerCombatStats,
		float[] luckDistribution,
		bool disableCrits,
		object damageReceiver = null)
	{
		if (forecast == null || strikerStackCount <= 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		if (!ForecastReader.TryRead(forecast, out var values)
		    || values.DamageMin < 0
		    || values.DamageMax < values.DamageMin)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var capInfo = ResolveKillCap(values, damageReceiver, receiverStackCount);
		var receiverCap = capInfo != null && capInfo.IsDefensible
			? capInfo.SelectedCap
			: receiverStackCount;
		if (receiverCap < 0 || (receiverCap == 0 && values.KillMax > 0))
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		ResolveKillHints(values, damageReceiver, capInfo, out var kMin, out var kMax);
		return BuildKillHistogramCore(
			values.DamageMin,
			values.DamageMax,
			kMin,
			kMax,
			strikerStackCount,
			receiverCap,
			convolutionMaxUnits,
			strikerCombatStats,
			luckDistribution,
			disableCrits,
			damageReceiver);
	}

	private static HistogramSnapshot AttachSpecialShare(HistogramSnapshot combined, HistogramSnapshot special)
	{
		if (combined.IsEmpty
		    || special == null
		    || special.IsEmpty
		    || combined.Probabilities == null
		    || special.Probabilities == null)
		{
			return combined;
		}

		var share = new float[combined.Probabilities.Length];
		for (var i = 0; i < share.Length; i++)
		{
			var outcome = combined.MinOutcome + i;
			var specialIdx = outcome - special.MinOutcome;
			if ((uint)specialIdx >= (uint)special.Probabilities.Length
			    || combined.Probabilities[i] <= 1e-20f)
			{
				continue;
			}
			share[i] = Mathf.Clamp01(special.Probabilities[specialIdx] / combined.Probabilities[i]);
		}

		return new HistogramSnapshot(
			combined.Probabilities,
			combined.MinOutcome,
			combined.MaxOutcome,
			share);
	}

	internal static HistogramSnapshot BuildMarginalizedRetaliationKillHistogram(
		object forwardForecast,
		object retalForecast,
		int defenderStack,
		int attackerStack,
		int convolutionMaxUnits,
		UnitStat attackerCombatStats,
		UnitStat defenderCombatStats,
		float[] luckDistribution,
		bool disableCrits,
		object defenderUnit = null,
		object attackerUnit = null)
	{
		if (forwardForecast == null || retalForecast == null || defenderStack <= 0 || attackerStack <= 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var forwardOnDefender = BuildKillHistogram(
			forwardForecast,
			attackerStack,
			defenderStack,
			convolutionMaxUnits,
			attackerCombatStats,
			luckDistribution,
			disableCrits,
			defenderUnit);
		if (forwardOnDefender.IsEmpty)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var attackerReceiverCap = attackerStack;
		if (attackerUnit is DamageReceiverContext attackerContext
		    && attackerContext.CapInfo != null
		    && attackerContext.CapInfo.IsDefensible)
		{
			attackerReceiverCap = attackerContext.CapInfo.SelectedCap;
		}

		var maxKIndex = Mathf.Min(forwardOnDefender.Probabilities.Length - 1, defenderStack);
		var maxAggKills = Mathf.Min(attackerReceiverCap, 511);
		var agg = new float[maxAggKills + 1];
		var aggLuckNum = new float[maxAggKills + 1];
		var any = false;

		for (var k = 0; k <= maxKIndex; k++)
		{
			var p = forwardOnDefender.Probabilities[k];
			if (p <= 1e-15f)
			{
				continue;
			}

			var surv = defenderStack - k;
			if (surv <= 0)
			{
				continue;
			}

			var scale = surv / (float)defenderStack;
			if (!ForecastReader.TryRead(retalForecast, out var retalValues))
			{
				return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
			}
			var tMin = Mathf.RoundToInt(retalValues.DamageMin * scale);
			var tMax = Mathf.RoundToInt(retalValues.DamageMax * scale);
			if (tMax < tMin)
			{
				(tMin, tMax) = (tMax, tMin);
			}

			var kMinS = Mathf.RoundToInt(retalValues.KillMin * scale);
			var kMaxS = Mathf.RoundToInt(retalValues.KillMax * scale);

			var branch = BuildKillHistogramCore(
				tMin,
				tMax,
				kMinS,
				kMaxS,
				surv,
				attackerReceiverCap,
				convolutionMaxUnits,
				defenderCombatStats,
				luckDistribution,
				disableCrits,
				attackerUnit);
			if (branch.IsEmpty)
			{
				continue;
			}

			AddWeightedKillPmf(
				agg,
				aggLuckNum,
				branch,
				p);
			any = true;
		}

		if (!any)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var luckOut = new float[agg.Length];
		for (var j = 0; j < agg.Length; j++)
		{
			if (agg[j] > 1e-20f)
			{
				luckOut[j] = Mathf.Clamp01(aggLuckNum[j] / agg[j]);
			}
		}

		NormalizeInPlace(agg);
		return new HistogramSnapshot(
			agg,
			0,
			agg.Length - 1,
			luckOut);
	}

	internal static DamageKillMapping.KillCapInfo ResolveKillCap(
		ForecastValues values,
		object damageReceiver,
		int receiverStackHint)
	{
		var context = damageReceiver as DamageReceiverContext;
		if (context?.CapInfo != null)
		{
			return context.CapInfo;
		}

		var nativeTarget = context != null ? context.NativeTarget : damageReceiver;
		var unitDataOwner = context != null ? context.UnitDataOwner : damageReceiver;
		var capInfo = DamageKillMapping.ResolveKillCap(
			values.DamageMin,
			values.DamageMax,
			values.KillMin,
			values.KillMax,
			nativeTarget,
			unitDataOwner,
			receiverStackHint);
		if (context != null)
		{
			context.CapInfo = capInfo;
		}
		return capInfo;
	}

	private static void ResolveKillHints(
		ForecastValues values,
		object damageReceiver,
		DamageKillMapping.KillCapInfo capInfo,
		out int kMin,
		out int kMax)
	{
		kMin = Mathf.Max(0, values.KillMin);
		kMax = Mathf.Max(kMin, values.KillMax);
		if (capInfo == null)
		{
			return;
		}

		if (capInfo.HasUsableUnitDataKills
		    && (capInfo.NativeConflictsWithDto || !capInfo.HasUsableNativeKills))
		{
			kMin = capInfo.UnitDataKillMin;
			kMax = capInfo.UnitDataKillMax;
		}
		else if (capInfo.HasUsableNativeKills)
		{
			kMin = capInfo.NativeKillMin;
			kMax = capInfo.NativeKillMax;
		}
		else if (capInfo.HasUsableUnitDataKills)
		{
			kMin = capInfo.UnitDataKillMin;
			kMax = capInfo.UnitDataKillMax;
		}

		kMin = Mathf.Max(0, kMin);
		kMax = Mathf.Max(kMin, Mathf.Max(kMax, values.KillMax));
	}

	private static bool ResolveDamageInputs(
		object forecast,
		object damageReceiver,
		out int dMin,
		out int dMax,
		out int kMinHint,
		out int kMaxHint)
	{
		dMin = 0;
		dMax = -1;
		kMinHint = 0;
		kMaxHint = 0;
		if (!ForecastReader.TryRead(forecast, out var values))
		{
			return false;
		}
		dMin = values.DamageMin;
		dMax = values.DamageMax;
		if (damageReceiver != null)
		{
			if (DamageKillMapping.TryGetKilledStacksFromGameRules(dMin, damageReceiver, out var kMin)
			    && DamageKillMapping.TryGetKilledStacksFromGameRules(dMax, damageReceiver, out var kMax))
			{
				kMinHint = kMin;
				kMaxHint = kMax;
				return true;
			}
		}

		kMinHint = values.KillMin;
		kMaxHint = values.KillMax;
		return true;
	}

	private static HistogramSnapshot BuildKillHistogramCore(
		int dMin,
		int dMax,
		int kMin,
		int kMax,
		int strikerStackCount,
		int receiverStackCount,
		int convolutionMaxUnits,
		UnitStat strikerCombatStats,
		float[] luckDistribution,
		bool disableCrits,
		object damageReceiver = null)
	{
		if (dMin < 0 || dMax < dMin)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var hpEst = EstimateHpPerCreature(dMin, dMax, kMin, kMax);
		if (hpEst < 1f)
		{
			hpEst = 1f;
		}

		var dmgHist = Homm3BaseDamageHistogram(dMin, dMax, strikerStackCount, convolutionMaxUnits);
		if (dmgHist.IsEmpty)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var afterLuck = LuckCritMixture.ApplyToTotalDamageHistogramSplit(
			dmgHist,
			strikerCombatStats,
			luckDistribution,
			disableCrits,
			out var specialDmg);
		var withSpecial = !specialDmg.IsEmpty
			&& specialDmg.Probabilities != null
			&& specialDmg.Probabilities.Length == afterLuck.Probabilities.Length
			&& specialDmg.MinOutcome == afterLuck.MinOutcome
			&& specialDmg.MaxOutcome == afterLuck.MaxOutcome;
		return MapTotalDamageToKillHistogram(
			afterLuck,
			withSpecial ? specialDmg : null,
			hpEst,
			kMin,
			kMax,
			receiverStackCount,
			damageReceiver);
	}

	private static HistogramSnapshot MapTotalDamageToKillHistogram(
		HistogramSnapshot dmgHist,
		HistogramSnapshot specialDmg,
		float hpEst,
		int kMinHint,
		int kMaxHint,
		int receiverStackCount,
		object damageReceiver = null)
	{
		var receiverCap = Mathf.Clamp(receiverStackCount, 0, 511);
		var maxKillIdx = Mathf.Max(Mathf.Max(kMaxHint, receiverCap), 0);
		var killBuckets = Mathf.Clamp(maxKillIdx + 1, 1, 512);
		var killPmf = new float[killBuckets];
		var mapSpec = specialDmg != null
			&& !specialDmg.IsEmpty
			&& specialDmg.Probabilities != null
			&& specialDmg.Probabilities.Length == dmgHist.Probabilities.Length
			&& specialDmg.MinOutcome == dmgHist.MinOutcome;
		var specPmf = mapSpec
			? new float[killBuckets]
			: null;

		for (var i = 0; i < dmgHist.Probabilities.Length; i++)
		{
			var p = dmgHist.Probabilities[i];
			var pS = specPmf != null
				? specialDmg.Probabilities[i]
				: 0f;
			if (p <= 0f
			    && pS <= 0f)
			{
				continue;
			}

			var dmg = dmgHist.MinOutcome + i;
			var kills = MapDamageToKills(dmg, hpEst, dmgHist.MinOutcome, dmgHist.MaxOutcome, kMinHint, kMaxHint, damageReceiver);

			kills = Mathf.Clamp(kills, 0, Mathf.Min(receiverCap, killBuckets - 1));
			killPmf[kills] += p;
			if (specPmf != null)
			{
				specPmf[kills] += pS;
			}
		}

		float[] luckShare = null;
		if (specPmf != null)
		{
			luckShare = new float[killBuckets];
			for (var j = 0; j < killBuckets; j++)
			{
				if (killPmf[j] > 1e-20f)
				{
					luckShare[j] = Mathf.Clamp01(specPmf[j] / killPmf[j]);
				}
			}
		}

		return new HistogramSnapshot(
			killPmf,
			0,
			killBuckets - 1,
			luckShare);
	}

	private static int MapDamageToKills(
		int dmg,
		float hpEst,
		int dMinHint,
		int dMaxHint,
		int kMinHint,
		int kMaxHint,
		object damageReceiver)
	{
		var context = damageReceiver as DamageReceiverContext;
		if (context != null
		    && context.CapInfo != null
		    && context.CapInfo.HasUsableUnitDataKills
		    && (context.CapInfo.NativeConflictsWithDto || !context.CapInfo.HasUsableNativeKills)
		    && DamageKillMapping.TryGetKilledStacksFromUnitDataRules(dmg, context.UnitDataOwner, out var unitDataPreferred))
		{
			return unitDataPreferred;
		}

		var nativeTarget = context != null ? context.NativeTarget : damageReceiver;
		if (nativeTarget != null
		    && (context == null || context.CapInfo == null || context.CapInfo.HasUsableNativeKills)
		    && DamageKillMapping.TryGetKilledStacksFromGameRules(dmg, nativeTarget, out var nativeKills))
		{
			return nativeKills;
		}

		var unitDataOwner = context != null ? context.UnitDataOwner : damageReceiver;
		if (unitDataOwner != null
		    && (context == null || context.CapInfo == null || context.CapInfo.HasUsableUnitDataKills)
		    && DamageKillMapping.TryGetKilledStacksFromUnitDataRules(dmg, unitDataOwner, out var unitDataKills))
		{
			return unitDataKills;
		}

		if (kMaxHint >= kMinHint && kMaxHint > 0 && dMaxHint > dMinHint)
		{
			var t = Mathf.Clamp01((dmg - dMinHint) / (float)(dMaxHint - dMinHint));
			return Mathf.RoundToInt(Mathf.Lerp(kMinHint, kMaxHint, t));
		}

		return Mathf.FloorToInt(dmg / hpEst);
	}

	private static void AddWeightedKillPmf(float[] acc, float[] accLuckNum, HistogramSnapshot branch, float weight)
	{
		if (branch.IsEmpty || weight <= 0f)
		{
			return;
		}

		var offset = branch.MinOutcome;
		for (var i = 0; i < branch.Probabilities.Length; i++)
		{
			var p = branch.Probabilities[i];
			if (p <= 0f)
			{
				continue;
			}

			var idx = offset + i;
			if ((uint)idx < (uint)acc.Length)
			{
				acc[idx] += weight * p;
				if (accLuckNum != null
				    && accLuckNum.Length == acc.Length
				    && branch.LuckSharePerBin != null
				    && i < branch.LuckSharePerBin.Length)
				{
					accLuckNum[idx] += weight * p * branch.LuckSharePerBin[i];
				}
			}
		}
	}

	private static void NormalizeInPlace(float[] probs)
	{
		var s = 0f;
		for (var i = 0; i < probs.Length; i++)
		{
			s += probs[i];
		}

		if (s <= 1e-20f)
		{
			return;
		}

		for (var i = 0; i < probs.Length; i++)
		{
			probs[i] /= s;
		}
	}

	private static float EstimateHpPerCreature(int dMin, int dMax, int kMin, int kMax)
	{
		if (kMin > 0)
		{
			return Mathf.Max(1f, (float)dMin / kMin);
		}

		if (kMax > 0)
		{
			return Mathf.Max(1f, (float)dMax / kMax);
		}

		var midD = (dMin + dMax) * 0.5f;
		return Mathf.Max(1f, midD / Mathf.Max((kMin + kMax + 1) * 0.5f, 1f));
	}

	/// <summary>
	/// HoMM3 base damage: N≤10 → sum of N i.i.d. discrete uniforms per creature; N&gt;10 → sum of 10 uniforms, scaled by <c>(sum * N) / 10</c>.
	/// <para/>
	/// <c>lo</c> = floor of min total / N, <c>hi</c> = ceil of max total / N so a single i.i.d. [lo,hi] can reach the game’s
	/// max total, then the result PMF is <see cref="ClipPmfToEngineRange"/>-clipped to the engine interval <c>[totalMin,totalMax]</c>
	/// (avoids mass below/above the tooltip and fixes off-by-ones from two floor-division mistakes).
	/// </summary>
	private static HistogramSnapshot Homm3BaseDamageHistogram(
		int totalMin,
		int totalMax,
		int stackCount,
		int convolutionMaxUnits)
	{
		if (stackCount <= 0 || totalMax < totalMin)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		// If both endpoints divide exactly, the classic [lo,hi] = [min/N, max/N] matches engine bounds. Otherwise floored
		// "hi" is too small (N*hi < max total); use ceil for upper per-creature bound, then renormalize after clipping to engine range.
		var lo = totalMin / stackCount;
		var hi = (totalMax + stackCount - 1) / stackCount;
		if (hi < lo)
		{
			(hi, lo) = (lo, hi);
		}

		if (hi < lo || lo < 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		HistogramSnapshot raw;
		if (stackCount <= 10)
		{
			if (stackCount <= convolutionMaxUnits)
			{
				raw = ConvolveDiscreteUniform(stackCount, lo, hi);
			}
			else
			{
				raw = NormalApproxSum(stackCount, lo, hi);
			}
		}
		else
		{
			if (10 <= convolutionMaxUnits)
			{
				raw = ConvolveDiscreteUniform(10, lo, hi);
			}
			else
			{
				raw = NormalApproxSum(10, lo, hi);
			}

			raw = ScaleTenRollSumToStack(raw, stackCount);
		}

		return ClipPmfToEngineRange(raw, totalMin, totalMax);
	}

	/// <summary>
	/// Restricts a total-damage PMF to the engine’s min/max. If the model put no mass on the interval, falls back to a flat
	/// distribution on every integer in <c>[dMin, dMax]</c>.
	/// </summary>
	private static HistogramSnapshot ClipPmfToEngineRange(HistogramSnapshot h, int dMin, int dMax)
	{
		if (h.IsEmpty || dMax < dMin)
		{
			return h;
		}

		var width = dMax - dMin + 1;
		var acc = new float[width];
		for (var i = 0; i < h.Probabilities.Length; i++)
		{
			var p = h.Probabilities[i];
			if (p <= 0f)
			{
				continue;
			}

			var v = h.MinOutcome + i;
			if (v < dMin || v > dMax)
			{
				continue;
			}

			acc[v - dMin] += p;
		}

		var s = 0f;
		for (var j = 0; j < width; j++)
		{
			s += acc[j];
		}

		if (s <= 1e-20f)
		{
			return UniformIntRangeHistogram(dMin, dMax);
		}

		for (var j = 0; j < width; j++)
		{
			acc[j] /= s;
		}

		return new HistogramSnapshot(acc, dMin, dMax);
	}

	private static HistogramSnapshot UniformIntRangeHistogram(int dMin, int dMax)
	{
		if (dMax < dMin)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var w = dMax - dMin + 1;
		var p = 1f / w;
		var probs = new float[w];
		for (var i = 0; i < w; i++)
		{
			probs[i] = p;
		}

		return new HistogramSnapshot(probs, dMin, dMax);
	}

	/// <summary>Maps PMF of T (sum of 10 rolls) to floor(T·N/10) per HoMM3 large-stack rule.</summary>
	private static HistogramSnapshot ScaleTenRollSumToStack(HistogramSnapshot s10, int stackCount)
	{
		if (s10.IsEmpty || stackCount <= 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var acc = new Dictionary<int, float>();
		for (var i = 0; i < s10.Probabilities.Length; i++)
		{
			var p = s10.Probabilities[i];
			if (p <= 0f)
			{
				continue;
			}

			var t = s10.MinOutcome + i;
			var dmg = (t * stackCount) / 10;
			if (!acc.TryGetValue(dmg, out var cur))
			{
				cur = 0f;
			}

			acc[dmg] = cur + p;
		}

		if (acc.Count == 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var minD = int.MaxValue;
		var maxD = int.MinValue;
		foreach (var k in acc.Keys)
		{
			minD = Mathf.Min(minD, k);
			maxD = Mathf.Max(maxD, k);
		}

		var width = maxD - minD + 1;
		var probs = new float[width];
		foreach (var kv in acc)
		{
			probs[kv.Key - minD] = kv.Value;
		}

		return new HistogramSnapshot(probs, minD, maxD);
	}

	private static HistogramSnapshot ConvolveDiscreteUniform(int n, int lo, int hi)
	{
		var span = hi - lo + 1;
		if (span <= 0 || n <= 0)
		{
			return new HistogramSnapshot(Array.Empty<float>(), 0, 0);
		}

		var baseProb = 1f / span;
		var pmf = new float[span];
		for (var i = 0; i < span; i++)
		{
			pmf[i] = baseProb;
		}

		for (var step = 1; step < n; step++)
		{
			var newLen = pmf.Length + span - 1;
			var next = new float[newLen];
			for (var i = 0; i < pmf.Length; i++)
			{
				var pi = pmf[i];
				if (pi <= 0f)
				{
					continue;
				}

				for (var k = 0; k < span; k++)
				{
					next[i + k] += pi * baseProb;
				}
			}

			pmf = next;
		}

		var minOutcome = n * lo;
		return new HistogramSnapshot(pmf, minOutcome, minOutcome + pmf.Length - 1);
	}

	private static HistogramSnapshot NormalApproxSum(int n, int lo, int hi)
	{
		var mean = (float)n * (lo + hi) * 0.5f;
		var range = hi - lo + 1;
		var variance = n * ((range * range - 1f) / 12f);
		var sigma = Mathf.Sqrt(Mathf.Max(variance, 1e-3f));
		var minSum = lo * n;
		var maxSum = hi * n;
		var width = maxSum - minSum + 1;
		width = Mathf.Clamp(width, 3, 800);

		var probs = new float[width];
		var sum = 0f;
		for (var i = 0; i < width; i++)
		{
			var x = minSum + i;
			var z = (x - mean) / sigma;
			var p = Mathf.Exp(-0.5f * z * z);
			probs[i] = p;
			sum += p;
		}

		if (sum <= 0f)
		{
			probs[width / 2] = 1f;
			sum = 1f;
		}

		for (var i = 0; i < width; i++)
		{
			probs[i] /= sum;
		}

		return new HistogramSnapshot(probs, minSum, maxSum);
	}
}
