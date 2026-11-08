using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic bridge between exact native packet surfaces and the shared
/// no-compromise law handler registry. This does not mutate gameplay. It only
/// records whether a native hook owner can resolve active law/rank state and
/// whether the packet proof gate still denies gameplay.
/// </summary>
internal static class Homm3CustomLawHandlerTrace
{
	internal readonly struct HandlerProbe
	{
		internal readonly string HandlerKey;
		internal readonly int LawIndex;

		internal HandlerProbe(string handlerKey, int lawIndex)
		{
			HandlerKey = handlerKey;
			LawIndex = lawIndex;
		}
	}

	internal static string Describe(object owner, params HandlerProbe[] probes)
	{
		if (probes == null || probes.Length == 0)
			return "none";

		var parts = new List<string>(probes.Length);
		for (var i = 0; i < probes.Length; i++)
		{
			var probe = probes[i];
			if (Homm3CustomLawHandlerRegistry.TryEnterHandler(
				    owner,
				    probe.HandlerKey,
				    probe.LawIndex,
				    out var context,
				    out var failReason))
			{
				parts.Add(probe.HandlerKey + "=allowed:" + context + DescribeProfile(probe, context.Law.FactionSid, context.Law.Rank));
				continue;
			}

			if (Homm3CustomLawHandlerRegistry.TryProbeHandler(
				    owner,
				    probe.HandlerKey,
				    probe.LawIndex,
				    out var candidate,
				    out var candidateFailReason))
			{
				parts.Add(probe.HandlerKey + "=candidate-denied:" + candidate + DescribeProfile(probe, candidate.Law.FactionSid, candidate.Law.Rank));
				continue;
			}

			if (!string.IsNullOrEmpty(candidateFailReason))
			{
				parts.Add(probe.HandlerKey + "=denied:" + candidateFailReason + "; enterDenied=" + (failReason ?? "unknown"));
				continue;
			}

			parts.Add(probe.HandlerKey + "=denied:" + (failReason ?? "unknown"));
		}

		return "[" + string.Join("; ", parts) + "]";
	}

	private static string DescribeProfile(HandlerProbe probe, string factionSid, int rank)
	{
		if (probe.HandlerKey == "vision.reveal")
		{
			return Homm3CustomLawEffectProfiles.TryGetVisionProfile(factionSid, rank, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "damage.training")
		{
			return Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(factionSid, rank, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "counterattack.doctrine")
			return " profile=event-specific-counterattack-observation-required";
		if (probe.HandlerKey == "battle.melee-formation" || probe.HandlerKey == "battle.ranged-formation")
		{
			return Homm3CustomLawEffectProfiles.TryGetFormationProfile(factionSid, rank, probe.HandlerKey, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "construction.commit")
		{
			return Homm3CustomLawEffectProfiles.TryGetConstructionProfile(factionSid, rank, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "reward.gold-economy")
		{
			return Homm3CustomLawEffectProfiles.TryGetRewardEconomyProfile(factionSid, rank, probe.HandlerKey, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "reward.calendar")
		{
			return Homm3CustomLawEffectProfiles.TryGetCalendarProfile(factionSid, rank, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "morale.package")
		{
			return Homm3CustomLawEffectProfiles.TryGetMoralePackageProfile(factionSid, rank, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "morale.trigger")
			return " profile=event-specific-morale-roll-observation-required";
		if (probe.HandlerKey == "spell.low" || probe.HandlerKey == "spell.high")
		{
			return Homm3CustomLawEffectProfiles.TryGetSpellSchoolProfile(factionSid, rank, probe.LawIndex, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}
		if (probe.HandlerKey == "spell.cooldown")
		{
			return Homm3CustomLawEffectProfiles.TryGetSpellCooldownProfile(factionSid, rank, out var profile, out var failReason)
				? " profile={" + profile + "}"
				: " profileDenied='" + (failReason ?? "unknown") + "'";
		}

		return string.Empty;
	}

	internal static HandlerProbe VisionReveal => new(
		"vision.reveal",
		Homm3CustomFactionLawRuntime.HeroSightRadiusIndex);

	internal static HandlerProbe DamageTraining => new(
		"damage.training",
		Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex);

	internal static HandlerProbe CounterattackDoctrine => new(
		"counterattack.doctrine",
		Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex);

	internal static HandlerProbe MeleeFormation => new(
		"battle.melee-formation",
		Homm3CustomFactionLawRuntime.MeleeFormationIndex);

	internal static HandlerProbe RangedFormation => new(
		"battle.ranged-formation",
		Homm3CustomFactionLawRuntime.RangedFormationIndex);

	internal static HandlerProbe ConstructionCommit => new(
		"construction.commit",
		Homm3CustomFactionLawRuntime.ExtraConstructionIndex);

	internal static HandlerProbe RewardGoldEconomy => new(
		"reward.gold-economy",
		Homm3CustomFactionLawRuntime.GoldIncomePercentIndex);

	internal static HandlerProbe RewardCalendar => new(
		"reward.calendar",
		Homm3CustomFactionLawRuntime.AstrologyCalendarIncomeIndex);

	internal static HandlerProbe MoralePackage => new(
		"morale.package",
		Homm3CustomFactionLawRuntime.MoraleFlatIndex);

	internal static HandlerProbe MoraleTrigger => new(
		"morale.trigger",
		Homm3CustomFactionLawRuntime.MoraleTriggerIndex);

	internal static HandlerProbe SpellLow => new(
		"spell.low",
		Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex);

	internal static HandlerProbe SpellHigh => new(
		"spell.high",
		Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex);

	internal static HandlerProbe SpellCooldown => new(
		"spell.cooldown",
		Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex);
}
