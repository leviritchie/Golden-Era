using System.Text;
using Hex.Configs;

namespace OfflineUnlockMod;

/// <summary>
/// Human-readable catalog for source-prepared no-compromise custom law seams.
/// This is diagnostic metadata only. It does not resolve adapters, register
/// hooks, promote packet proofs, or authorize gameplay.
/// </summary>
internal static class Homm3CustomLawImplementationCatalog
{
	private static readonly string[] Factions =
	{
		Homm3CustomLawEffectProfiles.Castle,
		Homm3CustomLawEffectProfiles.Cove,
		Homm3CustomLawEffectProfiles.Dungeon,
		Homm3CustomLawEffectProfiles.Fortress,
		Homm3CustomLawEffectProfiles.Rampart,
		Homm3CustomLawEffectProfiles.Tower,
		Homm3CustomLawEffectProfiles.Conflux,
		Homm3CustomLawEffectProfiles.Inferno,
		Homm3CustomLawEffectProfiles.Necropolis,
		Homm3CustomLawEffectProfiles.Stronghold,
	};

	private readonly struct Row
	{
		internal readonly string Packet;
		internal readonly string Handler;
		internal readonly string Adapter;
		internal readonly string Runtime;
		internal readonly string Boundary;

		internal Row(string packet, string handler, string adapter, string runtime, string boundary)
		{
			Packet = packet;
			Handler = handler;
			Adapter = adapter;
			Runtime = runtime;
			Boundary = boundary;
		}
	}

	private static readonly Row[] Rows =
	{
		new(
			Homm3CustomLawPacketGate.Vision,
			"vision.reveal",
			nameof(Homm3AdventureVisionNativeAdapter),
			nameof(Homm3CustomVisionLawRuntime) + "/" + nameof(Homm3CustomLawIdempotenceRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"object scouting with data-object identity/idempotence gates plus source-prepared faction vision profiles only; fog tile mutation, object classification, neutral threat data, and map refresh unproven"),
		new(
			Homm3CustomLawPacketGate.Construction,
			"construction.commit",
			nameof(Homm3ConstructionNativeAdapter),
			nameof(Homm3CustomConstructionLawRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"native daily-count/state operations plus exact fbs city logic to BuildingsData, owner-side law resolution, and source-prepared faction construction profiles; commit/charge ordering and cost parity unproven"),
		new(
			Homm3CustomLawPacketGate.RewardResult,
			"reward.gold-economy/reward.calendar",
			nameof(Homm3RewardEconomyNativeAdapter),
			nameof(Homm3CustomRewardEconomyLawRuntime) + "/" + nameof(Homm3CustomLawIdempotenceRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"gold-only resource mutation plus active-law data-side Side.res/ResHeap.gold resolution, reward-set identity/idempotence gates, and source-prepared faction economy/calendar profiles; reward commit, day-start idempotence, Astrology mutation, and event ordering unproven"),
		new(
			Homm3CustomLawPacketGate.Morale,
			"morale.package/morale.trigger",
			nameof(Homm3MoraleTriggerNativeAdapter) + "/" + nameof(Homm3BuffDebuffNativeAdapter),
			nameof(Homm3CustomMoraleLawRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"flat morale package profiles plus roll classification, exact unit-derived law-owner gates, expanded 210-SID custom unit-family registry, and source-prepared faction trigger profiles only; native morale stat mutation, trigger/check/action ordering, and action queue behavior unproven"),
		new(
			Homm3CustomLawPacketGate.CommittedDamage,
			"damage.training",
			nameof(Homm3BattleEventNativeAdapter) + "/" + nameof(Homm3BuffDebuffNativeAdapter) + "/" + nameof(Homm3UnitLawClassifier),
			nameof(Homm3CustomBattleEventLawRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"damage payload reads plus exact dealer-derived law-owner, expanded 210-SID custom unit-family registry, buff gates, and source-prepared faction training profiles only; final damage ordering unproven"),
		new(
			Homm3CustomLawPacketGate.BattleAction,
			"battle.melee-formation/battle.ranged-formation",
			nameof(Homm3BattleEventNativeAdapter) + "/" + nameof(Homm3BuffDebuffNativeAdapter) + "/" + nameof(Homm3UnitLawClassifier),
			nameof(Homm3CustomBattleEventLawRuntime) + "/" + nameof(Homm3CustomBuffDebuffLawRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"cast/movement payload reads plus exact caster-derived law-owner, expanded 210-SID custom caster-family registry, first-round, target-count, buff gates, and source-prepared faction formation profiles only; action ordering/effect mutation unproven"),
		new(
			Homm3CustomLawPacketGate.Counterattack,
			"counterattack.doctrine",
			nameof(Homm3BattleEventNativeAdapter) + "/" + nameof(Homm3FocusNativeAdapter) + "/" + nameof(Homm3BuffDebuffNativeAdapter) + "/" + nameof(Homm3UnitLawClassifier),
			nameof(Homm3CustomCounterattackLawRuntime) + "/" + nameof(Homm3CustomFocusLawRuntime) + "/" + nameof(Homm3CustomBuffDebuffLawRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"requires native EAbilityType.CounterAttack and counterattacking battle object supplied by exact hook; derives law owner through FieldObject.basa, and Focus event-side/expanded 210-SID unit-family/buff gates plus source-prepared faction effect profiles fail closed"),
		new(
			Homm3CustomLawPacketGate.SpellCooldown,
			"spell.low/spell.high/spell.cooldown",
			nameof(Homm3SpellCooldownNativeAdapter) + "/" + nameof(Homm3SpellCastGateNativeAdapter) + "/" + nameof(Homm3SpellIdentityNativeAdapter) + "/" + nameof(Homm3FocusNativeAdapter) + "/" + nameof(Homm3BuffDebuffNativeAdapter),
			nameof(Homm3CustomSpellSchoolLawRuntime) + "/" + nameof(Homm3CustomSpellCooldownLawRuntime) + "/" + nameof(Homm3CustomFocusLawRuntime) + "/" + nameof(Homm3CustomBuffDebuffLawRuntime) + "/" + nameof(Homm3CustomLawEffectProfiles),
			"cooldown/gate/spell-identity/focus reads plus exact eex spell-pool enumeration, caster-derived spell-pool ownership, Focus event-side ownership, and source-prepared school/cooldown profiles; spellbook access mutation, cast ordering, and UI synchronization unproven"),
	};

	internal static string Describe()
	{
		var sb = new StringBuilder();
		for (var i = 0; i < Rows.Length; i++)
		{
			var row = Rows[i];
			if (i > 0)
				sb.Append("; ");
			sb.Append("packet='").Append(row.Packet)
				.Append("' handler='").Append(row.Handler)
				.Append("' adapter='").Append(row.Adapter)
				.Append("' runtime='").Append(row.Runtime)
				.Append("' boundary='").Append(row.Boundary)
				.Append("'");
		}
		return sb.ToString();
	}

	internal static string DescribeSourcePreparedProfiles(string factionSid, int rank)
	{
		var sb = new StringBuilder();
		AppendSourcePreparedProfiles(sb, factionSid, rank);
		return sb.ToString();
	}

	internal static string DescribeSourcePreparedProfileCatalog()
	{
		var sb = new StringBuilder();
		var lines = DescribeSourcePreparedProfileCatalogLines();
		for (var i = 0; i < lines.Length; i++)
		{
			if (i > 0)
				sb.Append("; ");
			sb.Append(lines[i]);
		}
		return sb.ToString();
	}

	internal static string[] DescribeSourcePreparedProfileCatalogLines()
	{
		var lines = new string[Factions.Length * 3];
		var index = 0;
		for (var f = 0; f < Factions.Length; f++)
		{
			for (var rank = 1; rank <= 3; rank++)
				lines[index++] = DescribeSourcePreparedProfiles(Factions[f], rank);
		}
		return lines;
	}

	private static void AppendSourcePreparedProfiles(StringBuilder sb, string factionSid, int rank)
	{
		sb.Append("faction='").Append(factionSid ?? "null").Append("' rank=").Append(rank);
		AppendProfile(sb, "vision.reveal", Homm3CustomLawEffectProfiles.TryGetVisionProfile(factionSid, rank, out var vision, out var visionFail), vision.ToString(), visionFail);
		AppendProfile(sb, "damage.training", Homm3CustomLawEffectProfiles.TryGetTrainingDamageProfile(factionSid, rank, out var training, out var trainingFail), training.ToString(), trainingFail);
		var counterObservation = new Homm3CustomCounterattackLawRuntime.CounterattackAbilityObservation(null, EAbilityType.CounterAttack, -1);
		AppendProfile(sb, "counterattack.doctrine.syntheticCounterAttack", Homm3CustomLawEffectProfiles.TryGetCounterattackDoctrineProfile(factionSid, rank, counterObservation, out var counter, out var counterFail), counter.ToString(), counterFail);
		AppendProfile(sb, "spell.low", Homm3CustomLawEffectProfiles.TryGetSpellSchoolProfile(factionSid, rank, Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex, out var spellLow, out var spellLowFail), spellLow.ToString(), spellLowFail);
		AppendProfile(sb, "battle.melee-formation", Homm3CustomLawEffectProfiles.TryGetFormationProfile(factionSid, rank, "battle.melee-formation", out var melee, out var meleeFail), melee.ToString(), meleeFail);
		AppendProfile(sb, "battle.ranged-formation", Homm3CustomLawEffectProfiles.TryGetFormationProfile(factionSid, rank, "battle.ranged-formation", out var ranged, out var rangedFail), ranged.ToString(), rangedFail);
		AppendProfile(sb, "reward.gold-economy", Homm3CustomLawEffectProfiles.TryGetRewardEconomyProfile(factionSid, rank, "reward.gold-economy", out var economy, out var economyFail), economy.ToString(), economyFail);
		AppendProfile(sb, "morale.package", Homm3CustomLawEffectProfiles.TryGetMoralePackageProfile(factionSid, rank, out var moralePackage, out var moralePackageFail), moralePackage.ToString(), moralePackageFail);
		var positiveMorale = new Homm3MoraleTriggerNativeAdapter.MoraleRollObservation(Homm3MoraleTriggerNativeAdapter.MoraleRollKind.Positive, true, "synthetic-catalog-positive");
		AppendProfile(sb, "morale.trigger.syntheticPositiveTrue", Homm3CustomLawEffectProfiles.TryGetMoraleTriggerProfile(factionSid, rank, positiveMorale, out var moralePositive, out var moralePositiveFail), moralePositive.ToString(), moralePositiveFail);
		var negativeMorale = new Homm3MoraleTriggerNativeAdapter.MoraleRollObservation(Homm3MoraleTriggerNativeAdapter.MoraleRollKind.Negative, true, "synthetic-catalog-negative");
		AppendProfile(sb, "morale.trigger.syntheticNegativeTrue", Homm3CustomLawEffectProfiles.TryGetMoraleTriggerProfile(factionSid, rank, negativeMorale, out var moraleNegative, out var moraleNegativeFail), moraleNegative.ToString(), moraleNegativeFail);
		AppendProfile(sb, "spell.high", Homm3CustomLawEffectProfiles.TryGetSpellSchoolProfile(factionSid, rank, Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex, out var spellHigh, out var spellHighFail), spellHigh.ToString(), spellHighFail);
		AppendProfile(sb, "construction.commit", Homm3CustomLawEffectProfiles.TryGetConstructionProfile(factionSid, rank, out var construction, out var constructionFail), construction.ToString(), constructionFail);
		AppendProfile(sb, "reward.calendar", Homm3CustomLawEffectProfiles.TryGetCalendarProfile(factionSid, rank, out var calendar, out var calendarFail), calendar.ToString(), calendarFail);
		AppendProfile(sb, "spell.cooldown", Homm3CustomLawEffectProfiles.TryGetSpellCooldownProfile(factionSid, rank, out var cooldown, out var cooldownFail), cooldown.ToString(), cooldownFail);
	}

	private static void AppendProfile(StringBuilder sb, string handlerKey, bool ok, string value, string failReason)
	{
		sb.Append(" ").Append(handlerKey).Append("=");
		if (ok)
		{
			sb.Append("{").Append(value).Append("}");
			return;
		}
		sb.Append("denied:'").Append(failReason ?? "unknown").Append("'");
	}
}
