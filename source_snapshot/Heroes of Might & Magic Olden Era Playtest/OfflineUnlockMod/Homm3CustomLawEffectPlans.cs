namespace OfflineUnlockMod;

/// <summary>
/// Source-prepared, non-mutating execution plans for custom faction laws.
/// These plans are the handoff between approved law profiles and future exact
/// native mutations. They intentionally do not patch, register hooks, modify
/// game state, or promote any packet proof gate.
/// </summary>
internal static class Homm3CustomLawEffectPlans
{
	internal readonly struct TrainingDamageEffectPlan
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly int ObservedDamage;
		internal readonly int BonusDamagePercent;
		internal readonly int PlannedBonusDamage;
		internal readonly int AttackDebuffPerHit;
		internal readonly int DefenseDebuffPerHit;
		internal readonly int TemporaryManaPerCorpse;
		internal readonly int SpeedDelta;
		internal readonly string MutationKind;
		internal readonly string MutationPoint;
		internal readonly string MutationCleanup;
		internal readonly string RequiredPredicates;
		internal readonly string EvidenceBoundary;

		internal TrainingDamageEffectPlan(
			Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
			Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
			Homm3TrainingDamageMutationRegistry.Entry mutation,
			string requiredPredicates)
		{
			FactionSid = profile.FactionSid;
			LawName = profile.LawName;
			EffectKey = profile.EffectKey;
			Rank = profile.Rank;
			ObservedDamage = damageInfo.Damage;
			BonusDamagePercent = profile.DamagePercentBonus;
			PlannedBonusDamage = profile.DamagePercentBonus == 0
				? 0
				: damageInfo.Damage * profile.DamagePercentBonus / 100;
			AttackDebuffPerHit = profile.AttackDebuffPerHit;
			DefenseDebuffPerHit = profile.DefenseDebuffPerHit;
			TemporaryManaPerCorpse = profile.TemporaryManaPerCorpse;
			SpeedDelta = profile.SpeedDelta;
			MutationKind = mutation.MutationKind;
			MutationPoint = mutation.MutationPoint;
			MutationCleanup = mutation.Cleanup;
			RequiredPredicates = requiredPredicates;
			EvidenceBoundary = profile.EvidenceBoundary;
		}

		public override string ToString()
		{
			return "trainingDamagePlan faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " observedDamage=" + ObservedDamage
			       + " bonusDamagePercent=" + BonusDamagePercent
			       + " plannedBonusDamage=" + PlannedBonusDamage
			       + " attackDebuffPerHit=" + AttackDebuffPerHit
			       + " defenseDebuffPerHit=" + DefenseDebuffPerHit
			       + " temporaryManaPerCorpse=" + TemporaryManaPerCorpse
			       + " speedDelta=" + SpeedDelta
			       + " mutationKind=" + (MutationKind ?? "unresolved")
			       + " mutationPoint=" + (MutationPoint ?? "unresolved")
			       + " cleanup=" + (MutationCleanup ?? "unresolved")
			       + " requiredPredicates=" + RequiredPredicates
			       + " boundary=" + EvidenceBoundary
			       + " mutation=disabled";
		}
	}

	internal readonly struct FormationEffectPlan
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly string HandlerKey;
		internal readonly int RoundNumber;
		internal readonly int AttackedObjectCount;
		internal readonly int AttackedHexCount;
		internal readonly int ImmuneObjectCount;
		internal readonly string AbilityName;
		internal readonly string RequiredPredicates;
		internal readonly string EvidenceBoundary;

		internal FormationEffectPlan(
			Homm3CustomLawEffectProfiles.FormationProfile profile,
			Homm3BattleEventNativeAdapter.CastAbilityEventInfo eventInfo,
			string requiredPredicates)
		{
			FactionSid = profile.FactionSid;
			LawName = profile.LawName;
			EffectKey = profile.EffectKey;
			Rank = profile.Rank;
			HandlerKey = profile.HandlerKey;
			RoundNumber = eventInfo.RoundNumber;
			AttackedObjectCount = eventInfo.AttackedObjectCount;
			AttackedHexCount = eventInfo.AttackedHexCount;
			ImmuneObjectCount = eventInfo.ImmuneObjectCount;
			AbilityName = eventInfo.AbilityName;
			RequiredPredicates = requiredPredicates;
			EvidenceBoundary = profile.EvidenceBoundary;
		}

		public override string ToString()
		{
			return "formationPlan faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " handler=" + HandlerKey
			       + " round=" + RoundNumber
			       + " attackedObjects=" + AttackedObjectCount
			       + " attackedHexes=" + AttackedHexCount
			       + " immuneObjects=" + ImmuneObjectCount
			       + " abilityName=" + (AbilityName ?? "null")
			       + " requiredPredicates=" + RequiredPredicates
			       + " boundary=" + EvidenceBoundary
			       + " mutation=disabled";
		}
	}

	internal readonly struct CounterattackDoctrineEffectPlan
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly int FocusDelta;
		internal readonly int DamagePercentBonus;
		internal readonly int AttackDebuff;
		internal readonly int CounterChargeDelta;
		internal readonly int DrainPercent;
		internal readonly int StackingDamagePercent;
		internal readonly int AbilityIndex;
		internal readonly string RequiredPredicates;
		internal readonly string EvidenceBoundary;

		internal CounterattackDoctrineEffectPlan(
			Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
			Homm3CustomCounterattackLawRuntime.CounterattackAbilityObservation observation,
			string requiredPredicates)
		{
			FactionSid = profile.FactionSid;
			LawName = profile.LawName;
			EffectKey = profile.EffectKey;
			Rank = profile.Rank;
			FocusDelta = profile.FocusDelta;
			DamagePercentBonus = profile.DamagePercentBonus;
			AttackDebuff = profile.AttackDebuff;
			CounterChargeDelta = profile.CounterChargeDelta;
			DrainPercent = profile.DrainPercent;
			StackingDamagePercent = profile.StackingDamagePercent;
			AbilityIndex = observation.AbilityIndex;
			RequiredPredicates = requiredPredicates;
			EvidenceBoundary = profile.EvidenceBoundary;
		}

		public override string ToString()
		{
			return "counterattackDoctrinePlan faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " focusDelta=" + FocusDelta
			       + " damagePercentBonus=" + DamagePercentBonus
			       + " attackDebuff=" + AttackDebuff
			       + " counterChargeDelta=" + CounterChargeDelta
			       + " drainPercent=" + DrainPercent
			       + " stackingDamagePercent=" + StackingDamagePercent
			       + " abilityIndex=" + AbilityIndex
			       + " requiredPredicates=" + RequiredPredicates
			       + " boundary=" + EvidenceBoundary
			       + " mutation=disabled";
		}
	}

	internal readonly struct ProfileEffectPlan
	{
		internal readonly string Packet;
		internal readonly string HandlerKey;
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly string PrimaryAction;
		internal readonly string NumericEffects;
		internal readonly string RequiredPredicates;
		internal readonly string EvidenceBoundary;

		internal ProfileEffectPlan(
			string packet,
			string handlerKey,
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			string primaryAction,
			string numericEffects,
			string requiredPredicates,
			string evidenceBoundary)
		{
			Packet = packet;
			HandlerKey = handlerKey;
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			PrimaryAction = primaryAction;
			NumericEffects = numericEffects;
			RequiredPredicates = requiredPredicates;
			EvidenceBoundary = evidenceBoundary;
		}

		public override string ToString()
		{
			return "profilePlan packet=" + Packet
			       + " handler=" + HandlerKey
			       + " faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " action=" + PrimaryAction
			       + " numericEffects=" + NumericEffects
			       + " requiredPredicates=" + RequiredPredicates
			       + " boundary=" + EvidenceBoundary
			       + " mutation=disabled";
		}
	}

	internal static bool TryPlanTrainingDamageEffect(
		Homm3CustomLawEffectProfiles.TrainingDamageProfile profile,
		Homm3BattleEventNativeAdapter.DamageEventInfo damageInfo,
		out TrainingDamageEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "training damage profile is data-only and has no custom runtime plan";
			return false;
		}
		if (damageInfo.ImmuneToDamage)
		{
			failReason = "damage event is immune; refusing to plan damage/stat side effects";
			return false;
		}
		if (damageInfo.Damage <= 0)
		{
			failReason = "damage event has no positive damage; refusing to plan damage/stat side effects";
			return false;
		}
		if (!Homm3TrainingDamageMutationRegistry.TryGet(profile.EffectKey, out var mutation))
		{
			failReason = "training damage mutation contract missing for effect key " + (profile.EffectKey ?? "null");
			return false;
		}
		plan = new TrainingDamageEffectPlan(profile, damageInfo, mutation, DescribeTrainingDamagePredicates(profile));
		failReason = null;
		return true;
	}

	internal static bool TryPlanFormationEffect(
		Homm3CustomLawEffectProfiles.FormationProfile profile,
		Homm3BattleEventNativeAdapter.CastAbilityEventInfo eventInfo,
		out FormationEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "formation profile is data-only and has no custom runtime plan";
			return false;
		}
		if (profile.RequiresFirstVolley && eventInfo.RoundNumber != 1)
		{
			failReason = "formation profile requires first volley but event round is " + eventInfo.RoundNumber;
			return false;
		}
		plan = new FormationEffectPlan(profile, eventInfo, DescribeFormationPredicates(profile));
		failReason = null;
		return true;
	}

	internal static bool TryPlanCounterattackDoctrineEffect(
		Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile,
		Homm3CustomCounterattackLawRuntime.CounterattackAbilityObservation observation,
		out CounterattackDoctrineEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "counterattack doctrine profile is data-only and has no custom runtime plan";
			return false;
		}
		if (!observation.IsCounterAttackCandidate)
		{
			failReason = "observation is not native CounterAttack; refusing to plan counterattack doctrine effect";
			return false;
		}
		plan = new CounterattackDoctrineEffectPlan(profile, observation, DescribeCounterattackPredicates(profile));
		failReason = null;
		return true;
	}

	internal static bool TryPlanMoraleTriggerEffect(
		Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile,
		Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.UsesPositiveCandidate && !observation.PositiveCandidateReturnedTrue)
		{
			failReason = "morale trigger profile requires positive candidate success";
			return false;
		}
		if (profile.UsesNegativeCandidate && !observation.NegativeCandidateReturnedTrue)
		{
			failReason = "morale trigger profile requires negative candidate success";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.Morale,
			"morale.trigger",
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"morale-trigger-reaction",
			"focusDelta=" + profile.FocusDelta
			+ ",moraleDelta=" + profile.MoraleDelta
			+ ",speedDelta=" + profile.SpeedDelta
			+ ",damagePercentBonus=" + profile.DamagePercentBonus,
			DescribeMoraleTriggerPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanMoralePackageEffect(
		Homm3CustomLawEffectProfiles.MoralePackageProfile profile,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "morale package profile is data-only and has no custom runtime plan";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.Morale,
			"morale.package",
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"morale-package-runtime-behavior",
			"nativeFriendlyMoraleRows=" + profile.UsesNativeFriendlyMoraleRows
			+ ",nativeAdditionalActionRows=" + profile.UsesNativeAdditionalActionRows,
			DescribeMoralePackagePredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanRewardEconomyEffect(
		Homm3CustomLawEffectProfiles.RewardEconomyProfile profile,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "reward economy profile is data-only and has no custom runtime plan";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.RewardResult,
			profile.HandlerKey,
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"reward-economy-grant",
			"goldGrantPercent=" + profile.GoldGrantPercent + ",goldGrantFlat=" + profile.GoldGrantFlat,
			DescribeRewardEconomyPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanCalendarEffect(
		Homm3CustomLawEffectProfiles.CalendarProfile profile,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.RewardResult,
			"reward.calendar",
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"calendar-phase-runtime-behavior",
			"nativeAstrologyIncome=" + profile.NativeAstrologyIncome
			+ ",nativeAstrologyShape=" + (profile.NativeAstrologyShape ?? "none")
			+ ",phaseModel=" + (profile.PhaseModel ?? "none"),
			DescribeCalendarPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanConstructionEffect(
		Homm3CustomLawEffectProfiles.ConstructionProfile profile,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "construction profile is data-only and has no custom runtime plan";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.Construction,
			"construction.commit",
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"construction-eligibility-cost-or-refund",
			"extraBuildCount=" + profile.ExtraBuildCount
			+ ",goldDiscountPercent=" + profile.GoldDiscountPercent
			+ ",woodOreDiscountPercent=" + profile.WoodOreDiscountPercent
			+ ",goldSurchargePercent=" + profile.GoldSurchargePercent
			+ ",oreDiscountPercent=" + profile.OreDiscountPercent
			+ ",sacrificeValuePercent=" + profile.SacrificeValuePercent,
			DescribeConstructionPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanVisionEffect(
		Homm3CustomLawEffectProfiles.VisionProfile profile,
		int side,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "vision profile is data-only and has no custom runtime plan";
			return false;
		}
		if (side < 0)
		{
			failReason = "vision plan requires resolved non-negative side index";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.Vision,
			"vision.reveal",
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"vision-reveal-or-scout",
			"side=" + side
			+ ",viewRadiusDelta=" + profile.ViewRadiusDelta
			+ ",triggerContext=" + (profile.TriggerContext ?? "none")
			+ ",revealGroup=" + (profile.RevealGroup ?? "none"),
			DescribeVisionPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanSpellCooldownEffect(
		Homm3CustomLawEffectProfiles.SpellCooldownProfile profile,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "spell cooldown profile is data-only and has no custom runtime plan";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.SpellCooldown,
			"spell.cooldown",
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"spell-cooldown-credit-or-gate",
			"cooldownDelta=" + profile.CooldownDelta,
			DescribeSpellCooldownPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	internal static bool TryPlanSpellSchoolEffect(
		Homm3CustomLawEffectProfiles.SpellSchoolProfile profile,
		out ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (profile.DataOnly)
		{
			failReason = "spell school profile is data-only and has no custom runtime plan";
			return false;
		}
		plan = new ProfileEffectPlan(
			Homm3CustomLawPacketGate.SpellCooldown,
			profile.HandlerKey,
			profile.FactionSid,
			profile.LawName,
			profile.EffectKey,
			profile.Rank,
			"spell-school-access-or-runtime-addon",
			"lawIndex=" + profile.LawIndex
			+ ",nativeSchool=" + (profile.NativeSchoolName ?? "none")
			+ ",nativeAccessShape=" + (profile.NativeAccessShape ?? "none"),
			DescribeSpellSchoolPredicates(profile),
			profile.EvidenceBoundary);
		failReason = null;
		return true;
	}

	private static string DescribeTrainingDamagePredicates(Homm3CustomLawEffectProfiles.TrainingDamageProfile profile)
	{
		var predicates = "positiveDamage";
		AppendPredicate(ref predicates, profile.RequiresPositiveMoraleValue, "positiveMoraleValue");
		AppendPredicate(ref predicates, profile.RequiresGunpowderDealer, "gunpowderDealer");
		AppendPredicate(ref predicates, profile.RequiresCannonOrPirateDealer, "cannonOrPirateDealer");
		AppendPredicate(ref predicates, profile.RequiresIsolatedTarget, "isolatedTarget");
		AppendPredicate(ref predicates, profile.RequiresDebuffedAttacker, "debuffedAttacker");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresHeroSpellCast, "heroSpellCast");
		AppendPredicate(ref predicates, profile.RequiresElementalFamily, "elementalFamily");
		AppendPredicate(ref predicates, profile.RequiresGatedIdentity, "gatedIdentity");
		AppendPredicate(ref predicates, profile.RequiresCorpseCount, "corpseCount");
		AppendPredicate(ref predicates, profile.RequiresWoundedUnit, "woundedUnit");
		return predicates;
	}

	private static string DescribeFormationPredicates(Homm3CustomLawEffectProfiles.FormationProfile profile)
	{
		var predicates = "castAbilityEvent";
		AppendPredicate(ref predicates, profile.RequiresGunpowderOrPirate, "gunpowderOrPirate");
		AppendPredicate(ref predicates, profile.RequiresFirstVolley, "firstVolley");
		AppendPredicate(ref predicates, profile.RequiresFocusOrReload, "focusOrReload");
		AppendPredicate(ref predicates, profile.RequiresGeometryPredicate, "geometryPredicate");
		AppendPredicate(ref predicates, profile.RequiresNegativeStatusPredicate, "negativeStatusPredicate");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresConstructClassifier, "constructClassifier");
		AppendPredicate(ref predicates, profile.RequiresHeroSpellCast, "heroSpellCast");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMix, "elementalFamilyMix");
		AppendPredicate(ref predicates, profile.RequiresGatedOrTeleportedIdentity, "gatedOrTeleportedIdentity");
		AppendPredicate(ref predicates, profile.RequiresLivingEnemyPredicate, "livingEnemyPredicate");
		AppendPredicate(ref predicates, profile.RequiresForwardMovementOrKill, "forwardMovementOrKill");
		return predicates;
	}

	private static string DescribeCounterattackPredicates(Homm3CustomLawEffectProfiles.CounterattackDoctrineProfile profile)
	{
		var predicates = "nativeCounterAttack";
		AppendPredicate(ref predicates, profile.RequiresTargetOutnumbered, "targetOutnumbered");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresHeroSpellPower, "heroSpellPower");
		AppendPredicate(ref predicates, profile.RequiresSeparateMagicDamageSurface, "separateMagicDamageSurface");
		return predicates;
	}

	private static string DescribeMoraleTriggerPredicates(Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile)
	{
		var predicates = "moraleRollObservation";
		AppendPredicate(ref predicates, profile.UsesPositiveCandidate, "positiveCandidate");
		AppendPredicate(ref predicates, profile.UsesNegativeCandidate, "negativeCandidate");
		AppendPredicate(ref predicates, profile.RequiresOpposingLawOwner, "opposingLawOwner");
		AppendPredicate(ref predicates, profile.RequiresKillOrLossEvent, "killOrLossEvent");
		AppendPredicate(ref predicates, profile.RequiresDamageTakenEvent, "damageTakenEvent");
		AppendPredicate(ref predicates, profile.RequiresSpellCastEvent, "spellCastEvent");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMix, "elementalFamilyMix");
		AppendPredicate(ref predicates, profile.RequiresGatedOrSacrificeIdentity, "gatedOrSacrificeIdentity");
		AppendPredicate(ref predicates, profile.RequiresCorpseOrUndeadContext, "corpseOrUndeadContext");
		return predicates;
	}

	private static string DescribeMoralePackagePredicates(Homm3CustomLawEffectProfiles.MoralePackageProfile profile)
	{
		var predicates = "activeMoralePackageLaw";
		AppendPredicate(ref predicates, profile.AvoidsFriendlyMoraleBonus, "avoidFriendlyMoraleBonus");
		AppendPredicate(ref predicates, profile.RequiresEnemyMoralePenalty, "enemyMoralePenalty");
		AppendPredicate(ref predicates, profile.RequiresKillOrLossEvent, "killOrLossEvent");
		AppendPredicate(ref predicates, profile.RequiresDamageTakenEvent, "damageTakenEvent");
		AppendPredicate(ref predicates, profile.RequiresSpellCastEvent, "spellCastEvent");
		AppendPredicate(ref predicates, profile.RequiresProtectOrPreserveEvent, "protectOrPreserveEvent");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresConstructClassifier, "constructClassifier");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMix, "elementalFamilyMix");
		AppendPredicate(ref predicates, profile.RequiresGatedOrSacrificeIdentity, "gatedOrSacrificeIdentity");
		AppendPredicate(ref predicates, profile.RequiresCorpseOrUndeadContext, "corpseOrUndeadContext");
		AppendPredicate(ref predicates, profile.RequiresWarcryOrRageEvent, "warcryOrRageEvent");
		return predicates;
	}

	private static string DescribeRewardEconomyPredicates(Homm3CustomLawEffectProfiles.RewardEconomyProfile profile)
	{
		var predicates = "activeRewardLaw";
		AppendPredicate(ref predicates, profile.RequiresCommittedRewardIdentity, "committedRewardIdentity");
		AppendPredicate(ref predicates, profile.RequiresCaptureOrOwnershipTransfer, "captureOrOwnershipTransfer");
		AppendPredicate(ref predicates, profile.RequiresBattleResultCasualties, "battleResultCasualties");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresRareResourceBalance, "rareResourceBalance");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMix, "elementalFamilyMix");
		AppendPredicate(ref predicates, profile.RequiresSacrificeOrTemporaryLoss, "sacrificeOrTemporaryLoss");
		AppendPredicate(ref predicates, profile.RequiresCorpseOrCasualtyContext, "corpseOrCasualtyContext");
		AppendPredicate(ref predicates, profile.RequiresWarcryExecution, "warcryExecution");
		return predicates;
	}

	private static string DescribeCalendarPredicates(Homm3CustomLawEffectProfiles.CalendarProfile profile)
	{
		var predicates = "activeCalendarLaw";
		AppendPredicate(ref predicates, profile.RequiresDaySideLawIdempotence, "daySideLawIdempotence");
		AppendPredicate(ref predicates, profile.RequiresAstrologyProgressMutation, "astrologyProgressMutation");
		AppendPredicate(ref predicates, profile.RequiresSpellCastEvent, "spellCastEvent");
		AppendPredicate(ref predicates, profile.RequiresBattleStartOrRoundEvent, "battleStartOrRoundEvent");
		AppendPredicate(ref predicates, profile.RequiresStatusDurationMutation, "statusDurationMutation");
		AppendPredicate(ref predicates, profile.RequiresFocusEvent, "focusEvent");
		AppendPredicate(ref predicates, profile.RequiresCooldownMutation, "cooldownMutation");
		AppendPredicate(ref predicates, profile.RequiresConstructClassifier, "constructClassifier");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMapping, "elementalFamilyMapping");
		AppendPredicate(ref predicates, profile.RequiresGatingSacrificeOrSummon, "gatingSacrificeOrSummon");
		AppendPredicate(ref predicates, profile.RequiresCorpseOrRaiseConsumption, "corpseOrRaiseConsumption");
		AppendPredicate(ref predicates, profile.RequiresWarcryExecution, "warcryExecution");
		return predicates;
	}

	private static string DescribeConstructionPredicates(Homm3CustomLawEffectProfiles.ConstructionProfile profile)
	{
		var predicates = "activeConstructionLaw";
		AppendPredicate(ref predicates, profile.RequiresBuildingAllowlist, "buildingAllowlist");
		AppendPredicate(ref predicates, profile.RequiresDisplayedAndChargedCostParity, "displayedAndChargedCostParity");
		AppendPredicate(ref predicates, profile.RequiresCaptureToken, "captureToken");
		AppendPredicate(ref predicates, profile.RequiresPersistentMatureDwellingState, "persistentMatureDwellingState");
		AppendPredicate(ref predicates, profile.RequiresElementalBuildingMapping, "elementalBuildingMapping");
		AppendPredicate(ref predicates, profile.RequiresGarrisonSacrifice, "garrisonSacrifice");
		AppendPredicate(ref predicates, profile.RequiresDeathworksCredit, "deathworksCredit");
		AppendPredicate(ref predicates, !string.IsNullOrWhiteSpace(profile.EligibleGroup), "eligibleGroup=" + (profile.EligibleGroup ?? "none"));
		return predicates;
	}

	private static string DescribeVisionPredicates(Homm3CustomLawEffectProfiles.VisionProfile profile)
	{
		var predicates = "activeVisionLaw";
		AppendPredicate(ref predicates, profile.RequiresRoadTerrain, "roadTerrain");
		AppendPredicate(ref predicates, profile.RequiresOwnedStructureRadius, "ownedStructureRadius");
		AppendPredicate(ref predicates, profile.RequiresObjectSidOrCategoryAllowlist, "objectSidOrCategoryAllowlist");
		AppendPredicate(ref predicates, profile.RequiresNeutralThreatData, "neutralThreatData");
		AppendPredicate(ref predicates, profile.RequiresReadOnlyTooltipPreview, "readOnlyTooltipPreview");
		AppendPredicate(ref predicates, profile.RequiresEnemyHeroPositions, "enemyHeroPositions");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMapping, "elementalFamilyMapping");
		AppendPredicate(ref predicates, profile.RequiresExistingMapObjectClasses, "existingMapObjectClasses");
		AppendPredicate(ref predicates, profile.RequiresCorpseOrBattleSiteData, "corpseOrBattleSiteData");
		AppendPredicate(ref predicates, profile.RequiresFogRevealMutation, "fogRevealMutation");
		return predicates;
	}

	private static string DescribeSpellCooldownPredicates(Homm3CustomLawEffectProfiles.SpellCooldownProfile profile)
	{
		var predicates = "activeSpellCooldownLaw";
		AppendPredicate(ref predicates, profile.RequiresSpellSchoolOrSidClass, "spellSchoolOrSidClass");
		AppendPredicate(ref predicates, profile.RequiresSupportBlessingClassification, "supportBlessingClassification");
		AppendPredicate(ref predicates, profile.RequiresMovementStormSeaClassification, "movementStormSeaClassification");
		AppendPredicate(ref predicates, profile.RequiresNightCurseClassification, "nightCurseClassification");
		AppendPredicate(ref predicates, profile.RequiresEnemySlowPoisonMireState, "enemySlowPoisonMireState");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresOverclockCredit, "overclockCredit");
		AppendPredicate(ref predicates, profile.RequiresCastGateOverride, "castGateOverride");
		AppendPredicate(ref predicates, profile.RequiresElementalFamilyMapping, "elementalFamilyMapping");
		AppendPredicate(ref predicates, profile.RequiresSacrificeOrTemporaryLoss, "sacrificeOrTemporaryLoss");
		AppendPredicate(ref predicates, profile.RequiresCorpseConsumption, "corpseConsumption");
		AppendPredicate(ref predicates, profile.RequiresWarcryExecution, "warcryExecution");
		return predicates;
	}

	private static string DescribeSpellSchoolPredicates(Homm3CustomLawEffectProfiles.SpellSchoolProfile profile)
	{
		var predicates = "activeSpellSchoolLaw";
		AppendPredicate(ref predicates, profile.RequiresNativeSchoolVerification, "nativeSchoolVerification");
		AppendPredicate(ref predicates, profile.RequiresSpellCastEvent, "spellCastEvent");
		AppendPredicate(ref predicates, profile.RequiresGunpowderOrRangedSupport, "gunpowderOrRangedSupport");
		AppendPredicate(ref predicates, profile.RequiresFocusCredit, "focusCredit");
		AppendPredicate(ref predicates, profile.RequiresPoisonSlowMovementRestriction, "poisonSlowMovementRestriction");
		AppendPredicate(ref predicates, profile.RequiresNativeTerrainOrAdjacency, "nativeTerrainOrAdjacency");
		AppendPredicate(ref predicates, profile.RequiresAvengerMark, "avengerMark");
		AppendPredicate(ref predicates, profile.RequiresSpellbookReuseState, "spellbookReuseState");
		AppendPredicate(ref predicates, profile.RequiresDynamicElementalFamily, "dynamicElementalFamily");
		AppendPredicate(ref predicates, profile.RequiresGatingSacrificeOrSummon, "gatingSacrificeOrSummon");
		AppendPredicate(ref predicates, profile.RequiresCorpseOrCasualtyContext, "corpseOrCasualtyContext");
		AppendPredicate(ref predicates, profile.RequiresWarcryExecution, "warcryExecution");
		return predicates;
	}

	private static void AppendPredicate(ref string predicates, bool enabled, string name)
	{
		if (!enabled)
			return;
		predicates += "," + name;
	}
}
