using System;

namespace OfflineUnlockMod;

/// <summary>
/// Source-prepared, non-mutating effect profiles for custom faction laws.
/// These profiles translate the approved law design into concrete packet
/// intents. They do not register hooks, mutate game state, or promote packet
/// proof gates. Exact runtime hooks must still pass through the packet runtime
/// gates before consuming any profile.
/// </summary>
internal static class Homm3CustomLawEffectProfiles
{
	internal const string Castle = "homm3_castle";
	internal const string Cove = "homm3_cove";
	internal const string Dungeon = "homm3_dungeon";
	internal const string Fortress = "homm3_fortress";
	internal const string Rampart = "homm3_rampart";
	internal const string Tower = "homm3_tower";
	internal const string Conflux = "homm3_conflux";
	internal const string Inferno = "homm3_inferno";
	internal const string Necropolis = "homm3_necropolis";
	internal const string Stronghold = "homm3_stronghold";

	internal readonly struct CounterattackDoctrineProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool DataOnly;
		internal readonly int FocusDelta;
		internal readonly int DamagePercentBonus;
		internal readonly int AttackDebuff;
		internal readonly int CounterChargeDelta;
		internal readonly int DrainPercent;
		internal readonly int StackingDamagePercent;
		internal readonly bool RequiresTargetOutnumbered;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresHeroSpellPower;
		internal readonly bool RequiresSeparateMagicDamageSurface;
		internal readonly string EvidenceBoundary;

		internal CounterattackDoctrineProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool dataOnly = false,
			int focusDelta = 0,
			int damagePercentBonus = 0,
			int attackDebuff = 0,
			int counterChargeDelta = 0,
			int drainPercent = 0,
			int stackingDamagePercent = 0,
			bool requiresTargetOutnumbered = false,
			bool requiresAvengerMark = false,
			bool requiresHeroSpellPower = false,
			bool requiresSeparateMagicDamageSurface = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			DataOnly = dataOnly;
			FocusDelta = focusDelta;
			DamagePercentBonus = damagePercentBonus;
			AttackDebuff = attackDebuff;
			CounterChargeDelta = counterChargeDelta;
			DrainPercent = drainPercent;
			StackingDamagePercent = stackingDamagePercent;
			RequiresTargetOutnumbered = requiresTargetOutnumbered;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresHeroSpellPower = requiresHeroSpellPower;
			RequiresSeparateMagicDamageSurface = requiresSeparateMagicDamageSurface;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; exact counterattack-to-damage correlation still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " dataOnly=" + DataOnly
			       + " focusDelta=" + FocusDelta
			       + " damagePercentBonus=" + DamagePercentBonus
			       + " attackDebuff=" + AttackDebuff
			       + " counterChargeDelta=" + CounterChargeDelta
			       + " drainPercent=" + DrainPercent
			       + " stackingDamagePercent=" + StackingDamagePercent
			       + " requiresTargetOutnumbered=" + RequiresTargetOutnumbered
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresHeroSpellPower=" + RequiresHeroSpellPower
			       + " requiresSeparateMagicDamageSurface=" + RequiresSeparateMagicDamageSurface
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct MoraleTriggerProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool UsesPositiveCandidate;
		internal readonly bool UsesNegativeCandidate;
		internal readonly bool RequiresOpposingLawOwner;
		internal readonly bool RequiresKillOrLossEvent;
		internal readonly bool RequiresDamageTakenEvent;
		internal readonly bool RequiresSpellCastEvent;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresElementalFamilyMix;
		internal readonly bool RequiresGatedOrSacrificeIdentity;
		internal readonly bool RequiresCorpseOrUndeadContext;
		internal readonly int FocusDelta;
		internal readonly int MoraleDelta;
		internal readonly int SpeedDelta;
		internal readonly int DamagePercentBonus;
		internal readonly string EvidenceBoundary;

		internal MoraleTriggerProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool usesPositiveCandidate,
			bool usesNegativeCandidate,
			bool requiresOpposingLawOwner = false,
			bool requiresKillOrLossEvent = false,
			bool requiresDamageTakenEvent = false,
			bool requiresSpellCastEvent = false,
			bool requiresAvengerMark = false,
			bool requiresElementalFamilyMix = false,
			bool requiresGatedOrSacrificeIdentity = false,
			bool requiresCorpseOrUndeadContext = false,
			int focusDelta = 0,
			int moraleDelta = 0,
			int speedDelta = 0,
			int damagePercentBonus = 0,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			UsesPositiveCandidate = usesPositiveCandidate;
			UsesNegativeCandidate = usesNegativeCandidate;
			RequiresOpposingLawOwner = requiresOpposingLawOwner;
			RequiresKillOrLossEvent = requiresKillOrLossEvent;
			RequiresDamageTakenEvent = requiresDamageTakenEvent;
			RequiresSpellCastEvent = requiresSpellCastEvent;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresElementalFamilyMix = requiresElementalFamilyMix;
			RequiresGatedOrSacrificeIdentity = requiresGatedOrSacrificeIdentity;
			RequiresCorpseOrUndeadContext = requiresCorpseOrUndeadContext;
			FocusDelta = focusDelta;
			MoraleDelta = moraleDelta;
			SpeedDelta = speedDelta;
			DamagePercentBonus = damagePercentBonus;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; morale true/false semantic ordering still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " usesPositiveCandidate=" + UsesPositiveCandidate
			       + " usesNegativeCandidate=" + UsesNegativeCandidate
			       + " requiresOpposingLawOwner=" + RequiresOpposingLawOwner
			       + " requiresKillOrLossEvent=" + RequiresKillOrLossEvent
			       + " requiresDamageTakenEvent=" + RequiresDamageTakenEvent
			       + " requiresSpellCastEvent=" + RequiresSpellCastEvent
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresElementalFamilyMix=" + RequiresElementalFamilyMix
			       + " requiresGatedOrSacrificeIdentity=" + RequiresGatedOrSacrificeIdentity
			       + " requiresCorpseOrUndeadContext=" + RequiresCorpseOrUndeadContext
			       + " focusDelta=" + FocusDelta
			       + " moraleDelta=" + MoraleDelta
			       + " speedDelta=" + SpeedDelta
			       + " damagePercentBonus=" + DamagePercentBonus
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct MoralePackageProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool DataOnly;
		internal readonly bool UsesNativeFriendlyMoraleRows;
		internal readonly bool UsesNativeAdditionalActionRows;
		internal readonly bool AvoidsFriendlyMoraleBonus;
		internal readonly bool RequiresEnemyMoralePenalty;
		internal readonly bool RequiresKillOrLossEvent;
		internal readonly bool RequiresDamageTakenEvent;
		internal readonly bool RequiresSpellCastEvent;
		internal readonly bool RequiresProtectOrPreserveEvent;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresConstructClassifier;
		internal readonly bool RequiresElementalFamilyMix;
		internal readonly bool RequiresGatedOrSacrificeIdentity;
		internal readonly bool RequiresCorpseOrUndeadContext;
		internal readonly bool RequiresWarcryOrRageEvent;
		internal readonly string EvidenceBoundary;

		internal MoralePackageProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool dataOnly = false,
			bool usesNativeFriendlyMoraleRows = false,
			bool usesNativeAdditionalActionRows = false,
			bool avoidsFriendlyMoraleBonus = false,
			bool requiresEnemyMoralePenalty = false,
			bool requiresKillOrLossEvent = false,
			bool requiresDamageTakenEvent = false,
			bool requiresSpellCastEvent = false,
			bool requiresProtectOrPreserveEvent = false,
			bool requiresAvengerMark = false,
			bool requiresConstructClassifier = false,
			bool requiresElementalFamilyMix = false,
			bool requiresGatedOrSacrificeIdentity = false,
			bool requiresCorpseOrUndeadContext = false,
			bool requiresWarcryOrRageEvent = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			DataOnly = dataOnly;
			UsesNativeFriendlyMoraleRows = usesNativeFriendlyMoraleRows;
			UsesNativeAdditionalActionRows = usesNativeAdditionalActionRows;
			AvoidsFriendlyMoraleBonus = avoidsFriendlyMoraleBonus;
			RequiresEnemyMoralePenalty = requiresEnemyMoralePenalty;
			RequiresKillOrLossEvent = requiresKillOrLossEvent;
			RequiresDamageTakenEvent = requiresDamageTakenEvent;
			RequiresSpellCastEvent = requiresSpellCastEvent;
			RequiresProtectOrPreserveEvent = requiresProtectOrPreserveEvent;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresConstructClassifier = requiresConstructClassifier;
			RequiresElementalFamilyMix = requiresElementalFamilyMix;
			RequiresGatedOrSacrificeIdentity = requiresGatedOrSacrificeIdentity;
			RequiresCorpseOrUndeadContext = requiresCorpseOrUndeadContext;
			RequiresWarcryOrRageEvent = requiresWarcryOrRageEvent;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; flat morale, replacement package, and action-queue behavior still require exact native proof";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " dataOnly=" + DataOnly
			       + " usesNativeFriendlyMoraleRows=" + UsesNativeFriendlyMoraleRows
			       + " usesNativeAdditionalActionRows=" + UsesNativeAdditionalActionRows
			       + " avoidsFriendlyMoraleBonus=" + AvoidsFriendlyMoraleBonus
			       + " requiresEnemyMoralePenalty=" + RequiresEnemyMoralePenalty
			       + " requiresKillOrLossEvent=" + RequiresKillOrLossEvent
			       + " requiresDamageTakenEvent=" + RequiresDamageTakenEvent
			       + " requiresSpellCastEvent=" + RequiresSpellCastEvent
			       + " requiresProtectOrPreserveEvent=" + RequiresProtectOrPreserveEvent
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresConstructClassifier=" + RequiresConstructClassifier
			       + " requiresElementalFamilyMix=" + RequiresElementalFamilyMix
			       + " requiresGatedOrSacrificeIdentity=" + RequiresGatedOrSacrificeIdentity
			       + " requiresCorpseOrUndeadContext=" + RequiresCorpseOrUndeadContext
			       + " requiresWarcryOrRageEvent=" + RequiresWarcryOrRageEvent
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct RewardEconomyProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly string HandlerKey;
		internal readonly bool DataOnly;
		internal readonly bool RequiresCommittedRewardIdentity;
		internal readonly bool RequiresCaptureOrOwnershipTransfer;
		internal readonly bool RequiresBattleResultCasualties;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresRareResourceBalance;
		internal readonly bool RequiresElementalFamilyMix;
		internal readonly bool RequiresSacrificeOrTemporaryLoss;
		internal readonly bool RequiresCorpseOrCasualtyContext;
		internal readonly bool RequiresWarcryExecution;
		internal readonly int GoldGrantPercent;
		internal readonly int GoldGrantFlat;
		internal readonly string EvidenceBoundary;

		internal RewardEconomyProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			string handlerKey,
			bool dataOnly = false,
			bool requiresCommittedRewardIdentity = false,
			bool requiresCaptureOrOwnershipTransfer = false,
			bool requiresBattleResultCasualties = false,
			bool requiresAvengerMark = false,
			bool requiresRareResourceBalance = false,
			bool requiresElementalFamilyMix = false,
			bool requiresSacrificeOrTemporaryLoss = false,
			bool requiresCorpseOrCasualtyContext = false,
			bool requiresWarcryExecution = false,
			int goldGrantPercent = 0,
			int goldGrantFlat = 0,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			HandlerKey = handlerKey;
			DataOnly = dataOnly;
			RequiresCommittedRewardIdentity = requiresCommittedRewardIdentity;
			RequiresCaptureOrOwnershipTransfer = requiresCaptureOrOwnershipTransfer;
			RequiresBattleResultCasualties = requiresBattleResultCasualties;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresRareResourceBalance = requiresRareResourceBalance;
			RequiresElementalFamilyMix = requiresElementalFamilyMix;
			RequiresSacrificeOrTemporaryLoss = requiresSacrificeOrTemporaryLoss;
			RequiresCorpseOrCasualtyContext = requiresCorpseOrCasualtyContext;
			RequiresWarcryExecution = requiresWarcryExecution;
			GoldGrantPercent = goldGrantPercent;
			GoldGrantFlat = goldGrantFlat;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; reward source identity and idempotence still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " handler=" + HandlerKey
			       + " dataOnly=" + DataOnly
			       + " requiresCommittedRewardIdentity=" + RequiresCommittedRewardIdentity
			       + " requiresCaptureOrOwnershipTransfer=" + RequiresCaptureOrOwnershipTransfer
			       + " requiresBattleResultCasualties=" + RequiresBattleResultCasualties
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresRareResourceBalance=" + RequiresRareResourceBalance
			       + " requiresElementalFamilyMix=" + RequiresElementalFamilyMix
			       + " requiresSacrificeOrTemporaryLoss=" + RequiresSacrificeOrTemporaryLoss
			       + " requiresCorpseOrCasualtyContext=" + RequiresCorpseOrCasualtyContext
			       + " requiresWarcryExecution=" + RequiresWarcryExecution
			       + " goldGrantPercent=" + GoldGrantPercent
			       + " goldGrantFlat=" + GoldGrantFlat
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct CalendarProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool NativeAstrologyIncome;
		internal readonly string NativeAstrologyShape;
		internal readonly string PhaseModel;
		internal readonly bool RequiresDaySideLawIdempotence;
		internal readonly bool RequiresAstrologyProgressMutation;
		internal readonly bool RequiresSpellCastEvent;
		internal readonly bool RequiresBattleStartOrRoundEvent;
		internal readonly bool RequiresStatusDurationMutation;
		internal readonly bool RequiresFocusEvent;
		internal readonly bool RequiresCooldownMutation;
		internal readonly bool RequiresConstructClassifier;
		internal readonly bool RequiresElementalFamilyMapping;
		internal readonly bool RequiresGatingSacrificeOrSummon;
		internal readonly bool RequiresCorpseOrRaiseConsumption;
		internal readonly bool RequiresWarcryExecution;
		internal readonly string EvidenceBoundary;

		internal CalendarProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool nativeAstrologyIncome = true,
			string nativeAstrologyShape = "astrologyExp([250/500/750, 0.0])",
			string phaseModel = "side-day-law",
			bool requiresDaySideLawIdempotence = true,
			bool requiresAstrologyProgressMutation = false,
			bool requiresSpellCastEvent = false,
			bool requiresBattleStartOrRoundEvent = false,
			bool requiresStatusDurationMutation = false,
			bool requiresFocusEvent = false,
			bool requiresCooldownMutation = false,
			bool requiresConstructClassifier = false,
			bool requiresElementalFamilyMapping = false,
			bool requiresGatingSacrificeOrSummon = false,
			bool requiresCorpseOrRaiseConsumption = false,
			bool requiresWarcryExecution = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			NativeAstrologyIncome = nativeAstrologyIncome;
			NativeAstrologyShape = nativeAstrologyShape;
			PhaseModel = phaseModel;
			RequiresDaySideLawIdempotence = requiresDaySideLawIdempotence;
			RequiresAstrologyProgressMutation = requiresAstrologyProgressMutation;
			RequiresSpellCastEvent = requiresSpellCastEvent;
			RequiresBattleStartOrRoundEvent = requiresBattleStartOrRoundEvent;
			RequiresStatusDurationMutation = requiresStatusDurationMutation;
			RequiresFocusEvent = requiresFocusEvent;
			RequiresCooldownMutation = requiresCooldownMutation;
			RequiresConstructClassifier = requiresConstructClassifier;
			RequiresElementalFamilyMapping = requiresElementalFamilyMapping;
			RequiresGatingSacrificeOrSummon = requiresGatingSacrificeOrSummon;
			RequiresCorpseOrRaiseConsumption = requiresCorpseOrRaiseConsumption;
			RequiresWarcryExecution = requiresWarcryExecution;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; native astrology income is data, while faction calendar behavior still requires day/event ordering proof";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " nativeAstrologyIncome=" + NativeAstrologyIncome
			       + " nativeAstrologyShape=" + NativeAstrologyShape
			       + " phaseModel=" + PhaseModel
			       + " requiresDaySideLawIdempotence=" + RequiresDaySideLawIdempotence
			       + " requiresAstrologyProgressMutation=" + RequiresAstrologyProgressMutation
			       + " requiresSpellCastEvent=" + RequiresSpellCastEvent
			       + " requiresBattleStartOrRoundEvent=" + RequiresBattleStartOrRoundEvent
			       + " requiresStatusDurationMutation=" + RequiresStatusDurationMutation
			       + " requiresFocusEvent=" + RequiresFocusEvent
			       + " requiresCooldownMutation=" + RequiresCooldownMutation
			       + " requiresConstructClassifier=" + RequiresConstructClassifier
			       + " requiresElementalFamilyMapping=" + RequiresElementalFamilyMapping
			       + " requiresGatingSacrificeOrSummon=" + RequiresGatingSacrificeOrSummon
			       + " requiresCorpseOrRaiseConsumption=" + RequiresCorpseOrRaiseConsumption
			       + " requiresWarcryExecution=" + RequiresWarcryExecution
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct VisionProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool DataOnly;
		internal readonly int ViewRadiusDelta;
		internal readonly string TriggerContext;
		internal readonly string RevealGroup;
		internal readonly bool RequiresRoadTerrain;
		internal readonly bool RequiresOwnedStructureRadius;
		internal readonly bool RequiresObjectSidOrCategoryAllowlist;
		internal readonly bool RequiresNeutralThreatData;
		internal readonly bool RequiresReadOnlyTooltipPreview;
		internal readonly bool RequiresEnemyHeroPositions;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresElementalFamilyMapping;
		internal readonly bool RequiresExistingMapObjectClasses;
		internal readonly bool RequiresCorpseOrBattleSiteData;
		internal readonly bool RequiresFogRevealMutation;
		internal readonly string EvidenceBoundary;

		internal VisionProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool dataOnly = false,
			int viewRadiusDelta = 0,
			string triggerContext = null,
			string revealGroup = null,
			bool requiresRoadTerrain = false,
			bool requiresOwnedStructureRadius = false,
			bool requiresObjectSidOrCategoryAllowlist = false,
			bool requiresNeutralThreatData = false,
			bool requiresReadOnlyTooltipPreview = false,
			bool requiresEnemyHeroPositions = false,
			bool requiresAvengerMark = false,
			bool requiresElementalFamilyMapping = false,
			bool requiresExistingMapObjectClasses = false,
			bool requiresCorpseOrBattleSiteData = false,
			bool requiresFogRevealMutation = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			DataOnly = dataOnly;
			ViewRadiusDelta = viewRadiusDelta;
			TriggerContext = triggerContext;
			RevealGroup = revealGroup;
			RequiresRoadTerrain = requiresRoadTerrain;
			RequiresOwnedStructureRadius = requiresOwnedStructureRadius;
			RequiresObjectSidOrCategoryAllowlist = requiresObjectSidOrCategoryAllowlist;
			RequiresNeutralThreatData = requiresNeutralThreatData;
			RequiresReadOnlyTooltipPreview = requiresReadOnlyTooltipPreview;
			RequiresEnemyHeroPositions = requiresEnemyHeroPositions;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresElementalFamilyMapping = requiresElementalFamilyMapping;
			RequiresExistingMapObjectClasses = requiresExistingMapObjectClasses;
			RequiresCorpseOrBattleSiteData = requiresCorpseOrBattleSiteData;
			RequiresFogRevealMutation = requiresFogRevealMutation;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; native fog/reveal mutation, object classification, and map refresh ordering still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " dataOnly=" + DataOnly
			       + " viewRadiusDelta=" + ViewRadiusDelta
			       + " triggerContext=" + (TriggerContext ?? "none")
			       + " revealGroup=" + (RevealGroup ?? "none")
			       + " requiresRoadTerrain=" + RequiresRoadTerrain
			       + " requiresOwnedStructureRadius=" + RequiresOwnedStructureRadius
			       + " requiresObjectSidOrCategoryAllowlist=" + RequiresObjectSidOrCategoryAllowlist
			       + " requiresNeutralThreatData=" + RequiresNeutralThreatData
			       + " requiresReadOnlyTooltipPreview=" + RequiresReadOnlyTooltipPreview
			       + " requiresEnemyHeroPositions=" + RequiresEnemyHeroPositions
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresElementalFamilyMapping=" + RequiresElementalFamilyMapping
			       + " requiresExistingMapObjectClasses=" + RequiresExistingMapObjectClasses
			       + " requiresCorpseOrBattleSiteData=" + RequiresCorpseOrBattleSiteData
			       + " requiresFogRevealMutation=" + RequiresFogRevealMutation
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct ConstructionProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool DataOnly;
		internal readonly int ExtraBuildCount;
		internal readonly int GoldDiscountPercent;
		internal readonly int WoodOreDiscountPercent;
		internal readonly int GoldSurchargePercent;
		internal readonly int OreDiscountPercent;
		internal readonly int SacrificeValuePercent;
		internal readonly bool RequiresBuildingAllowlist;
		internal readonly bool RequiresDisplayedAndChargedCostParity;
		internal readonly bool RequiresCaptureToken;
		internal readonly bool RequiresPersistentMatureDwellingState;
		internal readonly bool RequiresElementalBuildingMapping;
		internal readonly bool RequiresGarrisonSacrifice;
		internal readonly bool RequiresDeathworksCredit;
		internal readonly string EligibleGroup;
		internal readonly string EvidenceBoundary;

		internal ConstructionProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool dataOnly = false,
			int extraBuildCount = 0,
			int goldDiscountPercent = 0,
			int woodOreDiscountPercent = 0,
			int goldSurchargePercent = 0,
			int oreDiscountPercent = 0,
			int sacrificeValuePercent = 0,
			bool requiresBuildingAllowlist = false,
			bool requiresDisplayedAndChargedCostParity = false,
			bool requiresCaptureToken = false,
			bool requiresPersistentMatureDwellingState = false,
			bool requiresElementalBuildingMapping = false,
			bool requiresGarrisonSacrifice = false,
			bool requiresDeathworksCredit = false,
			string eligibleGroup = null,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			DataOnly = dataOnly;
			ExtraBuildCount = extraBuildCount;
			GoldDiscountPercent = goldDiscountPercent;
			WoodOreDiscountPercent = woodOreDiscountPercent;
			GoldSurchargePercent = goldSurchargePercent;
			OreDiscountPercent = oreDiscountPercent;
			SacrificeValuePercent = sacrificeValuePercent;
			RequiresBuildingAllowlist = requiresBuildingAllowlist;
			RequiresDisplayedAndChargedCostParity = requiresDisplayedAndChargedCostParity;
			RequiresCaptureToken = requiresCaptureToken;
			RequiresPersistentMatureDwellingState = requiresPersistentMatureDwellingState;
			RequiresElementalBuildingMapping = requiresElementalBuildingMapping;
			RequiresGarrisonSacrifice = requiresGarrisonSacrifice;
			RequiresDeathworksCredit = requiresDeathworksCredit;
			EligibleGroup = eligibleGroup;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; construction validation/commit/cost ordering still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " dataOnly=" + DataOnly
			       + " extraBuildCount=" + ExtraBuildCount
			       + " goldDiscountPercent=" + GoldDiscountPercent
			       + " woodOreDiscountPercent=" + WoodOreDiscountPercent
			       + " goldSurchargePercent=" + GoldSurchargePercent
			       + " oreDiscountPercent=" + OreDiscountPercent
			       + " sacrificeValuePercent=" + SacrificeValuePercent
			       + " requiresBuildingAllowlist=" + RequiresBuildingAllowlist
			       + " requiresDisplayedAndChargedCostParity=" + RequiresDisplayedAndChargedCostParity
			       + " requiresCaptureToken=" + RequiresCaptureToken
			       + " requiresPersistentMatureDwellingState=" + RequiresPersistentMatureDwellingState
			       + " requiresElementalBuildingMapping=" + RequiresElementalBuildingMapping
			       + " requiresGarrisonSacrifice=" + RequiresGarrisonSacrifice
			       + " requiresDeathworksCredit=" + RequiresDeathworksCredit
			       + " eligibleGroup=" + (EligibleGroup ?? "none")
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct TrainingDamageProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly bool DataOnly;
		internal readonly int DamagePercentBonus;
		internal readonly int AttackDebuffPerHit;
		internal readonly int DefenseDebuffPerHit;
		internal readonly int TemporaryManaPerCorpse;
		internal readonly int SpeedDelta;
		internal readonly bool RequiresPositiveMoraleValue;
		internal readonly bool RequiresGunpowderDealer;
		internal readonly bool RequiresCannonOrPirateDealer;
		internal readonly bool RequiresIsolatedTarget;
		internal readonly bool RequiresDebuffedAttacker;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresHeroSpellCast;
		internal readonly bool RequiresElementalFamily;
		internal readonly bool RequiresGatedIdentity;
		internal readonly bool RequiresCorpseCount;
		internal readonly bool RequiresWoundedUnit;
		internal readonly string EvidenceBoundary;

		internal TrainingDamageProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			bool dataOnly = false,
			int damagePercentBonus = 0,
			int attackDebuffPerHit = 0,
			int defenseDebuffPerHit = 0,
			int temporaryManaPerCorpse = 0,
			int speedDelta = 0,
			bool requiresPositiveMoraleValue = false,
			bool requiresGunpowderDealer = false,
			bool requiresCannonOrPirateDealer = false,
			bool requiresIsolatedTarget = false,
			bool requiresDebuffedAttacker = false,
			bool requiresAvengerMark = false,
			bool requiresHeroSpellCast = false,
			bool requiresElementalFamily = false,
			bool requiresGatedIdentity = false,
			bool requiresCorpseCount = false,
			bool requiresWoundedUnit = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			DataOnly = dataOnly;
			DamagePercentBonus = damagePercentBonus;
			AttackDebuffPerHit = attackDebuffPerHit;
			DefenseDebuffPerHit = defenseDebuffPerHit;
			TemporaryManaPerCorpse = temporaryManaPerCorpse;
			SpeedDelta = speedDelta;
			RequiresPositiveMoraleValue = requiresPositiveMoraleValue;
			RequiresGunpowderDealer = requiresGunpowderDealer;
			RequiresCannonOrPirateDealer = requiresCannonOrPirateDealer;
			RequiresIsolatedTarget = requiresIsolatedTarget;
			RequiresDebuffedAttacker = requiresDebuffedAttacker;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresHeroSpellCast = requiresHeroSpellCast;
			RequiresElementalFamily = requiresElementalFamily;
			RequiresGatedIdentity = requiresGatedIdentity;
			RequiresCorpseCount = requiresCorpseCount;
			RequiresWoundedUnit = requiresWoundedUnit;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; final damage/buff/stat mutation point still required";
		}
	}

	internal readonly struct FormationProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly string HandlerKey;
		internal readonly bool DataOnly;
		internal readonly bool RequiresGunpowderOrPirate;
		internal readonly bool RequiresFirstVolley;
		internal readonly bool RequiresFocusOrReload;
		internal readonly bool RequiresGeometryPredicate;
		internal readonly bool RequiresNegativeStatusPredicate;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresConstructClassifier;
		internal readonly bool RequiresHeroSpellCast;
		internal readonly bool RequiresElementalFamilyMix;
		internal readonly bool RequiresGatedOrTeleportedIdentity;
		internal readonly bool RequiresLivingEnemyPredicate;
		internal readonly bool RequiresForwardMovementOrKill;
		internal readonly string EvidenceBoundary;

		internal FormationProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			string handlerKey,
			bool dataOnly = false,
			bool requiresGunpowderOrPirate = false,
			bool requiresFirstVolley = false,
			bool requiresFocusOrReload = false,
			bool requiresGeometryPredicate = false,
			bool requiresNegativeStatusPredicate = false,
			bool requiresAvengerMark = false,
			bool requiresConstructClassifier = false,
			bool requiresHeroSpellCast = false,
			bool requiresElementalFamilyMix = false,
			bool requiresGatedOrTeleportedIdentity = false,
			bool requiresLivingEnemyPredicate = false,
			bool requiresForwardMovementOrKill = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			HandlerKey = handlerKey;
			DataOnly = dataOnly;
			RequiresGunpowderOrPirate = requiresGunpowderOrPirate;
			RequiresFirstVolley = requiresFirstVolley;
			RequiresFocusOrReload = requiresFocusOrReload;
			RequiresGeometryPredicate = requiresGeometryPredicate;
			RequiresNegativeStatusPredicate = requiresNegativeStatusPredicate;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresConstructClassifier = requiresConstructClassifier;
			RequiresHeroSpellCast = requiresHeroSpellCast;
			RequiresElementalFamilyMix = requiresElementalFamilyMix;
			RequiresGatedOrTeleportedIdentity = requiresGatedOrTeleportedIdentity;
			RequiresLivingEnemyPredicate = requiresLivingEnemyPredicate;
			RequiresForwardMovementOrKill = requiresForwardMovementOrKill;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; battle action classification/effect mutation still required";
		}
	}

	internal readonly struct SpellCooldownProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly int CooldownDelta;
		internal readonly bool DataOnly;
		internal readonly bool RequiresSpellSchoolOrSidClass;
		internal readonly bool RequiresSupportBlessingClassification;
		internal readonly bool RequiresMovementStormSeaClassification;
		internal readonly bool RequiresNightCurseClassification;
		internal readonly bool RequiresEnemySlowPoisonMireState;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresOverclockCredit;
		internal readonly bool RequiresCastGateOverride;
		internal readonly bool RequiresElementalFamilyMapping;
		internal readonly bool RequiresSacrificeOrTemporaryLoss;
		internal readonly bool RequiresCorpseConsumption;
		internal readonly bool RequiresWarcryExecution;
		internal readonly string EvidenceBoundary;

		internal SpellCooldownProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			int cooldownDelta = 0,
			bool dataOnly = false,
			bool requiresSpellSchoolOrSidClass = false,
			bool requiresSupportBlessingClassification = false,
			bool requiresMovementStormSeaClassification = false,
			bool requiresNightCurseClassification = false,
			bool requiresEnemySlowPoisonMireState = false,
			bool requiresAvengerMark = false,
			bool requiresOverclockCredit = false,
			bool requiresCastGateOverride = false,
			bool requiresElementalFamilyMapping = false,
			bool requiresSacrificeOrTemporaryLoss = false,
			bool requiresCorpseConsumption = false,
			bool requiresWarcryExecution = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			CooldownDelta = cooldownDelta;
			DataOnly = dataOnly;
			RequiresSpellSchoolOrSidClass = requiresSpellSchoolOrSidClass;
			RequiresSupportBlessingClassification = requiresSupportBlessingClassification;
			RequiresMovementStormSeaClassification = requiresMovementStormSeaClassification;
			RequiresNightCurseClassification = requiresNightCurseClassification;
			RequiresEnemySlowPoisonMireState = requiresEnemySlowPoisonMireState;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresOverclockCredit = requiresOverclockCredit;
			RequiresCastGateOverride = requiresCastGateOverride;
			RequiresElementalFamilyMapping = requiresElementalFamilyMapping;
			RequiresSacrificeOrTemporaryLoss = requiresSacrificeOrTemporaryLoss;
			RequiresCorpseConsumption = requiresCorpseConsumption;
			RequiresWarcryExecution = requiresWarcryExecution;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; cooldown storage/cast gate/UI sync still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " cooldownDelta=" + CooldownDelta
			       + " dataOnly=" + DataOnly
			       + " requiresSpellSchoolOrSidClass=" + RequiresSpellSchoolOrSidClass
			       + " requiresSupportBlessingClassification=" + RequiresSupportBlessingClassification
			       + " requiresMovementStormSeaClassification=" + RequiresMovementStormSeaClassification
			       + " requiresNightCurseClassification=" + RequiresNightCurseClassification
			       + " requiresEnemySlowPoisonMireState=" + RequiresEnemySlowPoisonMireState
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresOverclockCredit=" + RequiresOverclockCredit
			       + " requiresCastGateOverride=" + RequiresCastGateOverride
			       + " requiresElementalFamilyMapping=" + RequiresElementalFamilyMapping
			       + " requiresSacrificeOrTemporaryLoss=" + RequiresSacrificeOrTemporaryLoss
			       + " requiresCorpseConsumption=" + RequiresCorpseConsumption
			       + " requiresWarcryExecution=" + RequiresWarcryExecution
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal readonly struct SpellSchoolProfile
	{
		internal readonly string FactionSid;
		internal readonly string LawName;
		internal readonly string EffectKey;
		internal readonly int Rank;
		internal readonly int LawIndex;
		internal readonly string HandlerKey;
		internal readonly bool DataOnly;
		internal readonly string NativeSchoolName;
		internal readonly string NativeAccessShape;
		internal readonly bool RequiresNativeSchoolVerification;
		internal readonly bool RequiresSpellCastEvent;
		internal readonly bool RequiresGunpowderOrRangedSupport;
		internal readonly bool RequiresFocusCredit;
		internal readonly bool RequiresPoisonSlowMovementRestriction;
		internal readonly bool RequiresNativeTerrainOrAdjacency;
		internal readonly bool RequiresAvengerMark;
		internal readonly bool RequiresSpellbookReuseState;
		internal readonly bool RequiresDynamicElementalFamily;
		internal readonly bool RequiresGatingSacrificeOrSummon;
		internal readonly bool RequiresCorpseOrCasualtyContext;
		internal readonly bool RequiresWarcryExecution;
		internal readonly string EvidenceBoundary;

		internal SpellSchoolProfile(
			string factionSid,
			string lawName,
			string effectKey,
			int rank,
			int lawIndex,
			string handlerKey,
			bool dataOnly = false,
			string nativeSchoolName = null,
			string nativeAccessShape = null,
			bool requiresNativeSchoolVerification = false,
			bool requiresSpellCastEvent = false,
			bool requiresGunpowderOrRangedSupport = false,
			bool requiresFocusCredit = false,
			bool requiresPoisonSlowMovementRestriction = false,
			bool requiresNativeTerrainOrAdjacency = false,
			bool requiresAvengerMark = false,
			bool requiresSpellbookReuseState = false,
			bool requiresDynamicElementalFamily = false,
			bool requiresGatingSacrificeOrSummon = false,
			bool requiresCorpseOrCasualtyContext = false,
			bool requiresWarcryExecution = false,
			string evidenceBoundary = null)
		{
			FactionSid = factionSid;
			LawName = lawName;
			EffectKey = effectKey;
			Rank = rank;
			LawIndex = lawIndex;
			HandlerKey = handlerKey;
			DataOnly = dataOnly;
			NativeSchoolName = nativeSchoolName;
			NativeAccessShape = nativeAccessShape;
			RequiresNativeSchoolVerification = requiresNativeSchoolVerification;
			RequiresSpellCastEvent = requiresSpellCastEvent;
			RequiresGunpowderOrRangedSupport = requiresGunpowderOrRangedSupport;
			RequiresFocusCredit = requiresFocusCredit;
			RequiresPoisonSlowMovementRestriction = requiresPoisonSlowMovementRestriction;
			RequiresNativeTerrainOrAdjacency = requiresNativeTerrainOrAdjacency;
			RequiresAvengerMark = requiresAvengerMark;
			RequiresSpellbookReuseState = requiresSpellbookReuseState;
			RequiresDynamicElementalFamily = requiresDynamicElementalFamily;
			RequiresGatingSacrificeOrSummon = requiresGatingSacrificeOrSummon;
			RequiresCorpseOrCasualtyContext = requiresCorpseOrCasualtyContext;
			RequiresWarcryExecution = requiresWarcryExecution;
			EvidenceBoundary = evidenceBoundary ?? "profile-only; spellbook access mutation, cast ordering, and UI synchronization still required";
		}

		public override string ToString()
		{
			return "faction=" + FactionSid
			       + " law=" + LawName
			       + " effect=" + EffectKey
			       + " rank=" + Rank
			       + " lawIndex=" + LawIndex
			       + " handler=" + HandlerKey
			       + " dataOnly=" + DataOnly
			       + " nativeSchool=" + (NativeSchoolName ?? "none")
			       + " nativeAccessShape=" + (NativeAccessShape ?? "none")
			       + " requiresNativeSchoolVerification=" + RequiresNativeSchoolVerification
			       + " requiresSpellCastEvent=" + RequiresSpellCastEvent
			       + " requiresGunpowderOrRangedSupport=" + RequiresGunpowderOrRangedSupport
			       + " requiresFocusCredit=" + RequiresFocusCredit
			       + " requiresPoisonSlowMovementRestriction=" + RequiresPoisonSlowMovementRestriction
			       + " requiresNativeTerrainOrAdjacency=" + RequiresNativeTerrainOrAdjacency
			       + " requiresAvengerMark=" + RequiresAvengerMark
			       + " requiresSpellbookReuseState=" + RequiresSpellbookReuseState
			       + " requiresDynamicElementalFamily=" + RequiresDynamicElementalFamily
			       + " requiresGatingSacrificeOrSummon=" + RequiresGatingSacrificeOrSummon
			       + " requiresCorpseOrCasualtyContext=" + RequiresCorpseOrCasualtyContext
			       + " requiresWarcryExecution=" + RequiresWarcryExecution
			       + " boundary=" + EvidenceBoundary;
		}
	}

	internal static bool TryGetCounterattackDoctrineProfile(
		string factionSid,
		int rank,
		Homm3CustomCounterattackLawRuntime.CounterattackAbilityObservation observation,
		out CounterattackDoctrineProfile profile,
		out string failReason)
	{
		profile = default;
		if (!observation.IsCounterAttackCandidate)
		{
			failReason = "counterattack doctrine profile requires EAbilityType.CounterAttack observation";
			return false;
		}
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new CounterattackDoctrineProfile(
				Castle,
				"Shield Wall",
				"castle.data.counterattack-damage",
				normalizedRank,
				dataOnly: true,
				evidenceBoundary: "Castle counterattack doctrine should remain native data-only unless exact runtime behavior is intentionally added");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new CounterattackDoctrineProfile(
				Cove,
				"Boarding Hooks",
				"cove.focus.on-counterattack",
				normalizedRank,
				focusDelta: 1,
				evidenceBoundary: "requires Focus write surface and committed counterattack correlation");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new CounterattackDoctrineProfile(
				Dungeon,
				"Outnumber",
				"dungeon.damage-vs-smaller-stack",
				normalizedRank,
				damagePercentBonus: 10,
				requiresTargetOutnumbered: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new CounterattackDoctrineProfile(
				Fortress,
				"Thorned Hides",
				"fortress.attack-debuff-on-counterattack",
				normalizedRank,
				attackDebuff: -1,
				evidenceBoundary: "requires exact native attack-debuff application surface");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new CounterattackDoctrineProfile(
				Rampart,
				"Avenger's Reprisal",
				"rampart.avenger-marked-counterattack-damage",
				normalizedRank,
				damagePercentBonus: 100,
				requiresAvengerMark: true,
				evidenceBoundary: "uses exact CounterAttack event plus custom Avenger marker SID state; no native buff/status mutation or faction-match inference");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new CounterattackDoctrineProfile(
				Tower,
				"Reactive Wards",
				"tower.spell-power-as-counterattack-attack",
				normalizedRank,
				requiresHeroSpellPower: true,
				evidenceBoundary: "requires defender hero spell-power read and damage formula injection point");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new CounterattackDoctrineProfile(
				Conflux,
				"Elemental Backlash",
				"conflux.extra-magic-damage-counterattack",
				normalizedRank,
				requiresSeparateMagicDamageSurface: true,
				evidenceBoundary: "must use a separate magic damage component; folding into physical damage is an explicit design compromise only");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new CounterattackDoctrineProfile(
				Inferno,
				"Hellfire Reprisal",
				"inferno.native-extra-counter-charge",
				normalizedRank,
				dataOnly: true,
				counterChargeDelta: 1,
				evidenceBoundary: "prefer native unitStat numCounters row; runtime profile is documentation only unless exact row is impossible");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new CounterattackDoctrineProfile(
				Necropolis,
				"Death Grip",
				"necropolis.counterattack-drain-restore",
				normalizedRank,
				drainPercent: normalizedRank >= 2 ? 20 : 10,
				evidenceBoundary: "requires final damage amount, lost-unit HP restore surface, and original-stack-size clamp");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new CounterattackDoctrineProfile(
				Stronghold,
				"Blood Feud",
				"stronghold.stacking-damage-buff-on-counterattack",
				normalizedRank,
				stackingDamagePercent: normalizedRank >= 2 ? 4 : 2,
				evidenceBoundary: "requires stack-scoped battle buff storage and cap before mutation");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for counterattack profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetMoraleTriggerProfile(
		string factionSid,
		int rank,
		Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation,
		out MoraleTriggerProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new MoraleTriggerProfile(
				Castle,
				"Righteous Zeal",
				"castle.native-morale-package",
				normalizedRank,
				usesPositiveCandidate: true,
				usesNegativeCandidate: false,
				evidenceBoundary: "Castle morale should remain native data-only unless exact runtime behavior is intentionally added");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			if (!observation.PositiveCandidateReturnedTrue)
			{
				failReason = "Cove Crew Nerve uses positive morale/momentum candidate only";
				return false;
			}
			profile = new MoraleTriggerProfile(
				Cove,
				"Crew Nerve",
				"cove.crew-momentum",
				normalizedRank,
				usesPositiveCandidate: true,
				usesNegativeCandidate: false,
				requiresKillOrLossEvent: true,
				evidenceBoundary: "requires kill/plunder/cannon/survive event correlation before applying morale, Focus, or speed");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			if (!observation.NegativeCandidateReturnedTrue)
			{
				failReason = "Dungeon Terror Exploitation uses enemy negative morale candidate only";
				return false;
			}
			profile = new MoraleTriggerProfile(
				Dungeon,
				"Terror Exploitation",
				"dungeon.enemy-morale-failure-exploit",
				normalizedRank,
				usesPositiveCandidate: false,
				usesNegativeCandidate: true,
				requiresOpposingLawOwner: true,
				evidenceBoundary: "requires opposing-side law owner; unit-owned morale gate is insufficient for enemy-failure laws");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new MoraleTriggerProfile(
				Fortress,
				"Cold-Blooded Endurance",
				"fortress.damage-taken-or-slow-poison-momentum",
				normalizedRank,
				usesPositiveCandidate: false,
				usesNegativeCandidate: false,
				requiresDamageTakenEvent: true,
				moraleDelta: 0,
				evidenceBoundary: "Fortress morale law is not driven by standard cheering; requires damage-taken or slow/poison application event");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new MoraleTriggerProfile(
				Rampart,
				"Defender's Grace",
				"rampart.protect-preserve-avenger-momentum",
				normalizedRank,
				usesPositiveCandidate: true,
				usesNegativeCandidate: false,
				requiresKillOrLossEvent: true,
				requiresAvengerMark: true,
				evidenceBoundary: "requires protect-adjacent ally, low-loss, or real Avenger mark event before applying morale");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new MoraleTriggerProfile(
				Tower,
				"Synchronization",
				"tower.construct-readiness-after-spell",
				normalizedRank,
				usesPositiveCandidate: false,
				usesNegativeCandidate: false,
				requiresSpellCastEvent: true,
				evidenceBoundary: "Tower morale law is construct readiness, not ordinary morale; requires spellcast-to-construct buff surface");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new MoraleTriggerProfile(
				Conflux,
				"Elemental Harmony",
				"conflux.elemental-family-resonance",
				normalizedRank,
				usesPositiveCandidate: true,
				usesNegativeCandidate: false,
				requiresElementalFamilyMix: true,
				evidenceBoundary: "requires exact elemental family mix before applying resonance; do not treat as ordinary morale alone");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new MoraleTriggerProfile(
				Inferno,
				"Frenzy",
				"inferno.death-sacrifice-gated-loss-momentum",
				normalizedRank,
				usesPositiveCandidate: false,
				usesNegativeCandidate: false,
				requiresKillOrLossEvent: true,
				requiresGatedOrSacrificeIdentity: true,
				evidenceBoundary: "requires temporary gated-loss/sacrifice identity; permanent casualties must not be conflated");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new MoraleTriggerProfile(
				Necropolis,
				"Dread",
				"necropolis.enemy-dread-and-corpse-value",
				normalizedRank,
				usesPositiveCandidate: false,
				usesNegativeCandidate: true,
				requiresOpposingLawOwner: true,
				requiresCorpseOrUndeadContext: true,
				evidenceBoundary: "Necropolis must not grant friendly undead morale; requires enemy-side dread or corpse context");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new MoraleTriggerProfile(
				Stronghold,
				"Rage",
				"stronghold.damage-kill-tempo",
				normalizedRank,
				usesPositiveCandidate: true,
				usesNegativeCandidate: false,
				requiresKillOrLossEvent: true,
				requiresDamageTakenEvent: true,
				evidenceBoundary: "requires damage-taken and kill event correlation before applying speed or damage tempo");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for morale profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetMoralePackageProfile(
		string factionSid,
		int rank,
		out MoralePackageProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new MoralePackageProfile(
				Castle,
				"Righteous Zeal",
				"castle.native-morale-package",
				normalizedRank,
				dataOnly: true,
				usesNativeFriendlyMoraleRows: true,
				usesNativeAdditionalActionRows: true,
				evidenceBoundary: "Castle morale package should stay native morale/additional-action rows unless exact runtime behavior is intentionally added");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new MoralePackageProfile(
				Cove,
				"Crew Nerve",
				"cove.kill-plunder-cannon-momentum-package",
				normalizedRank,
				requiresKillOrLossEvent: true,
				evidenceBoundary: "requires kill/plunder/cannon-hit/survive-ranged-fire event correlation before applying temporary morale, Focus, or speed");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new MoralePackageProfile(
				Dungeon,
				"Terror Exploitation",
				"dungeon.enemy-failure-debuff-package",
				normalizedRank,
				avoidsFriendlyMoraleBonus: true,
				requiresEnemyMoralePenalty: true,
				evidenceBoundary: "replaces friendly morale with enemy morale-failure/debuff exploitation; requires opposing-side context");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new MoralePackageProfile(
				Fortress,
				"Cold-Blooded Endurance",
				"fortress.damage-taken-slow-poison-package",
				normalizedRank,
				avoidsFriendlyMoraleBonus: true,
				requiresDamageTakenEvent: true,
				evidenceBoundary: "not standard cheering morale; requires damage-taken plus slow/poison application event proof");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new MoralePackageProfile(
				Rampart,
				"Defender's Grace",
				"rampart.protect-preserve-avenger-package",
				normalizedRank,
				requiresProtectOrPreserveEvent: true,
				requiresAvengerMark: true,
				requiresKillOrLossEvent: true,
				evidenceBoundary: "requires protect-adjacent ally, favored-enemy kill, low-loss, and actual Avenger custom marker hooks");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new MoralePackageProfile(
				Tower,
				"Synchronization",
				"tower.construct-readiness-package",
				normalizedRank,
				avoidsFriendlyMoraleBonus: true,
				requiresSpellCastEvent: true,
				requiresConstructClassifier: true,
				evidenceBoundary: "construct readiness should come from spellcast-to-construct buff, not ordinary morale on morale-neutral units");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new MoralePackageProfile(
				Conflux,
				"Elemental Harmony",
				"conflux.mixed-elemental-resonance-package",
				normalizedRank,
				avoidsFriendlyMoraleBonus: true,
				requiresElementalFamilyMix: true,
				evidenceBoundary: "mixed elemental families should produce battle-start/round resonance, not generic friendly morale");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new MoralePackageProfile(
				Inferno,
				"Frenzy",
				"inferno.death-sacrifice-gating-momentum-package",
				normalizedRank,
				requiresKillOrLossEvent: true,
				requiresGatedOrSacrificeIdentity: true,
				evidenceBoundary: "requires friendly death, sacrifice, and gated-loss identity; temporary gated losses must be separated from permanent casualties");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new MoralePackageProfile(
				Necropolis,
				"Dread",
				"necropolis.enemy-dread-corpse-package",
				normalizedRank,
				avoidsFriendlyMoraleBonus: true,
				requiresEnemyMoralePenalty: true,
				requiresCorpseOrUndeadContext: true,
				evidenceBoundary: "Necropolis should avoid positive undead morale and use enemy dread/corpse pressure instead");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new MoralePackageProfile(
				Stronghold,
				"Rage",
				"stronghold.damage-kill-rage-package",
				normalizedRank,
				requiresDamageTakenEvent: true,
				requiresKillOrLossEvent: true,
				requiresWarcryOrRageEvent: true,
				evidenceBoundary: "requires damage-taken/kill tempo and safe speed/damage buff cap; do not mutate turn order mid-action without proof");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for morale package profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetRewardEconomyProfile(
		string factionSid,
		int rank,
		string handlerKey,
		out RewardEconomyProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(handlerKey))
		{
			failReason = "reward economy handler key is required";
			return false;
		}

		var isCalendar = string.Equals(handlerKey, "reward.calendar", StringComparison.Ordinal);
		if (IsFaction(factionSid, Castle))
		{
			profile = new RewardEconomyProfile(
				Castle,
				isCalendar ? "Chapel Calendar" : "Prosperous Holdings",
				isCalendar ? "castle.native-astrology-income" : "castle.native-gold-percent",
				normalizedRank,
				handlerKey,
				dataOnly: true,
				evidenceBoundary: "Castle economy/calendar should remain native data-only unless exact runtime behavior is intentionally added");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new RewardEconomyProfile(
				Cove,
				isCalendar ? "Storm Omens" : "Prize Shares",
				isCalendar ? "cove.focus-storm-omens" : "cove.plunder-treasure-bank-gold",
				normalizedRank,
				handlerKey,
				requiresCommittedRewardIdentity: !isCalendar,
				evidenceBoundary: isCalendar
					? "requires Focus generation/spend or pirate/cannon attack event before omens are consumed"
					: "requires reward/capture source classification for plunder, treasure, creature banks, or defeated neutrals");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new RewardEconomyProfile(
				Dungeon,
				isCalendar ? "Deep Portents" : "Subjugated Mines",
				isCalendar ? "dungeon.first-night-spell-portent" : "dungeon.mine-guard-underground-income",
				normalizedRank,
				handlerKey,
				requiresCaptureOrOwnershipTransfer: !isCalendar,
				evidenceBoundary: isCalendar
					? "requires first Night spell/debuff mark event, not generic calendar income"
					: "requires ownership transfer or mine-guard combat completion proof");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new RewardEconomyProfile(
				Fortress,
				isCalendar ? "Witch Signs" : "Marsh Rights",
				isCalendar ? "fortress.poison-slow-calendar-sign" : "fortress.defensive-win-swamp-structure-income",
				normalizedRank,
				handlerKey,
				requiresBattleResultCasualties: !isCalendar,
				evidenceBoundary: isCalendar
					? "requires first poison/slow application or adjacent poisoned/slowed enemy context"
					: "requires defensive win or owned swamp-structure day-start source identity");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new RewardEconomyProfile(
				Rampart,
				isCalendar ? "Druidic Calendar" : "Preservation Tithe",
				isCalendar ? "rampart.cleanse-regeneration-cycle" : "rampart.low-loss-avenger-tithe",
				normalizedRank,
				handlerKey,
				requiresBattleResultCasualties: true,
				requiresAvengerMark: true,
				evidenceBoundary: "requires low-loss battle result or real Avenger mark interaction; no faction-match inference");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new RewardEconomyProfile(
				Tower,
				isCalendar ? "Celestial Calculus" : "Transmutation Ledger",
				isCalendar ? "tower.cooldown-construct-calculus" : "tower.rare-resource-transmutation",
				normalizedRank,
				handlerKey,
				requiresRareResourceBalance: !isCalendar,
				evidenceBoundary: isCalendar
					? "requires spellcast/cooldown or construct-artifice event; cooldown mutation still unproven"
					: "requires exact rare-resource balance read and capped conversion policy");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new RewardEconomyProfile(
				Conflux,
				isCalendar ? "Planar Calendar" : "Elemental Market",
				isCalendar ? "conflux.planar-day-phase" : "conflux.elemental-family-market",
				normalizedRank,
				handlerKey,
				requiresElementalFamilyMix: true,
				evidenceBoundary: "requires exact elemental family composition before market/calendar scaling");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new RewardEconomyProfile(
				Inferno,
				isCalendar ? "Infernal Signs" : "Soul Contract",
				isCalendar ? "inferno.fire-gated-signs" : "inferno.sacrifice-summoned-loss-economy",
				normalizedRank,
				handlerKey,
				requiresSacrificeOrTemporaryLoss: true,
				evidenceBoundary: "requires sacrifice/gated/summoned-loss identity; ordinary permanent casualties are not enough");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new RewardEconomyProfile(
				Necropolis,
				isCalendar ? "Death Moon" : "Mortuary Accounting",
				isCalendar ? "necropolis.corpse-raise-death-moon" : "necropolis.casualty-corpse-accounting",
				normalizedRank,
				handlerKey,
				requiresCorpseOrCasualtyContext: true,
				evidenceBoundary: "requires logical corpse/casualty state, not visual corpses or broad battle completion");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new RewardEconomyProfile(
				Stronghold,
				isCalendar ? "War Festival" : "Spoils Ledger",
				isCalendar ? "stronghold.warcry-festival" : "stronghold.raid-tribute-income",
				normalizedRank,
				handlerKey,
				requiresWarcryExecution: isCalendar,
				requiresCommittedRewardIdentity: !isCalendar,
				evidenceBoundary: isCalendar
					? "requires real Warcry execution hook"
					: "requires defeated neutral/capture reward identity; no broad all-combat income");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for reward economy profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetCalendarProfile(
		string factionSid,
		int rank,
		out CalendarProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new CalendarProfile(
				Castle,
				"Chapel Calendar",
				"castle.support-blessing-astrology-calendar",
				normalizedRank,
				requiresAstrologyProgressMutation: true,
				requiresSpellCastEvent: true,
				requiresBattleStartOrRoundEvent: true,
				evidenceBoundary: "native astrology income is data; support/blessing charges and first-combat blessing require exact spell/battle-start hooks");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new CalendarProfile(
				Cove,
				"Storm Omens",
				"cove.focus-storm-omen-calendar",
				normalizedRank,
				requiresFocusEvent: true,
				requiresBattleStartOrRoundEvent: true,
				evidenceBoundary: "requires Focus generation/spend and Pirate/Cannon ranged attack consumption; no passive all-ranged bonus");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new CalendarProfile(
				Dungeon,
				"Deep Portents",
				"dungeon.first-night-spell-portent-calendar",
				normalizedRank,
				requiresSpellCastEvent: true,
				evidenceBoundary: "requires first Night spell/debuff mark ordering before spell-level/effect scaling or target marking");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new CalendarProfile(
				Fortress,
				"Witch Signs",
				"fortress.poison-slow-duration-calendar",
				normalizedRank,
				requiresStatusDurationMutation: true,
				requiresBattleStartOrRoundEvent: true,
				evidenceBoundary: "requires first poison/slow application per battle and safe status duration/adjacent regeneration mutation");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new CalendarProfile(
				Rampart,
				"Druidic Calendar",
				"rampart.cleanse-regeneration-resistance-calendar",
				normalizedRank,
				requiresBattleStartOrRoundEvent: true,
				requiresStatusDurationMutation: true,
				evidenceBoundary: "requires actual debuff removal/regeneration/resistance cycle at battle start or unit turn start");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new CalendarProfile(
				Tower,
				"Celestial Calculus",
				"tower.cooldown-construct-calculus-calendar",
				normalizedRank,
				requiresSpellCastEvent: true,
				requiresCooldownMutation: true,
				requiresConstructClassifier: true,
				evidenceBoundary: "requires day-start calculation charges plus proven cooldown mutation or construct/artifice buff after spellcasts");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new CalendarProfile(
				Conflux,
				"Planar Calendar",
				"conflux.day-phase-elemental-calendar",
				normalizedRank,
				phaseModel: "day-modulo-elemental-phase",
				requiresBattleStartOrRoundEvent: true,
				requiresElementalFamilyMapping: true,
				evidenceBoundary: "requires deterministic day phase and dominant elemental family mapping before Fire/Air/Water/Earth or harmony buffs");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new CalendarProfile(
				Inferno,
				"Infernal Signs",
				"inferno.fire-gated-sign-calendar",
				normalizedRank,
				requiresSpellCastEvent: true,
				requiresStatusDurationMutation: true,
				requiresGatingSacrificeOrSummon: true,
				evidenceBoundary: "requires first fire damage marker plus gated/summoned entry and gated-loss/sacrifice identity");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new CalendarProfile(
				Necropolis,
				"Death Moon",
				"necropolis.corpse-raise-death-moon-calendar",
				normalizedRank,
				requiresAstrologyProgressMutation: true,
				requiresCorpseOrRaiseConsumption: true,
				evidenceBoundary: "requires actual corpse consumption/raise event before Astrology grant, raise/drain boost, or Dread pressure");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new CalendarProfile(
				Stronghold,
				"War Festival",
				"stronghold.warcry-festival-calendar",
				normalizedRank,
				requiresAstrologyProgressMutation: true,
				requiresWarcryExecution: true,
				requiresBattleStartOrRoundEvent: true,
				evidenceBoundary: "requires real Warcry execution and Warcry-followup kill hooks; no traditional spell cooldown assumptions");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for calendar profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetConstructionProfile(
		string factionSid,
		int rank,
		out ConstructionProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new ConstructionProfile(
				Castle,
				"Civic Engineers",
				"castle.native-extra-construction",
				normalizedRank,
				dataOnly: true,
				extraBuildCount: 1,
				evidenceBoundary: "Castle construction should remain native constructionDailyLimit data-only unless exact runtime behavior is intentionally added");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new ConstructionProfile(
				Cove,
				"Harbor Rush",
				"cove.harbor-infrastructure-extra-build",
				normalizedRank,
				extraBuildCount: 1,
				goldDiscountPercent: 20,
				requiresBuildingAllowlist: true,
				requiresDisplayedAndChargedCostParity: true,
				eligibleGroup: "market,tavern,cannon,pirate-infrastructure",
				evidenceBoundary: "requires exact Cove infrastructure building SID allowlist plus displayed/charged cost parity");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new ConstructionProfile(
				Dungeon,
				"Excavation Crews",
				"dungeon.capture-token-dwelling-build",
				normalizedRank,
				extraBuildCount: 1,
				requiresCaptureToken: true,
				requiresBuildingAllowlist: true,
				eligibleGroup: "dungeon-dwelling-build-or-upgrade",
				evidenceBoundary: "requires mine/cave/external-dwelling capture hook and side-scoped construction token");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new ConstructionProfile(
				Fortress,
				"Mudworks",
				"fortress-fortification-extra-build",
				normalizedRank,
				extraBuildCount: 1,
				woodOreDiscountPercent: 25,
				requiresBuildingAllowlist: true,
				requiresDisplayedAndChargedCostParity: true,
				eligibleGroup: "fortification,defensive-support",
				evidenceBoundary: "requires exact Fortress fortification/support building allowlist plus displayed/charged cost parity");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new ConstructionProfile(
				Rampart,
				"Living Groves",
				"rampart-mature-dwelling-upgrade",
				normalizedRank,
				extraBuildCount: 1,
				requiresPersistentMatureDwellingState: true,
				requiresBuildingAllowlist: true,
				eligibleGroup: "matured-dwelling-upgrade",
				evidenceBoundary: "requires durable mature-dwelling state before extra construction or discount can ship");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new ConstructionProfile(
				Tower,
				"Grand Workshop",
				"tower-magical-construct-workshop-slot",
				normalizedRank,
				extraBuildCount: 1,
				goldSurchargePercent: 50,
				requiresBuildingAllowlist: true,
				requiresDisplayedAndChargedCostParity: true,
				eligibleGroup: "magical,construct",
				evidenceBoundary: "requires normal-slot vs workshop-slot distinction and visible surcharge cost");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new ConstructionProfile(
				Conflux,
				"Planar Alignment",
				"conflux-elemental-alignment-build",
				normalizedRank,
				extraBuildCount: 1,
				requiresElementalBuildingMapping: true,
				requiresBuildingAllowlist: true,
				eligibleGroup: "elemental-building",
				evidenceBoundary: "requires exact town/building elemental alignment mapping");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new ConstructionProfile(
				Inferno,
				"Blood Mortar",
				"inferno-garrison-sacrifice-extra-build",
				normalizedRank,
				extraBuildCount: 1,
				sacrificeValuePercent: 25,
				requiresGarrisonSacrifice: true,
				requiresDisplayedAndChargedCostParity: true,
				evidenceBoundary: "requires safe deterministic garrison sacrifice worth at least 25% of gold cost");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new ConstructionProfile(
				Necropolis,
				"Reanimated Masonry",
				"necropolis-deathworks-credit-build",
				normalizedRank,
				extraBuildCount: 1,
				requiresDeathworksCredit: true,
				requiresBuildingAllowlist: true,
				eligibleGroup: "dwelling,converter",
				evidenceBoundary: "requires deathworks credit from casualties/captured dwellings; external dwelling conversion remains deferred");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new ConstructionProfile(
				Stronghold,
				"Warcamp Raising",
				"stronghold-military-extra-build",
				normalizedRank,
				extraBuildCount: 1,
				oreDiscountPercent: 20,
				requiresBuildingAllowlist: true,
				requiresDisplayedAndChargedCostParity: true,
				eligibleGroup: "military",
				evidenceBoundary: "requires exact military-building allowlist plus displayed/charged ore discount parity");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for construction profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetTrainingDamageProfile(
		string factionSid,
		int rank,
		out TrainingDamageProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new TrainingDamageProfile(
				Castle,
				"Officer Corps",
				"castle.damage-per-positive-morale",
				normalizedRank,
				damagePercentBonus: normalizedRank >= 2 ? 4 : 2,
				requiresPositiveMoraleValue: true,
				evidenceBoundary: "requires current positive Morale value at final damage calculation; do not change morale itself");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new TrainingDamageProfile(
				Cove,
				"Burning Ash",
				"cove.gunpowder-defense-debuff",
				normalizedRank,
				defenseDebuffPerHit: normalizedRank >= 2 ? -2 : -1,
				requiresGunpowderDealer: true,
				requiresCannonOrPirateDealer: false,
				evidenceBoundary: "candidate uses exact Cove gunpowder-unit committed-damage events and battle-local custom ash stacks; no native buff/status mutation and no Cannon/Pirate-only claim until that classifier exists");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new TrainingDamageProfile(
				Dungeon,
				"Predator's Instruction",
				"dungeon.isolated-target-damage",
				normalizedRank,
				damagePercentBonus: normalizedRank >= 2 ? 10 : 5,
				requiresIsolatedTarget: true,
				evidenceBoundary: "requires battle geometry helper and exact isolated predicate");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new TrainingDamageProfile(
				Fortress,
				"Hidebound Drill",
				"fortress.debuffed-attacker-damage-reduction",
				normalizedRank,
				damagePercentBonus: -10,
				requiresDebuffedAttacker: true,
				evidenceBoundary: "requires exact negative-status classification on attacker and outgoing damage hook");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new TrainingDamageProfile(
				Rampart,
				"Avenger's Tutelage",
				"rampart.avenger-vulnerability",
				normalizedRank,
				damagePercentBonus: RampartAvengerTutelageDamagePercent(normalizedRank),
				requiresAvengerMark: true,
				evidenceBoundary: "uses custom Avenger marker SID state on receiver; no native buff/status mutation and no faction-match inference");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new TrainingDamageProfile(
				Tower,
				"Arcane Calibration",
				"tower.spellcast-stacking-attack-defense",
				normalizedRank,
				requiresHeroSpellCast: true,
				evidenceBoundary: "requires successful spell cast hook and stackable timed battle buff cleanup");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new TrainingDamageProfile(
				Conflux,
				"Elemental Aspect",
				"conflux.family-stat-aspect",
				normalizedRank,
				damagePercentBonus: ConfluxElementalAspectDamagePercent(normalizedRank),
				requiresElementalFamily: true,
				evidenceBoundary: "requires exact elemental unit classifier; Fire/Earth/Air/Water split remains unimplemented");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new TrainingDamageProfile(
				Inferno,
				"Infernal Ascension",
				"inferno.gated-entry-damage",
				normalizedRank,
				damagePercentBonus: normalizedRank >= 2 ? 30 : 15,
				requiresGatedIdentity: true,
				evidenceBoundary: "requires Gating spawn/entry identity; permanent recruited units must not be affected");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new TrainingDamageProfile(
				Necropolis,
				"Corpse Wisdom",
				"necropolis.temp-mana-per-corpse",
				normalizedRank,
				temporaryManaPerCorpse: normalizedRank * 2,
				requiresCorpseCount: true,
				evidenceBoundary: "requires logical corpse count and temporary mana mutation/cleanup");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new TrainingDamageProfile(
				Stronghold,
				"Berserker Charge",
				"stronghold.wounded-speed",
				normalizedRank,
				speedDelta: normalizedRank >= 2 ? 2 : 1,
				requiresWoundedUnit: true,
				evidenceBoundary: "requires wounded threshold and safe turn-order refresh, preferably at round boundary");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for training damage profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetFormationProfile(
		string factionSid,
		int rank,
		string handlerKey,
		out FormationProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(handlerKey))
		{
			failReason = "formation handler key is required";
			return false;
		}

		if (IsFaction(factionSid, Castle))
		{
			profile = new FormationProfile(
				Castle,
				"Line Doctrine",
				"castle.native-formation",
				normalizedRank,
				handlerKey,
				dataOnly: true,
				evidenceBoundary: "Castle formation should remain vanilla/native rows unless exact runtime behavior is intentionally added");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new FormationProfile(
				Cove,
				handlerKey == "battle.ranged-formation" ? "Gun Decks" : "Boarding Parties",
				handlerKey == "battle.ranged-formation" ? "cove.first-gunpowder-volley" : "cove.pirate-adjacent-shooter-protection",
				normalizedRank,
				handlerKey,
				requiresGunpowderOrPirate: true,
				requiresFirstVolley: handlerKey == "battle.ranged-formation",
				requiresFocusOrReload: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new FormationProfile(
				Dungeon,
				"Kill Corridors",
				"dungeon.boxed-disabled-flanked-bonus",
				normalizedRank,
				handlerKey,
				requiresGeometryPredicate: true,
				requiresNegativeStatusPredicate: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new FormationProfile(
				Fortress,
				"Bog Line",
				"fortress.slow-poison-defensive-line",
				normalizedRank,
				handlerKey,
				requiresGeometryPredicate: true,
				requiresNegativeStatusPredicate: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new FormationProfile(
				Rampart,
				"Hunter Pairs",
				"rampart.protect-shooter-avenger-mark",
				normalizedRank,
				handlerKey,
				requiresGeometryPredicate: true,
				requiresAvengerMark: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new FormationProfile(
				Tower,
				"Battle Automata",
				"tower.construct-intercept-overcharge",
				normalizedRank,
				handlerKey,
				requiresConstructClassifier: true,
				requiresHeroSpellCast: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new FormationProfile(
				Conflux,
				"Elemental Conjunction",
				"conflux.mixed-elemental-composition",
				normalizedRank,
				handlerKey,
				requiresElementalFamilyMix: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new FormationProfile(
				Inferno,
				"Hellpack Assault",
				"inferno.gating-teleport-adjacency",
				normalizedRank,
				handlerKey,
				requiresGeometryPredicate: true,
				requiresGatedOrTeleportedIdentity: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new FormationProfile(
				Necropolis,
				"Death March",
				"necropolis.living-enemy-death-pressure",
				normalizedRank,
				handlerKey,
				requiresLivingEnemyPredicate: true,
				requiresNegativeStatusPredicate: true);
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new FormationProfile(
				Stronghold,
				"Warband Crush",
				"stronghold.forward-move-kill-armor-pressure",
				normalizedRank,
				handlerKey,
				requiresForwardMovementOrKill: true,
				requiresNegativeStatusPredicate: true);
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for formation profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetSpellCooldownProfile(
		string factionSid,
		int rank,
		out SpellCooldownProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new SpellCooldownProfile(
				Castle,
				"Liturgical Rhythm",
				"castle.daylight-support-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresSupportBlessingClassification: true,
				evidenceBoundary: "requires exact Daylight/support/blessing/cleanse/heal/morale/defense spell classification and UI sync");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new SpellCooldownProfile(
				Cove,
				"Reload Drills",
				"cove.movement-storm-sea-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresMovementStormSeaClassification: true,
				evidenceBoundary: "requires movement-control/storm/sea spell classification plus cannon/reload/Focus credit event");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new SpellCooldownProfile(
				Dungeon,
				"Cruel Momentum",
				"dungeon.night-curse-kill-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresNightCurseClassification: true,
				evidenceBoundary: "requires Night/curse spell classification and debuffed/disabled kill correlation for credits");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new SpellCooldownProfile(
				Fortress,
				"Bog Hex",
				"fortress.enemy-slow-poison-cooldown-penalty",
				normalizedRank,
				requiresEnemySlowPoisonMireState: true,
				evidenceBoundary: "requires enemy slowed/poisoned/mired army state; unconditional Absolute Zero shape is a design compromise only");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new SpellCooldownProfile(
				Rampart,
				"Avenger's Patience",
				"rampart.nature-protection-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresAvengerMark: true,
				evidenceBoundary: "requires Nature/protection/restoration spell classification plus custom Avenger marker SID interaction; temporary mana/cooldown UI sync not implemented");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new SpellCooldownProfile(
				Tower,
				"Overclocked Spellworks",
				"tower.overclock-cooldown-and-cast-gate",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresOverclockCredit: true,
				requiresCastGateOverride: true,
				evidenceBoundary: "requires exact Tower spell classification, overclock credit storage, and proven cast gate override for one-cooldown spells");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new SpellCooldownProfile(
				Conflux,
				"Aspect Cooldowns",
				"conflux.elemental-family-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresElementalFamilyMapping: true,
				evidenceBoundary: "requires exact spell element and dominant army elemental family mapping");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new SpellCooldownProfile(
				Inferno,
				"Sacrificial Casting",
				"inferno.fire-gating-sacrifice-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresSacrificeOrTemporaryLoss: true,
				evidenceBoundary: "requires fire/gating/summon spell classification and sacrifice/gated/summoned loss identity");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new SpellCooldownProfile(
				Necropolis,
				"Corpse Fuel",
				"necropolis.raise-drain-curse-corpse-cooldown",
				normalizedRank,
				cooldownDelta: -1,
				requiresSpellSchoolOrSidClass: true,
				requiresCorpseConsumption: true,
				evidenceBoundary: "requires raise/drain/curse/Night death spell classification and actual corpse consumption");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new SpellCooldownProfile(
				Stronghold,
				"Spellbreaker Chants",
				"stronghold.warcry-cooldown-tempo",
				normalizedRank,
				requiresWarcryExecution: true,
				evidenceBoundary: "requires real Warcry execution/cooldown path; Stronghold should not use traditional spell cooldown assumptions");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for spell cooldown profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetSpellSchoolProfile(
		string factionSid,
		int rank,
		int lawIndex,
		out SpellSchoolProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;
		if (!TryGetSpellSchoolHandlerKey(lawIndex, out var handlerKey, out failReason))
			return false;

		var nativeAccessShape = lawIndex == Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex
			? "magicSchoolSet school 0 1"
			: "magicSchoolSet school 5 0";

		if (IsFaction(factionSid, Castle))
		{
			profile = new SpellSchoolProfile(
				Castle,
				"Daylight Liturgy",
				"castle.native-daylight-access",
				normalizedRank,
				lawIndex,
				handlerKey,
				dataOnly: true,
				nativeSchoolName: "Daylight",
				nativeAccessShape: nativeAccessShape,
				evidenceBoundary: "native Daylight school access row only; runtime add-ons are not required for Castle");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new SpellSchoolProfile(
				Cove,
				"Storm Charts",
				"cove.space-arcane-gunpowder-support",
				normalizedRank,
				lawIndex,
				handlerKey,
				nativeSchoolName: "Space/Arcane",
				nativeAccessShape: nativeAccessShape,
				requiresNativeSchoolVerification: true,
				requiresSpellCastEvent: true,
				requiresGunpowderOrRangedSupport: true,
				requiresFocusCredit: true,
				evidenceBoundary: "native Space/Arcane school choice must match generated rows; runtime support requires exact spell cast and Cove gunpowder/Focus event correlation");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new SpellSchoolProfile(
				Dungeon,
				"Night Dominion",
				"dungeon.native-night-access",
				normalizedRank,
				lawIndex,
				handlerKey,
				dataOnly: true,
				nativeSchoolName: "Night",
				nativeAccessShape: nativeAccessShape,
				evidenceBoundary: "native Night access row is acceptable first pass because Night already contains curse/disable tools");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new SpellSchoolProfile(
				Fortress,
				"Bog Witchcraft",
				"fortress.primal-slow-poison-extension",
				normalizedRank,
				lawIndex,
				handlerKey,
				nativeSchoolName: "Primal",
				nativeAccessShape: nativeAccessShape,
				requiresSpellCastEvent: true,
				requiresPoisonSlowMovementRestriction: true,
				requiresNativeTerrainOrAdjacency: true,
				evidenceBoundary: "native Primal access can be data; runtime extension requires exact poison/slow/movement-restriction status and terrain/adjacency predicates");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new SpellSchoolProfile(
				Rampart,
				"Druidic Oath",
				"rampart.primal-protection-avenger",
				normalizedRank,
				lawIndex,
				handlerKey,
				nativeSchoolName: "Primal",
				nativeAccessShape: nativeAccessShape,
				requiresSpellCastEvent: true,
				requiresAvengerMark: true,
				evidenceBoundary: "native Primal access can be data; runtime add-on requires cleanse/resist/regeneration classification and custom Avenger marker SID state");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new SpellSchoolProfile(
				Tower,
				"Prepared Artifice",
				"tower.prepared-spellbook-reuse",
				normalizedRank,
				lawIndex,
				handlerKey,
				nativeSchoolName: "generator-profile-school",
				nativeAccessShape: nativeAccessShape,
				requiresNativeSchoolVerification: true,
				requiresSpellCastEvent: true,
				requiresSpellbookReuseState: true,
				evidenceBoundary: "base school must be read from the generator profile; spellbook reuse/prepared charges remain high risk and need spellbook state proof");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new SpellSchoolProfile(
				Conflux,
				"Elemental Wheel",
				"conflux.dynamic-elemental-school",
				normalizedRank,
				lawIndex,
				handlerKey,
				requiresDynamicElementalFamily: true,
				requiresSpellCastEvent: true,
				evidenceBoundary: "avoid static magicSchoolSet except as visible proxy; effective school access requires dominant elemental family computation");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new SpellSchoolProfile(
				Inferno,
				"Hellfire Gatecraft",
				"inferno.primal-fire-gating-charge",
				normalizedRank,
				lawIndex,
				handlerKey,
				nativeSchoolName: "Primal",
				nativeAccessShape: nativeAccessShape,
				requiresNativeSchoolVerification: true,
				requiresSpellCastEvent: true,
				requiresGatingSacrificeOrSummon: true,
				evidenceBoundary: "Primal access is acceptable only if fire/summon/gate spells live there; runtime charges require sacrifice/gated/summoned loss identity");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new SpellSchoolProfile(
				Necropolis,
				"Death Rite",
				"necropolis.night-corpse-rite",
				normalizedRank,
				lawIndex,
				handlerKey,
				nativeSchoolName: "Night",
				nativeAccessShape: nativeAccessShape,
				requiresSpellCastEvent: true,
				requiresCorpseOrCasualtyContext: true,
				evidenceBoundary: "native Night access can be data; runtime corpse/casualty boosts must integrate with real corpse consumption and Skeletal Necromancy bridge");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new SpellSchoolProfile(
				Stronghold,
				"Warcries",
				"stronghold.real-warcry-school-replacement",
				normalizedRank,
				lawIndex,
				handlerKey,
				requiresWarcryExecution: true,
				evidenceBoundary: "Stronghold should not use traditional school access; requires real Warcry execution/cooldown/ability path");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for spell school profile: " + (factionSid ?? "null");
		return false;
	}

	internal static bool TryGetVisionProfile(
		string factionSid,
		int rank,
		out VisionProfile profile,
		out string failReason)
	{
		profile = default;
		if (!NormalizeRank(rank, out var normalizedRank, out failReason))
			return false;

		if (IsFaction(factionSid, Castle))
		{
			profile = new VisionProfile(
				Castle,
				"Road Wardens",
				"castle.road-tile-view-radius",
				normalizedRank,
				viewRadiusDelta: 4,
				triggerContext: "hero-on-road",
				requiresRoadTerrain: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires native road terrain read before applying conditional +4 vision; do not replace with always-on view radius");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Cove))
		{
			profile = new VisionProfile(
				Cove,
				"Sea Charts",
				"cove.structure-scout-treasure-banks",
				normalizedRank,
				triggerContext: "owned-cove-town-or-dwelling",
				revealGroup: "treasure-cache,pirate-hideout,creature-bank,high-value-neutral-camp",
				requiresOwnedStructureRadius: true,
				requiresObjectSidOrCategoryAllowlist: true,
				requiresNeutralThreatData: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires explicit object SID/category allowlists and owned-structure reveal radius; no ocean-travel predicate");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Dungeon))
		{
			profile = new VisionProfile(
				Dungeon,
				"Deep Scouts",
				"dungeon.neutral-intention-preview",
				normalizedRank,
				triggerContext: "hero-proximity-to-neutral-stack",
				revealGroup: "neutral-intention-or-threat-preview",
				requiresNeutralThreatData: true,
				requiresReadOnlyTooltipPreview: true,
				evidenceBoundary: "requires native Read-Minds-style data or read-only tooltip preview; no hidden reward/fog mutation");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Fortress))
		{
			profile = new VisionProfile(
				Fortress,
				"Marsh Sense",
				"fortress.structure-reveal-enemy-heroes",
				normalizedRank,
				triggerContext: "side-turn-start-owned-fortress-or-swamp-structure",
				revealGroup: "nearby-enemy-heroes",
				requiresOwnedStructureRadius: true,
				requiresEnemyHeroPositions: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires exact owned Fortress town/dwelling/swamp structure ownership and enemy hero position reveal");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Rampart))
		{
			profile = new VisionProfile(
				Rampart,
				"Avenger's Trail",
				"rampart.avenger-marked-enemy-trail",
				normalizedRank,
				triggerContext: "avenger-mark-refresh",
				revealGroup: "last-known-or-nearest-avenger-marked-enemy",
				requiresAvengerMark: true,
				requiresEnemyHeroPositions: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "vision runtime abandoned for this pass; custom Avenger marker SID state is combat-local and not an adventure-map trail source");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Tower))
		{
			profile = new VisionProfile(
				Tower,
				"Observatory Network",
				"tower.structure-artifact-regional-reveal",
				normalizedRank,
				triggerContext: "owned-tower-town-or-observatory",
				revealGroup: "artifacts,small-region-around-observatory",
				requiresOwnedStructureRadius: true,
				requiresObjectSidOrCategoryAllowlist: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires exact artifact category/SID classification and structure-driven region reveal");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Conflux))
		{
			profile = new VisionProfile(
				Conflux,
				"Planar Attunement",
				"conflux.elemental-site-reveal",
				normalizedRank,
				triggerContext: "dominant-elemental-family-refresh",
				revealGroup: "elemental-shrine,elemental-dwelling,magic-site",
				requiresObjectSidOrCategoryAllowlist: true,
				requiresElementalFamilyMapping: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires explicit elemental-family mapping for both army and map object classification");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Inferno))
		{
			profile = new VisionProfile(
				Inferno,
				"Hellgate Omens",
				"inferno.existing-gate-site-reveal",
				normalizedRank,
				triggerContext: "side-turn-start-existing-inferno-map-objects",
				revealGroup: "pocket-dimension,teleporter,inferno-dwelling,summoning-site",
				requiresObjectSidOrCategoryAllowlist: true,
				requiresExistingMapObjectClasses: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires existing map object classes only; do not fabricate teleport or ocean mechanics");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Necropolis))
		{
			profile = new VisionProfile(
				Necropolis,
				"Gravesight",
				"necropolis.corpse-site-undead-reveal",
				normalizedRank,
				triggerContext: "owned-necropolis-structure-or-corpse-site-refresh",
				revealGroup: "graveyard,recent-battle-site,corpse-rich-location,undead-dwelling",
				requiresOwnedStructureRadius: true,
				requiresObjectSidOrCategoryAllowlist: true,
				requiresCorpseOrBattleSiteData: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires logical corpse/battle-site data or explicit object allowlist; visual corpse inference is not enough");
			failReason = null;
			return true;
		}
		if (IsFaction(factionSid, Stronghold))
		{
			profile = new VisionProfile(
				Stronghold,
				"War Scouts",
				"stronghold.weak-neutral-stack-scouting",
				normalizedRank,
				triggerContext: "hero-area-neutral-stack-scan",
				revealGroup: "easy-or-very-easy-neutral-stacks",
				requiresNeutralThreatData: true,
				requiresObjectSidOrCategoryAllowlist: true,
				requiresFogRevealMutation: true,
				evidenceBoundary: "requires native neutral strength/intention data; do not parse localized threat text");
			failReason = null;
			return true;
		}

		failReason = "unknown custom faction for vision profile: " + (factionSid ?? "null");
		return false;
	}

	private static bool NormalizeRank(int rank, out int normalizedRank, out string failReason)
	{
		normalizedRank = 0;
		if (rank <= 0)
		{
			failReason = "law rank must be positive";
			return false;
		}
		normalizedRank = rank > 3 ? 3 : rank;
		failReason = null;
		return true;
	}

	private static int RampartAvengerTutelageDamagePercent(int rank)
	{
		return rank >= 3 ? 30 : rank >= 2 ? 20 : 10;
	}

	private static int ConfluxElementalAspectDamagePercent(int rank)
	{
		return rank >= 3 ? 15 : rank >= 2 ? 10 : 5;
	}

	private static bool TryGetSpellSchoolHandlerKey(int lawIndex, out string handlerKey, out string failReason)
	{
		if (lawIndex == Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex)
		{
			handlerKey = "spell.low";
			failReason = null;
			return true;
		}
		if (lawIndex == Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex)
		{
			handlerKey = "spell.high";
			failReason = null;
			return true;
		}

		handlerKey = null;
		failReason = "spell school profile requires law index 15 or 27";
		return false;
	}

	private static bool IsFaction(string actual, string expected)
	{
		return string.Equals(actual, expected, StringComparison.Ordinal);
	}
}



