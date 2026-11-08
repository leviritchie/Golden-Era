namespace OfflineUnlockMod;

/// <summary>
/// Compile-time contract for RoE Castle Good1 campaign continuity.
/// Documents the native StoryHub / CampaignInfo handoff recipe for hero level
/// persistence. Core.zip install is opt-in via
/// tools/install_roe_castle_continuity_weave.py. Does not alter the Homecoming
/// playable-shell launch path (empty CampaignInfo).
///
/// Proof boundary: source/static constants + deployed-payload when installed.
/// Runtime session→hub writeback and strongest-N selection remain unvalidated.
/// </summary>
internal static class Homm3CampaignContinuityContract
{
	internal const string HubSid = "homm3_01_roe_castle_good1";
	/// <summary>
	/// BhCampaign.Init LocKit key is "campaign_" + HubSid. Missing this SID shows LOC:.
	/// </summary>
	internal const string CampaignLocKitSid = "campaign_homm3_01_roe_castle_good1";
	internal const string CampaignTitle = "Long Live the Queen";
	/// <summary>
	/// Native StoryHub UI ships six BhFractionReputation slots. fractions.json must
	/// match that length or BhFractionsReputation.Init hard-crashes on hub enter.
	/// </summary>
	internal const int NativeStoryHubFractionSlotCount = 6;
	internal const string CampaignEntry = "Good1.h3c";
	internal const string CarryPolicyRelativePath = "scenarios/roe_castle_campaign/continuity_carry_policy.v1.json";
	internal const string WeaveArtifactRelativePath =
		"artifacts/campaign_port_poc/roe_castle_campaign/continuity_weave/continuity.weave.v1.json";
	internal const string InstallerRelativePath = "tools/install_roe_castle_continuity_weave.py";

	internal const bool TransferHeroProgressFromSessionRequired = true;
	/// <summary>
	/// Set true after opt-in Core.zip install. Validator expects true when the live
	/// Golden Era Core.zip already contains campaigns/homm3_01_roe_castle_good1/.
	/// </summary>
	internal const bool InstalledIntoCoreZip = true;

	internal const string FirstMissionId = "homecoming";
	internal const string SecondMissionId = "guardian_angels";
	/// <summary>
	/// StoryHub mission mapSids. raw_translation is the only campaign map generation
	/// lane, so every hub mission SID carries the _raw_translation suffix that
	/// tools/install_roe_castle_continuity_weave.py actually installs.
	/// </summary>
	internal const string FirstMapSid = "h3_roe_castle_homecoming_raw_translation";
	internal const string SecondMapSid = "h3_roe_castle_guardian_angels_raw_translation";
	internal const string ThirdMapSid = "h3_roe_castle_griffin_cliff_raw_translation";

	internal const int HomecomingLevelCap = 6;
	internal const int StrongestHeroesCarryCount = 4;

	/// <summary>
	/// StoryHub BhDifficulties indices 0-3 (Easy..Expert) are available.
	/// Index 4 Impossible stays locked to match HoMM3's four campaign difficulties.
	/// </summary>
	internal const int AvailableDifficultyCount = 4;
	internal const bool ImpossibleDifficultyAvailable = false;
	internal const string BonusDifficultyPolicyRelativePath =
		"scenarios/roe_castle_campaign/continuity_bonus_difficulty.v1.json";
	/// <summary>
	/// HoMM3 starting-bonus MissionVariant UI is not shipped: heroesArmies replaces map
	/// spawn armies and StoryHub has no mission-start item grant action.
	/// </summary>
	internal const bool StartingBonusSelectionImplemented = false;

	internal static readonly string[] MissionChain =
	{
		"homecoming",
		"guardian_angels",
		"griffin_cliff",
	};

	internal static readonly string[] MinimumFaithfulCarryDimensions =
	{
		"experience",
		"primarySkills",
		"secondarySkills",
		"spells",
		"artifacts",
	};

	internal static readonly string[] DeferredExplicitLossDimensions =
	{
		"keepCreatures",
	};

	internal const string PlayableShellCampaignInfoFactory =
		"Plugin.CreateHomecomingPlayableShellCampaignInfo";

	internal const string UiClickPathSummary =
		"Main Menu → Campaign/Profiles → Long Live the Queen (homm3_01_roe_castle_good1) → "
		+ "Homecoming node → Select Difficulty (Easy/Normal/Difficult/Expert) → Start Game "
		+ "(map under maps/Story_maps/); hero portrait must not crash; "
		+ "after victory open Guardian Angels and check hero level. "
		+ "Starting-bonus choices are not shown yet (see continuity_bonus_difficulty.v1.json).";

	internal const string LevelPersistenceProofSummary =
		"Launch via StoryHub OpenMissionsPrologue with transferHeroProgressFromSession=true; "
		+ "complete Homecoming; read StoryHubSave.heroesSaves level/experience; "
		+ "start Guardian Angels and confirm the same hero sheet; "
		+ "separately prove strongest-4 selection (do not equate all-heroes transfer with HoMM3).";
}
