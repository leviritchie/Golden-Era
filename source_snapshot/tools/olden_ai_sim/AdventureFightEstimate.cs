using System;
using System.Collections.Generic;

namespace OldenAiSim
{
	/// <summary>
	/// PROVISIONAL army strength vs map-guard startValue.
	/// Neutrals assumed autobattle. Not fda.bjeg fidelity.
	/// </summary>
	public static class AdventureFightEstimate
	{
		public struct Outcome
		{
			public bool CanWin;
			public float PowerRatio;
			public float ExpectedLossFraction;
			public int RemainingArmyPower;
			public int RawPower;
			public int EffectivePower;
			public int RawThreat;
			public int EffectiveThreat;
			public string Summary;
		}

		public static int ArmyPower(AdventureSimHero hero)
		{
			if (hero?.Party == null || hero.Party.Count == 0)
				return 0;
			var sum = 0;
			for (var i = 0; i < hero.Party.Count; i++)
			{
				var s = hero.Party[i];
				if (s == null || s.Stacks <= 0)
					continue;
				var unit = s.UnitValue > 0 ? s.UnitValue : 1;
				sum += s.Stacks * unit;
			}
			return sum;
		}

		public static Outcome Estimate(AdventureSimHero hero, AdventureSimOccupant foe, AdventureSimKnobs knobs)
		{
			var winRatio = knobs != null && knobs.WinPowerRatio > 0f ? knobs.WinPowerRatio : 1.15f;
			var heroMult = knobs != null && knobs.HeroPowerMultiplier > 0f ? knobs.HeroPowerMultiplier : 1f;
			var mobMult = knobs != null && knobs.ValuesVsMobsMultiplier > 0f ? knobs.ValuesVsMobsMultiplier : 1f;
			return Estimate(hero, foe, winRatio, heroMult, mobMult);
		}

		public static Outcome Estimate(AdventureSimHero hero, AdventureSimOccupant foe, float winPowerRatio)
		{
			return Estimate(hero, foe, winPowerRatio, 1f, 1f);
		}

		public static Outcome Estimate(
			AdventureSimHero hero,
			AdventureSimOccupant foe,
			float winPowerRatio,
			float heroPowerMultiplier,
			float valuesVsMobsMultiplier)
		{
			var outcome = new Outcome();
			var rawPower = ArmyPower(hero);
			var rawThreat = foe != null && foe.StartValue > 0 ? foe.StartValue : 1;
			outcome.RawPower = rawPower;
			outcome.RawThreat = rawThreat;
			var power = Math.Max(0, (int)Math.Round(rawPower * heroPowerMultiplier));
			var threat = Math.Max(1, (int)Math.Round(rawThreat * valuesVsMobsMultiplier));
			outcome.EffectivePower = power;
			outcome.EffectiveThreat = threat;

			if (power <= 0)
			{
				outcome.CanWin = false;
				outcome.PowerRatio = 0f;
				outcome.ExpectedLossFraction = 1f;
				outcome.RemainingArmyPower = 0;
				outcome.Summary = "no army";
				return outcome;
			}

			var ratio = (float)power / threat;
			outcome.PowerRatio = ratio;
			var need = winPowerRatio > 0f ? winPowerRatio : 1.15f;
			outcome.CanWin = ratio >= need;
			var loss = 1f / (1f + ratio);
			if (loss < 0.05f)
				loss = 0.05f;
			if (loss > 0.85f)
				loss = 0.85f;
			if (!outcome.CanWin)
				loss = Math.Min(1f, loss + 0.25f);
			outcome.ExpectedLossFraction = loss;
			outcome.RemainingArmyPower = outcome.CanWin
				? Math.Max(1, (int)(power * (1f - loss)))
				: 0;
			outcome.Summary = "pwr=" + power + " thr=" + threat + " ratio=" + ratio.ToString("0.00")
				+ (outcome.CanWin ? " WIN" : " LOSE") + " loss=" + loss.ToString("0.00")
				+ " [provisional knobs h=" + heroPowerMultiplier.ToString("0.##")
				+ " m=" + valuesVsMobsMultiplier.ToString("0.##") + "]";
			return outcome;
		}

		public static AdventureSimFightBreakdown ToBreakdown(Outcome o, AdventureSimKnobs knobs)
		{
			return new AdventureSimFightBreakdown
			{
				Power = o.EffectivePower,
				Threat = o.EffectiveThreat,
				Ratio = o.PowerRatio,
				CanWin = o.CanWin,
				LossFraction = o.ExpectedLossFraction,
				HeroPowerMultiplier = knobs != null ? knobs.HeroPowerMultiplier : 1f,
				ValuesVsMobsMultiplier = knobs != null ? knobs.ValuesVsMobsMultiplier : 1f,
				Summary = o.Summary,
			};
		}

		public static AdventureSimHero ApplyCasualties(AdventureSimHero hero, float lossFraction)
		{
			if (hero == null)
				return null;
			var clone = CloneHeroShallow(hero);
			if (hero.Party == null)
				return clone;
			var keep = 1f - Clamp01(lossFraction);
			for (var i = 0; i < hero.Party.Count; i++)
			{
				var s = hero.Party[i];
				if (s == null)
					continue;
				var stacks = (int)Math.Floor(s.Stacks * keep);
				if (stacks <= 0)
					continue;
				clone.Party.Add(new AdventureSimStack
				{
					UnitSid = s.UnitSid,
					Stacks = stacks,
					UnitValue = s.UnitValue,
				});
			}
			return clone;
		}

		public static AdventureSimHero CloneHeroShallow(AdventureSimHero hero)
		{
			return new AdventureSimHero
			{
				HeroId = hero.HeroId,
				Name = hero.Name,
				Node = hero.Node,
				MovePoints = hero.MovePoints,
				MaxMovePoints = hero.MaxMovePoints,
				Mana = hero.Mana,
				Party = new List<AdventureSimStack>(),
			};
		}

		private static float Clamp01(float v)
		{
			if (v < 0f)
				return 0f;
			if (v > 1f)
				return 1f;
			return v;
		}
	}
}
