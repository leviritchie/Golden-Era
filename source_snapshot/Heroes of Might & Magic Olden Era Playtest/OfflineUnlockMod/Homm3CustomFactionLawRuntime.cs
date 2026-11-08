using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Shared custom-faction law helpers. This is intentionally diagnostic-only for
/// the first implementation slice: gameplay hooks must prove their native
/// surfaces before they consume this resolver for state mutation.
/// </summary>
internal static class Homm3CustomFactionLawRuntime
{
	internal const string DiagnosticFlag = "homm3_custom_faction_law_diag.flag";
	internal const string ProfileCatalogDiagnosticFlag = "homm3_custom_law_profile_catalog_diag.flag";
	internal const string NativeLawSeedDiagnosticFlag = "homm3_custom_faction_law_seed_diag.flag";
	private const string LawPrefix = "fraction_law_";
	private const string NativeLawSeedFactionSid = "homm3_castle";
	private const int NativeLawSeedIndex = HeroPrimaryStatTrainingIndex;
	private const int NativeLawSeedRank = 1;
	internal const int HeroSightRadiusIndex = 2;
	internal const int HeroPrimaryStatTrainingIndex = 6;
	internal const int CounterstrokeDoctrineIndex = 13;
	internal const int SpellSchoolAccessLowIndex = 15;
	internal const int MeleeFormationIndex = 18;
	internal const int RangedFormationIndex = 19;
	internal const int FormationIndex = RangedFormationIndex;
	internal const int CounterattackIndex = CounterstrokeDoctrineIndex;
	internal const int GoldIncomePercentIndex = 21;
	internal const int MoraleFlatIndex = 22;
	internal const int MoraleTriggerIndex = 25;
	internal const int SpellSchoolAccessHighIndex = 27;
	internal const int ExtraConstructionIndex = 28;
	internal const int AstrologyCalendarIncomeIndex = 33;
	internal const int SpellCooldownModifierIndex = 34;

	internal const string HeroSightRadiusFamily = "Hero sight radius";
	internal const string HeroPrimaryStatTrainingFamily = "Hero primary-stat training";
	internal const string CounterstrokeDoctrineFamily = "Counterattack doctrine";
	internal const string SpellSchoolAccessFamily = "Spell school access";
	internal const string FormationFamily = "Melee and ranged formations";
	internal const string GoldIncomePercentFamily = "Gold income percent";
	internal const string MoraleFamily = "Morale and morale triggers";
	internal const string ExtraConstructionFamily = "Extra construction";
	internal const string AstrologyCalendarIncomeFamily = "Astrology/calendar income";
	internal const string SpellCooldownModifierFamily = "Spell cooldown modifier";

	internal static readonly int[] KnownRuntimeLawIndices =
	{
		HeroSightRadiusIndex,
		HeroPrimaryStatTrainingIndex,
		CounterstrokeDoctrineIndex,
		SpellSchoolAccessLowIndex,
		MeleeFormationIndex,
		RangedFormationIndex,
		GoldIncomePercentIndex,
		MoraleFlatIndex,
		MoraleTriggerIndex,
		SpellSchoolAccessHighIndex,
		ExtraConstructionIndex,
		AstrologyCalendarIncomeIndex,
		SpellCooldownModifierIndex,
	};

	private static bool _registered;
	private static int _loggedBind;
	private static int _loggedRefresh;
	private static int _loggedPreseed;
	private static int _loggedPreseedLawRanks;
	private static int _loggedNativeLawSeed;
	private static int _loggedNativeLawCanApply;
	private static int _loggedNativeLawApply;
	private static bool _nativeLawSeedAttempted;
	private static bool _nativeLawSeedApplied;
	private static readonly Dictionary<int, object> LogicFractionLawsBySideIndex = new Dictionary<int, object>();
	private static readonly Dictionary<int, object> DataSidesBySideIndex = new Dictionary<int, object>();
	private static object _lastLawTreeLogicSide;
	private static object _lastLawTreeDataSide;

	internal struct NativeLawStateBridgeResult
	{
		internal string FactionSid;
		internal string LawSid;
		internal string Family;
		internal int Index;
		internal int RequestedRank;
		internal int CurrentLevel;
		internal int Line;
		internal int Group;
		internal bool WasAppliedKnown;
		internal bool WasApplied;
		internal bool CanApplyKnown;
		internal bool CanApply;
		internal bool RankEligibleKnown;
		internal bool RankEligible;
		internal bool LineVisibleKnown;
		internal bool LineVisible;
		internal bool CostKnown;
		internal int Cost;
		internal bool SpentPointsKnown;
		internal int SpentPoints;
		internal bool UnlockedLineKnown;
		internal int UnlockedLine;
		internal bool LineRequirementKnown;
		internal int LineRequirement;
		internal bool NativeSideLevelKnown;
		internal int NativeSideLevel;
		internal bool NativeLawPointsKnown;
		internal int NativeLawPoints;
		internal bool NativeCanAffordCostKnown;
		internal bool NativeCanAffordCost;
		internal bool ApplyRequested;
		internal bool ApplyInvoked;
		internal string ApplyFailure;
		internal string Source;
		internal string BeforeSummary;
		internal string AfterSummary;

		internal string ToJson()
		{
			var sb = new StringBuilder();
			sb.Append("\"factionSid\":\"").Append(JsonEscape(FactionSid)).Append("\"");
			sb.Append(",\"lawSid\":\"").Append(JsonEscape(LawSid)).Append("\"");
			sb.Append(",\"family\":\"").Append(JsonEscape(Family)).Append("\"");
			sb.Append(",\"index\":").Append(Index.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"requestedRank\":").Append(RequestedRank.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"currentLevel\":").Append(CurrentLevel.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"line\":").Append(Line.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"group\":").Append(Group.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"wasAppliedKnown\":").Append(WasAppliedKnown ? "true" : "false");
			if (WasAppliedKnown) sb.Append(",\"wasApplied\":").Append(WasApplied ? "true" : "false");
			sb.Append(",\"canApplyKnown\":").Append(CanApplyKnown ? "true" : "false");
			if (CanApplyKnown) sb.Append(",\"canApply\":").Append(CanApply ? "true" : "false");
			sb.Append(",\"rankEligibleKnown\":").Append(RankEligibleKnown ? "true" : "false");
			if (RankEligibleKnown) sb.Append(",\"rankEligible\":").Append(RankEligible ? "true" : "false");
			sb.Append(",\"lineVisibleKnown\":").Append(LineVisibleKnown ? "true" : "false");
			if (LineVisibleKnown) sb.Append(",\"lineVisible\":").Append(LineVisible ? "true" : "false");
			sb.Append(",\"costKnown\":").Append(CostKnown ? "true" : "false");
			if (CostKnown) sb.Append(",\"cost\":").Append(Cost.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"spentPointsKnown\":").Append(SpentPointsKnown ? "true" : "false");
			if (SpentPointsKnown) sb.Append(",\"spentPoints\":").Append(SpentPoints.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"unlockedLineKnown\":").Append(UnlockedLineKnown ? "true" : "false");
			if (UnlockedLineKnown) sb.Append(",\"unlockedLine\":").Append(UnlockedLine.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"lineRequirementKnown\":").Append(LineRequirementKnown ? "true" : "false");
			if (LineRequirementKnown) sb.Append(",\"lineRequirement\":").Append(LineRequirement.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"nativeSideLevelKnown\":").Append(NativeSideLevelKnown ? "true" : "false");
			if (NativeSideLevelKnown) sb.Append(",\"nativeSideLevel\":").Append(NativeSideLevel.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"nativeLawPointsKnown\":").Append(NativeLawPointsKnown ? "true" : "false");
			if (NativeLawPointsKnown) sb.Append(",\"nativeLawPoints\":").Append(NativeLawPoints.ToString(System.Globalization.CultureInfo.InvariantCulture));
			sb.Append(",\"nativeCanAffordCostKnown\":").Append(NativeCanAffordCostKnown ? "true" : "false");
			if (NativeCanAffordCostKnown) sb.Append(",\"nativeCanAffordCost\":").Append(NativeCanAffordCost ? "true" : "false");
			sb.Append(",\"applyRequested\":").Append(ApplyRequested ? "true" : "false");
			sb.Append(",\"applyInvoked\":").Append(ApplyInvoked ? "true" : "false");
			if (!string.IsNullOrWhiteSpace(ApplyFailure)) sb.Append(",\"applyFailure\":\"").Append(JsonEscape(ApplyFailure)).Append("\"");
			sb.Append(",\"source\":\"").Append(JsonEscape(Source)).Append("\"");
			sb.Append(",\"before\":\"").Append(JsonEscape(BeforeSummary)).Append("\"");
			sb.Append(",\"after\":\"").Append(JsonEscape(AfterSummary)).Append("\"");
			return sb.ToString();
		}
	}

	internal struct ActiveLawState
	{
		internal string FactionSid;
		internal string LawSid;
		internal string Family;
		internal int Index;
		internal int Rank;
		internal int Line;
		internal int Group;
		internal bool WasApplied;

		public override string ToString()
		{
			return "faction='" + FactionSid
			       + "' law='" + LawSid
			       + "' index=" + Index
			       + " rank=" + Rank
			       + " family='" + Family
			       + "' line=" + Line
			       + " group=" + Group
			       + " wasApplied=" + WasApplied;
		}
	}

	internal enum ActiveLawResolutionKind
	{
		Present,
		Absent,
		Failed,
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		var diagnosticEnabled = Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag);
		var profileCatalogEnabled = Homm3DiagnosticFlags.IsEnabled(ProfileCatalogDiagnosticFlag);
		if (!diagnosticEnabled && !profileCatalogEnabled)
			return;
		_registered = true;

		if (diagnosticEnabled)
		{
			log?.LogInfo("Homm3CustomFactionLawRuntime: diagnostic scaffold active; gameplay law hooks are registered by dedicated runtime classes, not by this resolver diagnostic.");
			log?.LogInfo("Homm3CustomFactionLawRuntime: known runtime families use law indices " + string.Join(",", KnownRuntimeLawIndices) + "; runtime-only mechanics must fail closed until probed.");
			log?.LogInfo("Homm3CustomFactionLawRuntime: variable donor unit/tier law slots and Resource Riches are intentionally not in KnownRuntimeLawIndices.");
			log?.LogInfo("Homm3CustomFactionLawRuntime: law-rank diagnostics use exact generated Data/Logic law members only; this diagnostic does not perform gameplay mutation.");
			if (Homm3DiagnosticFlags.IsEnabled(NativeLawSeedDiagnosticFlag))
				log?.LogWarning("Homm3CustomFactionLawRuntime: native law seed diagnostic enabled; will attempt one exact Logic.FractionLaws apply for "
					+ MakeLawId(NativeLawSeedFactionSid, NativeLawSeedIndex)
					+ " rank=" + NativeLawSeedRank.ToString(System.Globalization.CultureInfo.InvariantCulture)
					+ ". This is diagnostic-only and must not be treated as packet gameplay proof.");
			log?.LogInfo("Homm3CustomFactionLawRuntime: packet proof gate states: " + Homm3CustomLawPacketGate.DescribeKnownProofStates());
			log?.LogInfo("Homm3CustomFactionLawRuntime: no-compromise handler slots: " + Homm3CustomLawHandlerRegistry.DescribeHandlerSlots());
			log?.LogInfo("Homm3CustomFactionLawRuntime: source-prepared implementation seams: " + Homm3CustomLawImplementationCatalog.Describe());
			var patched = TryPatchLawViewDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: law-rank diagnostic surface patches registered=" + patched + ".");
			var dataSideInitPatches = TryPatchDataSideInitPreseedDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: Data.Side init preseed diagnostic patches registered=" + dataSideInitPatches + ". Diagnostic observation only.");
			var dataSidePatches = TryPatchDataSidesPreseedDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: DataSides preseed diagnostic patches registered=" + dataSidePatches + ". Diagnostic observation only.");
			var dataRootPatches = TryPatchDataRootPreseedDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: Data root preseed diagnostic patches registered=" + dataRootPatches + ". Diagnostic observation only.");
			var logicSidePatches = TryPatchLogicSidePreseedDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: Logic side preseed diagnostic patches registered=" + logicSidePatches + ". Diagnostic observation only.");
			var logicRootPatches = TryPatchLogicRootPreseedDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: Logic root side-collection preseed diagnostic patches registered=" + logicRootPatches + ". Diagnostic observation only.");
			var nativeActivationPatches = TryPatchNativeLawActivationDiagnostics(harmony, log);
			log?.LogInfo("Homm3CustomFactionLawRuntime: native FractionLaws activation diagnostic patches registered=" + nativeActivationPatches + ". Diagnostic observation only.");
			Homm3BattleUnitLawOwnerRegistry.TryRegister(harmony, log);
		}

		if (profileCatalogEnabled)
			LogSourcePreparedProfileCatalog(log);
	}

	private static void LogSourcePreparedProfileCatalog(ManualLogSource log)
	{
		log?.LogInfo("Homm3CustomFactionLawRuntime: source-prepared law profile catalog requested by " + ProfileCatalogDiagnosticFlag + ". Synthetic counterattack/morale rows are design metadata only; no gameplay packet is promoted.");
		var lines = Homm3CustomLawImplementationCatalog.DescribeSourcePreparedProfileCatalogLines();
		for (var i = 0; i < lines.Length; i++)
			log?.LogInfo("Homm3CustomFactionLawRuntime profileCatalog[" + i + "]: " + lines[i]);
	}

	internal static string MakeLawId(string factionSid, int index)
	{
		if (string.IsNullOrWhiteSpace(factionSid) || index <= 0)
			return string.Empty;
		return LawPrefix + factionSid.Trim() + "_" + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
	}

	internal static bool TryParseCustomLawId(string lawSid, out string factionSid, out int index)
	{
		return TryParseKnownCustomLawId(lawSid, out factionSid, out index, out _);
	}

	private static bool TryParseAnyCustomFactionLawId(string lawSid, out string factionSid, out int index)
	{
		factionSid = null;
		index = 0;
		if (string.IsNullOrWhiteSpace(lawSid) || !lawSid.StartsWith(LawPrefix, StringComparison.Ordinal))
			return false;

		var body = lawSid.Substring(LawPrefix.Length);
		var split = body.LastIndexOf('_');
		if (split <= 0 || split >= body.Length - 1)
			return false;
		if (!int.TryParse(body.Substring(split + 1), out index) || index <= 0)
			return false;

		factionSid = body.Substring(0, split);
		return Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid);
	}	internal static bool TryParseKnownCustomLawId(string lawSid, out string factionSid, out int index, out string family)
	{
		factionSid = null;
		index = 0;
		family = null;
		if (string.IsNullOrWhiteSpace(lawSid) || !lawSid.StartsWith(LawPrefix, StringComparison.Ordinal))
			return false;

		var body = lawSid.Substring(LawPrefix.Length);
		var split = body.LastIndexOf('_');
		if (split <= 0 || split >= body.Length - 1)
			return false;
		if (!int.TryParse(body.Substring(split + 1), out index) || index <= 0)
			return false;

		factionSid = body.Substring(0, split);
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return false;
		return TryGetKnownLawFamily(index, out family);
	}

	internal static bool TryGetKnownLawFamily(int index, out string family)
	{
		switch (index)
		{
			case HeroSightRadiusIndex: family = HeroSightRadiusFamily; return true;
			case HeroPrimaryStatTrainingIndex: family = HeroPrimaryStatTrainingFamily; return true;
			case CounterstrokeDoctrineIndex: family = CounterstrokeDoctrineFamily; return true;
			case SpellSchoolAccessLowIndex:
			case SpellSchoolAccessHighIndex: family = SpellSchoolAccessFamily; return true;
			case MeleeFormationIndex:
			case RangedFormationIndex: family = FormationFamily; return true;
			case GoldIncomePercentIndex: family = GoldIncomePercentFamily; return true;
			case MoraleFlatIndex:
			case MoraleTriggerIndex: family = MoraleFamily; return true;
			case ExtraConstructionIndex: family = ExtraConstructionFamily; return true;
			case AstrologyCalendarIncomeIndex: family = AstrologyCalendarIncomeFamily; return true;
			case SpellCooldownModifierIndex: family = SpellCooldownModifierFamily; return true;
			default: family = null; return false;
		}
	}

	internal static bool TryResolveActiveKnownCustomLaw(object sideOrLawOwner, int lawIndex, out ActiveLawState state)
	{
		state = default;
		if (sideOrLawOwner == null || lawIndex <= 0)
			return false;
		if (!TryGetKnownLawFamily(lawIndex, out _))
			return false;
		if (TryResolveActiveKnownCustomLawFromLogic(sideOrLawOwner, lawIndex, out state))
			return true;
		if (!TryResolveDataFractionLaws(sideOrLawOwner, out var dataFractionLaws))
			return false;
		if (!TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var factionSid))
			return false;
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return false;
		var expectedLawSid = MakeLawId(factionSid, lawIndex);
		if (string.IsNullOrEmpty(expectedLawSid))
			return false;
		if (!TryReadExactObject(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListMembers, out var lawsList))
			return false;
		if (!TryFindDataFractionLaw(lawsList, expectedLawSid, out var dataLaw))
			return false;
		return TryBuildActiveLawState(dataLaw, factionSid, expectedLawSid, lawIndex, out state);
	}

	internal static ActiveLawResolutionKind ResolveActiveKnownCustomLawState(
		object sideOrLawOwner,
		int lawIndex,
		out ActiveLawState state,
		out string detail)
	{
		state = default;
		detail = ExplainActiveKnownCustomLawResolution(sideOrLawOwner, lawIndex);
		if (sideOrLawOwner == null
		    || lawIndex <= 0
		    || !TryGetKnownLawFamily(lawIndex, out _)
		    || !TryResolveDataFractionLawsExplained(sideOrLawOwner, out var dataFractionLaws, out _))
			return ActiveLawResolutionKind.Failed;
		if (!TryReadExactString(
			    dataFractionLaws,
			    GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers,
			    out var factionSid))
			return ActiveLawResolutionKind.Failed;
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return ActiveLawResolutionKind.Absent;
		var expectedLawSid = MakeLawId(factionSid, lawIndex);
		if (string.IsNullOrEmpty(expectedLawSid))
			return ActiveLawResolutionKind.Failed;
		if (!TryReadExactObject(
			    dataFractionLaws,
			    GameSymbols.CustomFactionLawRuntime.DataFractionLawsListMembers,
			    out var lawsList))
			return ActiveLawResolutionKind.Failed;
		if (!TryFindDataFractionLaw(lawsList, expectedLawSid, out var dataLaw))
			return ActiveLawResolutionKind.Absent;
		if (!TryReadExactInt(
			    dataLaw,
			    GameSymbols.CustomFactionLawRuntime.DataFractionLawLevelMembers,
			    out var rank))
			return ActiveLawResolutionKind.Failed;
		if (rank <= 0)
			return ActiveLawResolutionKind.Absent;
		if (!TryReadExactBool(
			    dataLaw,
			    GameSymbols.CustomFactionLawRuntime.DataFractionLawWasAppliedMembers,
			    out var wasApplied))
			return ActiveLawResolutionKind.Failed;
		if (!wasApplied)
			return ActiveLawResolutionKind.Absent;
		if (!TryReadExactInt(
			    dataLaw,
			    GameSymbols.CustomFactionLawRuntime.DataFractionLawLineMembers,
			    out _)
		    || !TryReadExactInt(
			    dataLaw,
			    GameSymbols.CustomFactionLawRuntime.DataFractionLawGroupMembers,
			    out _))
			return ActiveLawResolutionKind.Failed;
		return TryBuildActiveLawState(dataLaw, factionSid, expectedLawSid, lawIndex, out state)
			? ActiveLawResolutionKind.Present
			: ActiveLawResolutionKind.Failed;
	}

	internal static bool TryDescribeNativeLawStateForBridge(string lawSid, int requestedRank, bool applyIfCan, out string json, out string failure)
	{
		json = null;
		failure = null;
		if (string.IsNullOrWhiteSpace(lawSid)) { failure = "lawSid is required"; return false; }
		if (requestedRank < 1 || requestedRank > 3) { failure = "requestedRank must be 1, 2, or 3"; return false; }
		if (!TryParseKnownCustomLawId(lawSid, out var factionSid, out var lawIndex, out var family))
		{
			if (!TryParseAnyCustomFactionLawId(lawSid, out factionSid, out lawIndex)) { failure = "lawSid is not a valid custom faction law SID: " + lawSid; return false; }
			family = "native-or-donor law row";
		}
		if (!TryResolveNativeLawContext(factionSid, out var logicFractionLaws, out _, out var source, out var contextFailure)) { failure = contextFailure; return false; }
		if (!TryInvokeExactObjectMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawBySidMethods, new object[] { lawSid }, out var logicLaw) || logicLaw == null) { failure = "exact native law wrapper lookup failed for " + lawSid + " from " + source; return false; }
		if (!TryExtractDataFractionLawForDiagnostic(logicLaw, out var dataLaw)) { failure = "exact DataFractionLaw extraction failed for " + lawSid + " from native law wrapper " + DescribeObject(logicLaw); return false; }
		if (!TryReadExactString(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, out var resolvedSid) || !string.Equals(resolvedSid, lawSid, StringComparison.Ordinal)) { failure = "native law wrapper resolved unexpected SID '" + (resolvedSid ?? "?") + "' for requested '" + lawSid + "'"; return false; }
		var result = new NativeLawStateBridgeResult { FactionSid = factionSid, LawSid = lawSid, Family = family, Index = lawIndex, RequestedRank = requestedRank, Source = source, ApplyRequested = applyIfCan, BeforeSummary = ExplainActiveKnownCustomLawResolution(logicFractionLaws, lawIndex) };
		ReadNativeLawDataFields(dataLaw, ref result);
		ReadNativeLawComputedState(logicFractionLaws, logicLaw, requestedRank, result.Line, ref result);
		ReadNativeLawSideState(logicFractionLaws, ref result);
		if (applyIfCan)
		{
			if (!result.CanApplyKnown) result.ApplyFailure = "native canApply method was not callable; apply skipped";
			else if (!result.CanApply) result.ApplyFailure = "native canApply returned false; apply skipped";
			else if (!TryInvokeExactVoidMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawApplyMethods, new object[] { lawSid, requestedRank }, out var applyFailure)) result.ApplyFailure = applyFailure;
			else
			{
				result.ApplyInvoked = true;
				if (TryInvokeExactObjectMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawBySidMethods, new object[] { lawSid }, out var refreshedLaw) && refreshedLaw != null && TryExtractDataFractionLawForDiagnostic(refreshedLaw, out var refreshedDataLaw))
				{
					ReadNativeLawDataFields(refreshedDataLaw, ref result);
					ReadNativeLawComputedState(logicFractionLaws, refreshedLaw, requestedRank, result.Line, ref result);
					ReadNativeLawSideState(logicFractionLaws, ref result);
				}
			}
		}
		result.AfterSummary = ExplainActiveKnownCustomLawResolution(logicFractionLaws, lawIndex);
		json = result.ToJson();
		return true;
	}

	internal static bool TryNativeLawLevelUpForBridge(string factionSid, int count, out string json, out string failure)
	{
		json = null;
		failure = null;
		if (string.IsNullOrWhiteSpace(factionSid)) { failure = "factionSid is required"; return false; }
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid)) { failure = "factionSid is not a custom faction: " + factionSid; return false; }
		if (count < 1 || count > 10) { failure = "count must be between 1 and 10"; return false; }
		if (!TryResolveNativeLawContext(factionSid, out var logicFractionLaws, out _, out var source, out var contextFailure)) { failure = contextFailure; return false; }
		if (!TryResolveLogicSideFromFractionLaws(logicFractionLaws, out var logicSide)) { failure = "exact dtj logic side could not be resolved from FractionLaws for faction '" + factionSid + "'"; return false; }
		if (!TryResolveDataSideFromLawOwner(logicSide, out var dataSide)) { failure = "exact Data.Side could not be resolved from dtj logic side for faction '" + factionSid + "'"; return false; }
		if (!TryReadExactObject(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers, out var fractionLaws)
		    || !TryReadExactString(fractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var resolvedFaction)
		    || !string.Equals(resolvedFaction, factionSid, StringComparison.Ordinal))
		{
			failure = "resolved Data.Side does not belong to faction '" + factionSid + "'";
			return false;
		}

		var beforeLevelKnown = TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideCurrentLevelMembers, out var beforeLevel);
		var beforePointsKnown = TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideCurrentLawsPointsMembers, out var beforePoints);
		for (var i = 0; i < count; i++)
		{
			if (!TryInvokeExactVoidMethod(logicSide, GameSymbols.CustomFactionLawRuntime.LogicSideLevelUpMethods, Array.Empty<object>(), out var invokeFailure))
			{
				failure = "native dtj.LevelUp failed after " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + " successful invocation(s): " + invokeFailure;
				return false;
			}
		}
		var afterLevelKnown = TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideCurrentLevelMembers, out var afterLevel);
		var afterPointsKnown = TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideCurrentLawsPointsMembers, out var afterPoints);
		json = "\"factionSid\":\"" + JsonEscape(factionSid) + "\""
			+ ",\"source\":\"" + JsonEscape(source) + "\""
			+ ",\"count\":" + count.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"nativeLevelUpInvoked\":true"
			+ ",\"beforeSideLevelKnown\":" + (beforeLevelKnown ? "true" : "false")
			+ (beforeLevelKnown ? ",\"beforeSideLevel\":" + beforeLevel.ToString(System.Globalization.CultureInfo.InvariantCulture) : "")
			+ ",\"beforeLawPointsKnown\":" + (beforePointsKnown ? "true" : "false")
			+ (beforePointsKnown ? ",\"beforeLawPoints\":" + beforePoints.ToString(System.Globalization.CultureInfo.InvariantCulture) : "")
			+ ",\"afterSideLevelKnown\":" + (afterLevelKnown ? "true" : "false")
			+ (afterLevelKnown ? ",\"afterSideLevel\":" + afterLevel.ToString(System.Globalization.CultureInfo.InvariantCulture) : "")
			+ ",\"afterLawPointsKnown\":" + (afterPointsKnown ? "true" : "false")
			+ (afterPointsKnown ? ",\"afterLawPoints\":" + afterPoints.ToString(System.Globalization.CultureInfo.InvariantCulture) : "");
		return true;
	}

	internal static bool TryGrantResourceForBridge(string factionSid, string resourceName, int amount, out string json, out string failure)
	{
		json = null;
		failure = null;
		if (string.IsNullOrWhiteSpace(factionSid)) { failure = "factionSid is required"; return false; }
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid)) { failure = "factionSid is not a custom faction: " + factionSid; return false; }
		if (string.IsNullOrWhiteSpace(resourceName)) { failure = "resourceName is required"; return false; }
		if (amount < 1 || amount > 1000000) { failure = "amount must be between 1 and 1000000"; return false; }
		if (!TryResolveRegisteredDataSideForBridge(factionSid, out var dataSide, out var source, out var sideFailure))
		{
			failure = sideFailure;
			return false;
		}
		if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(dataSide, resourceName, out var resource, out var beforeInfo, out var resourceFailure))
		{
			failure = resourceFailure;
			return false;
		}
		using (Homm3CustomFactionEconomyLawDiagnostics.SuppressTraceForExactBridgeResourceMutation())
		{
			if (!Homm3RewardEconomyNativeAdapter.TryAddResourceValue(resource, amount, out var addFailure))
			{
				failure = addFailure;
				return false;
			}
		}
		if (!Homm3RewardEconomyNativeAdapter.TryReadResourceIdentity(resource, out var afterInfo, out var afterFailure))
		{
			failure = "resource add was invoked, but post-state read failed closed: " + afterFailure;
			return false;
		}
		if (!string.Equals(afterInfo.Name, beforeInfo.Name, StringComparison.Ordinal))
		{
			failure = "resource identity changed after native add from '" + beforeInfo.Name + "' to '" + afterInfo.Name + "'";
			return false;
		}
		var expectedAfter = beforeInfo.Value + amount;
		if (afterInfo.Value != expectedAfter)
		{
			failure = "resource add post-state mismatch for '" + beforeInfo.Name + "': before=" + beforeInfo.Value.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " amount=" + amount.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " after=" + afterInfo.Value.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return false;
		}
		json = "\"factionSid\":\"" + JsonEscape(factionSid) + "\""
			+ ",\"source\":\"" + JsonEscape(source) + "\""
			+ ",\"resourceName\":\"" + JsonEscape(beforeInfo.Name) + "\""
			+ ",\"amount\":" + amount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"nativeResourceAddInvoked\":true"
			+ ",\"beforeValue\":" + beforeInfo.Value.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"afterValue\":" + afterInfo.Value.ToString(System.Globalization.CultureInfo.InvariantCulture);
		return true;
	}
	internal static bool TryGetAnyRegisteredDataSide(out object dataSide, out int sideIndex, out string source)
	{
		dataSide = null;
		sideIndex = -1;
		source = null;
		lock (DataSidesBySideIndex)
		{
			foreach (var pair in DataSidesBySideIndex)
			{
				if (pair.Value == null)
					continue;
				dataSide = pair.Value;
				sideIndex = pair.Key;
				source = "registered-data-side-" + pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture);
				return true;
			}
		}
		return false;
	}

	private static bool TryResolveRegisteredDataSideForBridge(string factionSid, out object dataSide, out string source, out string failure)
	{
		dataSide = null;
		source = null;
		failure = null;
		lock (DataSidesBySideIndex)
		{
			foreach (var pair in DataSidesBySideIndex)
			{
				if (pair.Value == null)
					continue;
				if (!TryReadExactObject(pair.Value, GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers, out var fractionLaws)
				    || !TryReadExactString(fractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var currentFaction))
					continue;
				if (!string.Equals(currentFaction, factionSid, StringComparison.Ordinal))
					continue;
				dataSide = pair.Value;
				source = "registered-data-side-" + pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture);
				return true;
			}
		}
		failure = "no exact registered Data.Side context for faction '" + factionSid + "'; load a map with Data.Side preseed diagnostics active";
		return false;
	}
	internal static string ExplainActiveKnownCustomLawResolution(object sideOrLawOwner, int lawIndex)
	{
		if (sideOrLawOwner == null)
			return "law owner source is null";
		if (lawIndex <= 0)
			return "law index must be positive";
		if (!TryGetKnownLawFamily(lawIndex, out var family))
			return "law index " + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + " is not a known runtime family";
		if (!TryResolveDataFractionLawsExplained(sideOrLawOwner, out var dataFractionLaws, out var fractionReason))
			return "dataFractionLaws unresolved for " + DescribeObject(sideOrLawOwner) + ": " + fractionReason;
		if (!TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var factionSid))
			return "dataFractionLaws resolved via " + DescribeObject(dataFractionLaws) + " but faction SID was unreadable";
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return "dataFractionLaws faction '" + factionSid + "' is not a custom faction";
		var expectedLawSid = MakeLawId(factionSid, lawIndex);
		if (string.IsNullOrEmpty(expectedLawSid))
			return "expected law SID could not be built for faction '" + factionSid + "' lawIndex=" + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
		if (!TryReadExactObject(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListMembers, out var lawsList))
			return "dataFractionLaws for faction '" + factionSid + "' did not expose exact laws list";
		if (!TryFindDataFractionLaw(lawsList, expectedLawSid, out var dataLaw))
			return "laws list for faction '" + factionSid + "' did not contain '" + expectedLawSid + "' for family '" + family + "'";
		if (!TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLevelMembers, out var rank))
			return "law '" + expectedLawSid + "' was found but exact rank/level was unreadable";
		if (rank <= 0)
			return "law '" + expectedLawSid + "' was found but rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture);
		if (!TryReadExactBool(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawWasAppliedMembers, out var wasApplied))
			return "law '" + expectedLawSid + "' rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture) + " but wasApplied was unreadable";
		if (!wasApplied)
			return "law '" + expectedLawSid + "' rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture) + " but wasApplied=false";
		if (!TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLineMembers, out _))
			return "law '" + expectedLawSid + "' rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture) + " but line was unreadable";
		if (!TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawGroupMembers, out _))
			return "law '" + expectedLawSid + "' rank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture) + " but group was unreadable";
		return "law '" + expectedLawSid + "' family '" + family + "' appears resolvable; caller should inspect packet gate or side-index resolution";
	}
	internal static bool TryResolveActiveKnownCustomLawSideIndex(object sideOrLawOwner, int lawIndex, out ActiveLawState state, out int sideIndex)
	{
		state = default;
		sideIndex = -1;
		if (!TryResolveActiveKnownCustomLaw(sideOrLawOwner, lawIndex, out state))
			return false;
		if (!TryResolveDataSideFromLawOwner(sideOrLawOwner, out var dataSide))
			return false;
		if (!TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out sideIndex))
			return false;
		return sideIndex >= 0;
	}

	internal static bool TryResolveActiveKnownCustomLawDataSide(object sideOrLawOwner, int lawIndex, out ActiveLawState state, out object dataSide)
	{
		state = default;
		dataSide = null;
		if (!TryResolveActiveKnownCustomLaw(sideOrLawOwner, lawIndex, out state))
			return false;
		if (!TryResolveDataSideFromLawOwner(sideOrLawOwner, out dataSide))
			return false;
		return dataSide != null;
	}

	internal static bool TryResolveAllowedActiveKnownCustomLawForRegisteredFactionExcludingDataSide(
		string factionSid,
		int lawIndex,
		object excludedSideOrLawOwner,
		out ActiveLawState state,
		out object dataSide,
		out string failReason)
	{
		state = default;
		dataSide = null;
		if (string.IsNullOrWhiteSpace(factionSid))
		{
			failReason = "faction SID is empty";
			return false;
		}
		if (lawIndex <= 0)
		{
			failReason = "law index must be positive";
			return false;
		}
		if (!TryResolveDataSideFromLawOwner(excludedSideOrLawOwner, out var excludedDataSide))
		{
			failReason = "excluded side could not be resolved to exact Data.Side";
			return false;
		}
		if (!TryReadExactInt(excludedDataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var excludedSideIndex))
		{
			failReason = "excluded Data.Side has no exact side index";
			return false;
		}

		KeyValuePair<int, object>[] knownSides;
		lock (DataSidesBySideIndex)
		{
			knownSides = new KeyValuePair<int, object>[DataSidesBySideIndex.Count];
			var offset = 0;
			foreach (var pair in DataSidesBySideIndex)
				knownSides[offset++] = pair;
		}

		var rejected = new StringBuilder();
		for (var i = 0; i < knownSides.Length; i++)
		{
			var pair = knownSides[i];
			if (pair.Value == null)
				continue;
			if (pair.Key == excludedSideIndex || ReferenceEquals(pair.Value, excludedDataSide))
				continue;
			if (!TryResolveActiveKnownCustomLaw(pair.Value, lawIndex, out var candidate))
				continue;
			if (!string.Equals(candidate.FactionSid, factionSid, StringComparison.Ordinal))
				continue;
			if (!Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(pair.Value, lawIndex, out var allowed, out var allowedFail))
			{
				if (rejected.Length > 0)
					rejected.Append("; ");
				rejected.Append("side ").Append(pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture)).Append(": ").Append(allowedFail);
				continue;
			}
			if (!string.Equals(allowed.Law.FactionSid, factionSid, StringComparison.Ordinal))
			{
				if (rejected.Length > 0)
					rejected.Append("; ");
				rejected.Append("side ").Append(pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture)).Append(": active law faction mismatch ").Append(allowed.Law.FactionSid);
				continue;
			}
			state = allowed.Law;
			dataSide = pair.Value;
			failReason = null;
			return true;
		}

		failReason = "no registered opposing Data.Side has allowed active law index "
		             + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
		             + " for faction '" + factionSid + "' excluding side "
		             + excludedSideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
		             + (rejected.Length > 0 ? "; rejected candidates: " + rejected : "");
		return false;
	}
	private static bool TryResolveDataFractionLaws(object source, out object dataFractionLaws)
	{
		dataFractionLaws = null;
		if (source == null)
			return false;
		if (LooksLikeDataFractionLaws(source))
		{
			dataFractionLaws = source;
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers, out dataFractionLaws)
		    && LooksLikeDataFractionLaws(dataFractionLaws))
		{
			TryPreseedDataSide(source, "direct-data-side-fraction-laws");
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsDataMembers, out dataFractionLaws)
		    && LooksLikeDataFractionLaws(dataFractionLaws))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicSideDataSideMembers, out var dataSide)
		    && dataSide != null
		    && TryResolveDataFractionLaws(dataSide, out dataFractionLaws))
		{
			TryPreseedDataSide(dataSide, "logic-side-data-side");
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicSideFractionLawsMembers, out var logicFractionLaws)
		    && logicFractionLaws != null
		    && TryResolveDataFractionLaws(logicFractionLaws, out dataFractionLaws))
			return true;
		if (TryResolveDataSideFromLogicHero(source, out var heroDataSide)
		    && TryResolveDataFractionLaws(heroDataSide, out dataFractionLaws))
		{
			TryPreseedDataSide(heroDataSide, "logic-hero-data-side");
			return true;
		}
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveDataSide(source, out var registeredDataSide)
		    && TryResolveDataFractionLaws(registeredDataSide, out dataFractionLaws))
			return true;
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(source, out var registeredTransferSide)
		    && TryResolveDataFractionLaws(registeredTransferSide, out dataFractionLaws))
			return true;
		if (TryResolveBattleSideFromBattleObject(source, out var battleSide)
		    && !ReferenceEquals(source, battleSide)
		    && TryResolveDataFractionLaws(battleSide, out dataFractionLaws))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var directTransferLogicHero)
		    && directTransferLogicHero != null
		    && TryResolveDataFractionLaws(directTransferLogicHero, out dataFractionLaws))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers, out var transferSide)
		    && transferSide != null
		    && TryReadExactObject(transferSide, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var logicHero)
		    && logicHero != null
		    && TryResolveDataFractionLaws(logicHero, out dataFractionLaws))
			return true;
		return false;
	}

	private static bool TryResolveDataFractionLawsExplained(object source, out object dataFractionLaws, out string failReason)
	{
		dataFractionLaws = null;
		string heroReason = "not attempted";
		string battleReason = "not attempted";
		if (source == null)
		{
			failReason = "source is null";
			return false;
		}
		if (LooksLikeDataFractionLaws(source))
		{
			dataFractionLaws = source;
			failReason = null;
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers, out dataFractionLaws)
		    && LooksLikeDataFractionLaws(dataFractionLaws))
		{
			TryPreseedDataSide(source, "direct-data-side-fraction-laws-explained");
			failReason = null;
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsDataMembers, out dataFractionLaws)
		    && LooksLikeDataFractionLaws(dataFractionLaws))
		{
			failReason = null;
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicSideDataSideMembers, out var dataSide)
		    && dataSide != null
		    && TryResolveDataFractionLawsExplained(dataSide, out dataFractionLaws, out failReason))
		{
			TryPreseedDataSide(dataSide, "logic-side-data-side-explained");
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicSideFractionLawsMembers, out var logicFractionLaws)
		    && logicFractionLaws != null
		    && TryResolveDataFractionLawsExplained(logicFractionLaws, out dataFractionLaws, out failReason))
			return true;
		if (TryResolveDataSideFromLogicHeroExplained(source, out var heroDataSide, out heroReason)
		    && TryResolveDataFractionLawsExplained(heroDataSide, out dataFractionLaws, out failReason))
		{
			TryPreseedDataSide(heroDataSide, "logic-hero-data-side-explained");
			return true;
		}
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveDataSide(source, out var registeredDataSide))
		{
			if (TryResolveDataFractionLawsExplained(registeredDataSide, out dataFractionLaws, out failReason))
				return true;
			battleReason = "battle unit registry hit data side " + DescribeObject(registeredDataSide) + " but data-side law owner resolution failed: " + failReason;
		}
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(source, out var registeredTransferSide))
		{
			if (TryResolveDataFractionLawsExplained(registeredTransferSide, out dataFractionLaws, out failReason))
				return true;
			battleReason = "battle unit registry hit transfer side " + DescribeObject(registeredTransferSide) + " but transfer-side law owner resolution failed: " + failReason;
		}
		if (TryResolveBattleSideFromBattleObjectExplained(source, out var battleSide, out battleReason)
		    && !ReferenceEquals(source, battleSide)
		    && TryResolveDataFractionLawsExplained(battleSide, out dataFractionLaws, out failReason))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var directTransferLogicHero)
		    && directTransferLogicHero != null
		    && TryResolveDataFractionLawsExplained(directTransferLogicHero, out dataFractionLaws, out failReason))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers, out var transferSide)
		    && transferSide != null
		    && TryReadExactObject(transferSide, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var logicHero)
		    && logicHero != null
		    && TryResolveDataFractionLawsExplained(logicHero, out dataFractionLaws, out failReason))
			return true;

		failReason = "no exact route matched; logicHero route: " + heroReason + "; battleObject route: " + battleReason;
		return false;
	}
	internal static bool TryResolveDataSideFromBattleTransferSide(object transferSide, out object dataSide, out string failReason)
	{
		dataSide = null;
		if (transferSide == null)
		{
			failReason = "TransferSide source is null";
			return false;
		}

		if (!TryReadExactObject(transferSide, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var logicHero)
		    || logicHero == null)
		{
			failReason = "TransferSide " + DescribeObject(transferSide) + " exposed no exact logicHero";
			return false;
		}
		if (!TryResolveDataSideFromLogicHeroExplained(logicHero, out dataSide, out failReason))
		{
			failReason = "TransferSide.logicHero bridge failed: " + failReason;
			return false;
		}
		if (TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var dataSideIndex))
			Homm3BattleUnitLawOwnerRegistry.RegisterDataSide(dataSideIndex, dataSide);
		failReason = null;
		return true;
	}
	private static bool TryResolveDataSideFromLawOwner(object source, out object dataSide)
	{
		dataSide = null;
		if (source == null)
			return false;
		if (TryReadExactInt(source, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var directDataSideIndex)
		    && TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers, out _))
		{
			dataSide = source;
			Homm3BattleUnitLawOwnerRegistry.RegisterDataSide(directDataSideIndex, dataSide);
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicSideDataSideMembers, out dataSide)
		    && dataSide != null
		    && TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var logicDataSideIndex))
		{
			Homm3BattleUnitLawOwnerRegistry.RegisterDataSide(logicDataSideIndex, dataSide);
			TryRegisterLogicFractionLawsForDataSide(source, dataSide);
			return true;
		}
		if (TryResolveDataSideFromLogicHero(source, out dataSide))
		{
			if (TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var heroDataSideIndex))
				Homm3BattleUnitLawOwnerRegistry.RegisterDataSide(heroDataSideIndex, dataSide);
			return true;
		}
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveDataSide(source, out dataSide))
			return true;
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(source, out var registeredTransferSide)
		    && TryResolveDataSideFromLawOwner(registeredTransferSide, out dataSide))
			return true;
		if (TryResolveBattleSideFromBattleObject(source, out var battleSide)
		    && !ReferenceEquals(source, battleSide)
		    && TryResolveDataSideFromLawOwner(battleSide, out dataSide))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var directTransferLogicHero)
		    && directTransferLogicHero != null
		    && TryResolveDataSideFromLogicHero(directTransferLogicHero, out dataSide))
			return true;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers, out var transferSide)
		    && transferSide != null
		    && TryReadExactObject(transferSide, GameSymbols.CustomFactionLawRuntime.TransferSideLogicHeroMembers, out var logicHero)
		    && logicHero != null
		    && TryResolveDataSideFromLogicHero(logicHero, out dataSide))
			return true;
		return false;
	}

	private static void PreseedDataRoot(object dataRoot, string source)
	{
		if (dataRoot == null)
			return;
		if (!TryReadExactObject(dataRoot, GameSymbols.CustomFactionLawRuntime.DataRootSidesMembers, out var dataSides)
		    || dataSides == null)
		{
			if (_loggedPreseed++ < 24)
				Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: Data root preseed failed closed; exact sides unreadable source="
					+ (source ?? "unspecified")
					+ " dataRoot=" + DescribeObject(dataRoot)
					+ ". Diagnostic observation only.");
			return;
		}
		PreseedDataSidesArray(dataSides, source);
	}

	private static void PreseedDataSidesArray(object dataSides, string source)
	{
		if (dataSides == null)
			return;
		if (!TryReadExactObject(dataSides, GameSymbols.CustomFactionLawRuntime.DataSidesArrayMembers, out var rawArray)
		    || rawArray is not System.Collections.IEnumerable enumerable)
		{
			if (_loggedPreseed++ < 24)
				Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: DataSides preseed failed closed; exact array unreadable source="
					+ (source ?? "unspecified")
					+ " dataSides=" + DescribeObject(dataSides)
					+ ". Diagnostic observation only.");
			return;
		}

		var visited = 0;
		var registered = 0;
		foreach (var candidate in enumerable)
		{
			if (candidate == null)
				continue;
			visited++;
			if (TryPreseedDataSide(candidate, source))
				registered++;
		}
		if (_loggedPreseed++ < 24)
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: DataSides preseed scan source="
				+ (source ?? "unspecified")
				+ " visited=" + visited.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " registered=" + registered.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ". Runtime proof pending; diagnostic observation only.");
	}

	private static void PreseedLogicRootSideCollection(object logicRoot, string source)
	{
		if (logicRoot == null)
			return;
		if (!TryReadExactObject(logicRoot, GameSymbols.CustomFactionLawRuntime.LogicRootSideCollectionMembers, out var logicSides)
		    || logicSides == null)
		{
			LogNativeLawSeed("logic-root side collection unreadable source=" + (source ?? "unspecified")
				+ " root=" + DescribeObject(logicRoot) + ". No raw DataFractionLaw write was attempted.");
			return;
		}
		var registered = 0;
		KeyValuePair<int, object>[] knownSides;
		lock (DataSidesBySideIndex)
		{
			knownSides = new KeyValuePair<int, object>[DataSidesBySideIndex.Count];
			var offset = 0;
			foreach (var pair in DataSidesBySideIndex)
				knownSides[offset++] = pair;
		}
		for (var i = 0; i < knownSides.Length; i++)
		{
			var pair = knownSides[i];
			if (!TryRegisterLogicFractionLawsFromSideCollection(logicSides, pair.Value, pair.Key, source))
				continue;
			registered++;
			TryPreseedDataSide(pair.Value, "logic-root-side-collection:" + (source ?? "unspecified"));
		}
		if (_loggedPreseed++ < 24)
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: logic-root side collection preseed source="
				+ (source ?? "unspecified")
				+ " registered=" + registered.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ". Runtime proof pending; diagnostic observation only.");
	}

	private static bool TryRegisterLogicFractionLawsFromGlobalRootForDataSide(object dataSide, int sideIndex, string source)
	{
		if (dataSide == null)
			return false;
		if (!TryResolveGlobalLogicRoot(out var logicRoot) || logicRoot == null)
			return false;
		if (!TryReadExactObject(logicRoot, GameSymbols.CustomFactionLawRuntime.LogicRootSideCollectionMembers, out var logicSides)
		    || logicSides == null)
			return false;
		return TryRegisterLogicFractionLawsFromSideCollection(logicSides, dataSide, sideIndex, source);
	}

	private static bool TryRegisterLogicFractionLawsFromSideCollection(object logicSides, object dataSide, int sideIndex, string source)
	{
		if (logicSides == null || dataSide == null)
			return false;
		if (!TryInvokeExactObjectMethod(logicSides, GameSymbols.CustomFactionLawRuntime.LogicSideCollectionByIndexMethods, new object[] { sideIndex }, out var logicSide)
		    || logicSide == null)
		{
			LogNativeLawSeed("logic side collection exact by-index lookup failed sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified")
				+ ". No raw DataFractionLaw write was attempted.");
			return false;
		}
		if (!TryRegisterLogicFractionLawsForDataSide(logicSide, dataSide))
		{
			LogNativeLawSeed("logic side collection returned " + DescribeObject(logicSide)
				+ " but exact Logic.FractionLaws registration failed sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified")
				+ ". No raw DataFractionLaw write was attempted.");
			return false;
		}
		return true;
	}

	private static bool TryResolveGlobalLogicRoot(out object logicRoot)
	{
		logicRoot = null;
		var type = FindFirstRuntimeType(GameSymbols.CustomFactionLawRuntime.GlobalLogicRootTypeHints);
		if (type == null)
			return false;
		foreach (var name in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootInstanceMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.FlattenHierarchy);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					logicRoot = prop.GetValue(null, null);
					if (logicRoot != null)
						return true;
				}
			}
			catch { }
			try
			{
				var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.FlattenHierarchy);
				if (field != null)
				{
					logicRoot = field.GetValue(null);
					if (logicRoot != null)
						return true;
				}
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.FlattenHierarchy, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
				{
					logicRoot = method.Invoke(null, null);
					if (logicRoot != null)
						return true;
				}
			}
			catch { }
		}
		return false;
	}
	private static bool TryPreseedDataSide(object candidate, string source)
	{
		if (candidate == null)
			return false;
		if (!TryReadExactInt(candidate, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var sideIndex))
			return false;
		if (!TryReadExactObject(candidate, GameSymbols.CustomFactionLawRuntime.DataSideFractionLawMembers, out var fractionLaws)
		    || !LooksLikeDataFractionLaws(fractionLaws))
			return false;
		Homm3BattleUnitLawOwnerRegistry.RegisterDataSide(sideIndex, candidate);
		lock (DataSidesBySideIndex)
			DataSidesBySideIndex[sideIndex] = candidate;
		TryRegisterLogicFractionLawsFromGlobalRootForDataSide(candidate, sideIndex, source);
		if (_loggedPreseed++ < 24)
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: preseeded combat Data.Side lookup sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified")
				+ " dataSide=" + DescribeObject(candidate)
				+ ". Runtime proof pending; diagnostic observation only.");
		LogPreseededKnownCustomLawRanks(candidate, fractionLaws, sideIndex, source);
		TrySeedActiveLawRankFromNativeLogic(candidate, fractionLaws, sideIndex, source);
		return true;
	}

	private static void TrySeedActiveLawRankFromNativeLogic(object dataSide, object fractionLaws, int sideIndex, string source)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(NativeLawSeedDiagnosticFlag) || _nativeLawSeedApplied || _nativeLawSeedAttempted)
			return;
		if (dataSide == null || fractionLaws == null)
			return;
		if (!TryReadExactString(fractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var factionSid))
			return;
		if (!string.Equals(factionSid, NativeLawSeedFactionSid, StringComparison.Ordinal))
			return;

		var lawSid = MakeLawId(factionSid, NativeLawSeedIndex);
		if (string.IsNullOrEmpty(lawSid))
			return;
		if (!TryReadExactObject(fractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListMembers, out var lawsList)
		    || !TryFindDataFractionLaw(lawsList, lawSid, out var dataLaw))
		{
			LogNativeLawSeed("failed closed; safe seed row '" + lawSid + "' was not found on sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified") + ".");
			return;
		}
		if (TryBuildActiveLawState(dataLaw, factionSid, lawSid, NativeLawSeedIndex, out var alreadyActive))
		{
			_nativeLawSeedApplied = true;
			LogNativeLawSeed("already active before seed: " + alreadyActive + ".");
			return;
		}
		if (!TryResolveLogicFractionLaws(dataSide, out var logicFractionLaws, out _))
		{
			LogNativeLawSeed("deferred; exact Logic.FractionLaws wrapper is not registered for sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified")
				+ ". No raw DataFractionLaw field write was attempted.");
			return;
		}

		_nativeLawSeedAttempted = true;
		var canApplyKnown = TryInvokeExactBoolMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawCanApplyMethods, new object[] { lawSid, NativeLawSeedRank }, out var canApply);
		LogNativeLawSeed("attempting exact native apply sideIndex="
			+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " law='" + lawSid + "' rank=" + NativeLawSeedRank.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " canApplyKnown=" + canApplyKnown
			+ " canApply=" + canApply
			+ " source=" + (source ?? "unspecified") + ".");
		if (canApplyKnown && !canApply)
		{
			LogNativeLawSeed("stopped before native apply because exact canApply rejected law='" + lawSid
				+ "' rank=" + NativeLawSeedRank.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ". No raw DataFractionLaw write or forced native apply was attempted.");
			return;
		}
		if (!TryInvokeExactVoidMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawApplyMethods, new object[] { lawSid, NativeLawSeedRank }, out var applyFailure))
		{
			LogNativeLawSeed("failed closed; exact native apply method was not invoked for law='" + lawSid + "': " + applyFailure + ".");
			return;
		}
		if (TryResolveActiveKnownCustomLaw(dataSide, NativeLawSeedIndex, out var seeded))
		{
			_nativeLawSeedApplied = true;
			LogNativeLawSeed("runtime proof candidate: exact native apply made active law resolvable: " + seeded + ". Packet gameplay remains disabled.");
			return;
		}
		LogNativeLawSeed("native apply returned, but active law resolver still failed: "
			+ ExplainActiveKnownCustomLawResolution(dataSide, NativeLawSeedIndex)
			+ ". Packet gameplay remains disabled.");
	}

	private static void LogNativeLawSeed(string message)
	{
		if (_loggedNativeLawSeed++ >= 12)
			return;
		Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: native law seed diagnostic " + message);
	}

	private static void LogPreseededKnownCustomLawRanks(object dataSide, object fractionLaws, int sideIndex, string source)
	{
		if (_loggedPreseedLawRanks++ >= 24)
			return;
		if (!TryReadExactString(fractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var factionSid)
		    && !TryReadExactString(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideFactionMembers, out factionSid))
		{
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: preseed law-rank scan failed closed; exact faction SID unreadable sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified")
				+ ". Diagnostic observation only.");
			return;
		}
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
		{
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: preseed law-rank scan skipped non-custom faction='"
				+ (factionSid ?? "null")
				+ "' sideIndex=" + sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " source=" + (source ?? "unspecified")
				+ ". Diagnostic observation only.");
			return;
		}

		if (!TryReadExactObject(fractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListMembers, out var lawsList))
		{
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: preseed law-rank scan failed closed; exact laws list unreadable sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " faction='" + factionSid + "' source=" + (source ?? "unspecified")
				+ ". Diagnostic observation only.");
			return;
		}
		if (!TryGetExactListCount(lawsList, out var totalRows))
		{
			Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: preseed law-rank scan failed closed; exact laws list count unreadable sideIndex="
				+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " faction='" + factionSid + "' source=" + (source ?? "unspecified")
				+ " lawsList=" + DescribeObject(lawsList)
				+ ". Diagnostic observation only.");
			return;
		}

		var readableSidRows = 0;
		var sampleSids = new StringBuilder();
		for (var row = 0; row < totalRows; row++)
		{
			if (!TryGetExactListItem(lawsList, row, out var candidate) || candidate == null)
				continue;
			if (!TryReadExactString(candidate, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, out var sid))
				continue;
			readableSidRows++;
			if (sampleSids.Length < 256)
			{
				if (sampleSids.Length > 0)
					sampleSids.Append(",");
				sampleSids.Append(sid);
			}
		}

		var found = 0;
		var active = 0;
		var sb = new StringBuilder();
		for (var i = 0; i < KnownRuntimeLawIndices.Length; i++)
		{
			var lawIndex = KnownRuntimeLawIndices[i];
			var expectedLawSid = MakeLawId(factionSid, lawIndex);
			if (!TryFindDataFractionLaw(lawsList, expectedLawSid, out var dataLaw))
				continue;
			found++;
			if (!TryBuildActiveLawState(dataLaw, factionSid, expectedLawSid, lawIndex, out var state))
				continue;
			active++;
			if (sb.Length > 0)
				sb.Append("; ");
			sb.Append(state.Index.ToString(System.Globalization.CultureInfo.InvariantCulture))
				.Append("=")
				.Append(state.Rank.ToString(System.Globalization.CultureInfo.InvariantCulture))
				.Append("[")
				.Append(state.Family)
				.Append("]");
		}

		Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: preseed law-rank scan sideIndex="
			+ sideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " faction='" + factionSid + "' source=" + (source ?? "unspecified")
			+ " totalRows=" + totalRows.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " readableSidRows=" + readableSidRows.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " sidSample=" + (sampleSids.Length == 0 ? "none" : sampleSids.ToString())
			+ " knownRows=" + found.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " activeKnownRows=" + active.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " activeRanks=" + (sb.Length == 0 ? "none" : sb.ToString())
			+ ". Runtime proof pending; diagnostic observation only.");
	}

	private static bool TryResolveBattleSideFromBattleObject(object source, out object battleSide)
	{
		battleSide = null;
		if (source == null)
			return false;
		if (TryReadExactObject(source, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out battleSide)
		    && battleSide != null)
			return true;
		return TryResolveTransferSideFromBattleObjectUnit(source, out battleSide);
	}

	private static bool TryResolveBattleSideFromBattleObjectExplained(object source, out object battleSide, out string failReason)
	{
		battleSide = null;
		if (source == null)
		{
			failReason = "battle object source is null";
			return false;
		}
		if (TryReadExactObject(source, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out battleSide)
		    && battleSide != null)
		{
			failReason = null;
			return true;
		}
		return TryResolveTransferSideFromBattleObjectUnitExplained(source, out battleSide, out failReason);
	}
	private static bool TryResolveTransferSideFromBattleObjectUnit(object source, out object transferSide)
	{
		transferSide = null;
		if (source == null)
			return false;
		if (!TryReadExactObject(source, GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers, out var battleLogic)
		    || battleLogic == null)
			return false;
		object unit = null;
		if (!TryReadExactObject(source, GameSymbols.BattleEventLaws.UnitTransferUnitMembers, out var transferUnit)
		    || transferUnit == null)
		{
			if (!TryReadExactObject(source, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex)
			    || hex == null)
				return false;
			if (!TryReadExactObject(hex, GameSymbols.BattleEventLaws.HexOccupantMembers, out unit)
			    || unit == null)
				return false;
			if (!TryReadExactObject(unit, GameSymbols.BattleEventLaws.UnitTransferUnitMembers, out transferUnit)
			    || transferUnit == null)
				return false;
		}
		if (!TryReadExactObject(battleLogic, GameSymbols.BattleEventLaws.BattleLogicTransferBattleMembers, out var transferBattle)
		    || transferBattle == null)
			return false;
		if (!TryReadExactObject(transferBattle, GameSymbols.BattleEventLaws.TransferBattleSidesMembers, out var sides)
		    || sides is not System.Collections.IEnumerable sideEnumerable)
			return false;
		foreach (var side in sideEnumerable)
		{
			if (side == null)
				continue;
			if (!TryReadExactObject(side, GameSymbols.BattleEventLaws.TransferSideUnitsMembers, out var units)
			    || units is not System.Collections.IEnumerable unitEnumerable)
				continue;
			foreach (var candidate in unitEnumerable)
			{
				if (candidate == null)
					continue;
				if (!SameRuntimeObject(candidate, transferUnit) && !SameTransferUnitIdentity(candidate, transferUnit))
					continue;
				transferSide = side;
				return true;
			}
		}
		return false;
	}

	private static bool TryResolveTransferSideFromBattleObjectUnitExplained(object source, out object transferSide, out string failReason)
	{
		transferSide = null;
		if (source == null)
		{
			failReason = "battle object source is null";
			return false;
		}
		if (!TryReadExactObject(source, GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers, out var battleLogic)
		    || battleLogic == null)
		{
			failReason = "battle object " + DescribeObject(source) + " did not expose exact battle logic";
			return false;
		}
		object unit = source;
		if (!TryReadExactObject(source, GameSymbols.BattleEventLaws.UnitTransferUnitMembers, out var transferUnit)
		    || transferUnit == null)
		{
			if (!TryReadExactObject(source, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex)
			    || hex == null)
			{
				failReason = "battle object " + DescribeObject(source) + " exposed battle logic " + DescribeObject(battleLogic) + " but no exact hex and no direct transfer unit";
				return false;
			}
			if (!TryReadExactObject(hex, GameSymbols.BattleEventLaws.HexOccupantMembers, out unit)
			    || unit == null)
			{
				failReason = "hex " + DescribeObject(hex) + " exposed no exact occupant unit and source had no direct transfer unit";
				return false;
			}
			if (!TryReadExactObject(unit, GameSymbols.BattleEventLaws.UnitTransferUnitMembers, out transferUnit)
			    || transferUnit == null)
			{
				failReason = "unit " + DescribeObject(unit) + " exposed no exact transfer unit";
				return false;
			}
		}
		if (!TryReadExactObject(battleLogic, GameSymbols.BattleEventLaws.BattleLogicTransferBattleMembers, out var transferBattle)
		    || transferBattle == null)
		{
			failReason = "battle logic " + DescribeObject(battleLogic) + " exposed no exact transfer battle";
			return false;
		}
		if (!TryReadExactObject(transferBattle, GameSymbols.BattleEventLaws.TransferBattleSidesMembers, out var sides)
		    || sides is not System.Collections.IEnumerable sideEnumerable)
		{
			failReason = "transfer battle " + DescribeObject(transferBattle) + " exposed no enumerable exact sides";
			return false;
		}
		var sideCount = 0;
		var sideWithoutUnits = 0;
		var comparedUnits = 0;
		foreach (var side in sideEnumerable)
		{
			if (side == null)
				continue;
			sideCount++;
			if (!TryReadExactObject(side, GameSymbols.BattleEventLaws.TransferSideUnitsMembers, out var units)
			    || units is not System.Collections.IEnumerable unitEnumerable)
			{
				sideWithoutUnits++;
				continue;
			}
			foreach (var candidate in unitEnumerable)
			{
				if (candidate == null)
					continue;
				comparedUnits++;
				if (!SameRuntimeObject(candidate, transferUnit) && !SameTransferUnitIdentity(candidate, transferUnit))
					continue;
				transferSide = side;
				failReason = null;
				return true;
			}
		}
		failReason = "transfer unit " + DescribeObject(transferUnit) + " was not present in transfer battle sides; sides="
		             + sideCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
		             + " sidesWithoutUnits=" + sideWithoutUnits.ToString(System.Globalization.CultureInfo.InvariantCulture)
		             + " comparedUnits=" + comparedUnits.ToString(System.Globalization.CultureInfo.InvariantCulture);
		return false;
	}
	private static bool SameTransferUnitIdentity(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (!TryReadExactString(left, GameSymbols.BattleEventLaws.TransferUnitConfigSidMembers, out var leftSid))
			return false;
		if (!TryReadExactString(right, GameSymbols.BattleEventLaws.TransferUnitConfigSidMembers, out var rightSid))
			return false;
		if (!string.Equals(leftSid, rightSid, StringComparison.Ordinal))
			return false;
		if (!TryReadExactInt(left, GameSymbols.BattleEventLaws.TransferUnitSlotPosMembers, out var leftSlot))
			return false;
		if (!TryReadExactInt(right, GameSymbols.BattleEventLaws.TransferUnitSlotPosMembers, out var rightSlot))
			return false;
		return leftSlot == rightSlot;
	}
	private static bool SameRuntimeObject(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		try
		{
			if (left.Equals(right) || right.Equals(left))
				return true;
		}
		catch
		{
		}
		return false;
	}

	private static bool TryResolveDataSideFromLogicHero(object source, out object dataSide)
	{
		dataSide = null;
		if (source == null)
			return false;
		if (!TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicHeroDataHeroMembers, out var dataHero)
		    || dataHero == null)
			return false;
		if (!TryReadExactInt(dataHero, GameSymbols.CustomFactionLawRuntime.DataHeroSideIdMembers, out var sideId))
			return false;
		if (!TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicHeroLogicRootMembers, out var logicRoot)
		    || logicRoot == null)
			return false;
		if (!TryReadExactObject(logicRoot, GameSymbols.CustomFactionLawRuntime.LogicRootDataMembers, out var dataRoot)
		    || dataRoot == null)
			return false;
		if (!TryReadExactObject(dataRoot, GameSymbols.CustomFactionLawRuntime.DataRootSidesMembers, out var dataSides)
		    || dataSides == null)
			return false;
		if (!TryReadExactObject(dataSides, GameSymbols.CustomFactionLawRuntime.DataSidesArrayMembers, out var sidesArray)
		    || sidesArray is not System.Collections.IEnumerable enumerable)
			return false;

		foreach (var candidate in enumerable)
		{
			if (candidate == null)
				continue;
			if (!TryReadExactInt(candidate, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var candidateIndex))
				continue;
			if (candidateIndex != sideId)
				continue;
			dataSide = candidate;
			return true;
		}
		return false;
	}

	// internal: also the Dungeon Captives Ransom gold path (Homm3DungeonCaptivesRuntime).
	internal static bool TryResolveDataSideFromLogicHeroExplained(object source, out object dataSide, out string failReason)
	{
		dataSide = null;
		if (source == null)
		{
			failReason = "logic hero source is null";
			return false;
		}
		if (!TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicHeroDataHeroMembers, out var dataHero)
		    || dataHero == null)
		{
			failReason = DescribeObject(source) + " exposed no exact data hero";
			return false;
		}
		if (!TryReadExactInt(dataHero, GameSymbols.CustomFactionLawRuntime.DataHeroSideIdMembers, out var sideId))
		{
			failReason = "data hero " + DescribeObject(dataHero) + " exposed no exact side id";
			return false;
		}
		if (!TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicHeroLogicRootMembers, out var logicRoot)
		    || logicRoot == null)
		{
			failReason = DescribeObject(source) + " exposed no exact logic root";
			return false;
		}
		if (!TryReadExactObject(logicRoot, GameSymbols.CustomFactionLawRuntime.LogicRootDataMembers, out var dataRoot)
		    || dataRoot == null)
		{
			failReason = "logic root " + DescribeObject(logicRoot) + " exposed no exact data root";
			return false;
		}
		if (!TryReadExactObject(dataRoot, GameSymbols.CustomFactionLawRuntime.DataRootSidesMembers, out var dataSides)
		    || dataSides == null)
		{
			failReason = "data root " + DescribeObject(dataRoot) + " exposed no exact data sides";
			return false;
		}
		if (!TryReadExactObject(dataSides, GameSymbols.CustomFactionLawRuntime.DataSidesArrayMembers, out var sidesArray)
		    || sidesArray is not System.Collections.IEnumerable enumerable)
		{
			failReason = "data sides " + DescribeObject(dataSides) + " exposed no enumerable exact sides array";
			return false;
		}

		var comparedSides = 0;
		foreach (var candidate in enumerable)
		{
			if (candidate == null)
				continue;
			if (!TryReadExactInt(candidate, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var candidateIndex))
				continue;
			comparedSides++;
			if (candidateIndex != sideId)
				continue;
			dataSide = candidate;
			failReason = null;
			return true;
		}
		failReason = "no data side matched data hero sideId=" + sideId.ToString(System.Globalization.CultureInfo.InvariantCulture)
		             + "; comparedSides=" + comparedSides.ToString(System.Globalization.CultureInfo.InvariantCulture);
		return false;
	}
	private static bool LooksLikeDataFractionLaws(object value)
	{
		if (value == null)
			return false;
		return TryReadExactString(value, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out _)
		       && TryReadExactObject(value, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListMembers, out _);
	}

	private static bool TryFindDataFractionLaw(object lawsList, string expectedLawSid, out object dataLaw)
	{
		dataLaw = null;
		if (!TryGetExactListCount(lawsList, out var totalRows))
			return false;
		for (var row = 0; row < totalRows; row++)
		{
			if (!TryGetExactListItem(lawsList, row, out var candidate) || candidate == null)
				continue;
			if (!TryReadExactString(candidate, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, out var sid))
				continue;
			if (!string.Equals(sid, expectedLawSid, StringComparison.Ordinal))
				continue;
			dataLaw = candidate;
			return true;
		}
		return false;
	}

	private static bool TryGetExactListCount(object list, out int count)
	{
		count = 0;
		return TryReadExactInt(list, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListCountMembers, out count)
		       && count >= 0;
	}

	private static bool TryGetExactListItem(object list, int index, out object item)
	{
		item = null;
		if (index < 0)
			return false;
		return TryInvokeExactObjectMethod(list, GameSymbols.CustomFactionLawRuntime.DataFractionLawsListItemMethods, new object[] { index }, out item);
	}

	private static bool TryResolveActiveKnownCustomLawFromLogic(object source, int lawIndex, out ActiveLawState state)
	{
		state = default;
		if (!TryResolveLogicFractionLaws(source, out var logicFractionLaws, out var dataFractionLaws))
			return false;
		if (!TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var factionSid))
			return false;
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return false;
		var expectedLawSid = MakeLawId(factionSid, lawIndex);
		if (string.IsNullOrEmpty(expectedLawSid))
			return false;
		if (!TryInvokeExactObjectMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawBySidMethods, new object[] { expectedLawSid }, out var logicLaw))
			return false;
		if (logicLaw == null)
			return false;
		if (!TryReadExactObject(logicLaw, GameSymbols.CustomFactionLawRuntime.LawDataGetters, out var dataLaw))
			return false;
		return TryBuildActiveLawState(dataLaw, factionSid, expectedLawSid, lawIndex, out state);
	}

	private static bool TryResolveNativeLawContext(string factionSid, out object logicFractionLaws, out object dataFractionLaws, out string source, out string failure)
	{
		logicFractionLaws = null; dataFractionLaws = null; source = null; failure = null;
		if (!string.IsNullOrWhiteSpace(factionSid) && _lastLawTreeLogicSide != null && TryResolveLogicFractionLaws(_lastLawTreeLogicSide, out logicFractionLaws, out dataFractionLaws) && TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var lawTreeFaction) && string.Equals(lawTreeFaction, factionSid, StringComparison.Ordinal)) { source = "last-law-tree-logic-side"; return true; }
		if (!string.IsNullOrWhiteSpace(factionSid) && _lastLawTreeDataSide != null && TryResolveLogicFractionLaws(_lastLawTreeDataSide, out logicFractionLaws, out dataFractionLaws) && TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var lawTreeDataFaction) && string.Equals(lawTreeDataFaction, factionSid, StringComparison.Ordinal)) { source = "last-law-tree-data-side"; return true; }
		lock (LogicFractionLawsBySideIndex)
		{
			foreach (var pair in LogicFractionLawsBySideIndex)
			{
				if (pair.Value != null && TryResolveLogicFractionLaws(pair.Value, out logicFractionLaws, out dataFractionLaws) && TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var currentFaction) && string.Equals(currentFaction, factionSid, StringComparison.Ordinal)) { source = "registered-logic-fraction-laws-side-" + pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture); return true; }
			}
		}
		lock (DataSidesBySideIndex)
		{
			foreach (var pair in DataSidesBySideIndex)
			{
				if (pair.Value != null && TryResolveLogicFractionLaws(pair.Value, out logicFractionLaws, out dataFractionLaws) && TryReadExactString(dataFractionLaws, GameSymbols.CustomFactionLawRuntime.DataFractionLawsFactionMembers, out var currentFaction) && string.Equals(currentFaction, factionSid, StringComparison.Ordinal)) { source = "registered-data-side-" + pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture); return true; }
			}
		}
		failure = "no exact registered native FractionLaws context for faction '" + factionSid + "'; open that faction law tree or load a map with law diagnostics active";
		return false;
	}

	private static void ReadNativeLawDataFields(object dataLaw, ref NativeLawStateBridgeResult result)
	{
		if (TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLevelMembers, out var level)) result.CurrentLevel = level;
		if (TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLineMembers, out var line)) result.Line = line;
		if (TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawGroupMembers, out var group)) result.Group = group;
		if (TryReadExactBool(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawWasAppliedMembers, out var wasApplied)) { result.WasAppliedKnown = true; result.WasApplied = wasApplied; }
	}

	private static void ReadNativeLawComputedState(object logicFractionLaws, object logicLaw, int requestedRank, int line, ref NativeLawStateBridgeResult result)
	{
		if (TryInvokeExactBoolMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawCanApplyMethods, new object[] { result.LawSid, requestedRank }, out var canApply)) { result.CanApplyKnown = true; result.CanApply = canApply; }
		if (TryInvokeExactBoolMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawRankEligibleMethods, new object[] { logicLaw, requestedRank }, out var rankEligible)) { result.RankEligibleKnown = true; result.RankEligible = rankEligible; }
		if (TryInvokeExactBoolMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawLineVisibleMethods, new object[] { logicLaw }, out var lineVisible)) { result.LineVisibleKnown = true; result.LineVisible = lineVisible; }
		if (TryInvokeExactIntMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawCostMethods, new object[] { logicLaw, requestedRank }, out var cost)) { result.CostKnown = true; result.Cost = cost; }
		if (TryInvokeExactIntMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsSpentPointsMethods, Array.Empty<object>(), out var spentPoints)) { result.SpentPointsKnown = true; result.SpentPoints = spentPoints; }
		if (TryInvokeExactIntMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsUnlockedLineMethods, Array.Empty<object>(), out var unlockedLine)) { result.UnlockedLineKnown = true; result.UnlockedLine = unlockedLine; }
		if (line >= 0 && TryInvokeExactIntMethod(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsLineRequirementMethods, new object[] { line }, out var lineRequirement)) { result.LineRequirementKnown = true; result.LineRequirement = lineRequirement; }
	}

	private static void ReadNativeLawSideState(object logicFractionLaws, ref NativeLawStateBridgeResult result)
	{
		if (!TryResolveLogicSideFromFractionLaws(logicFractionLaws, out var logicSide))
			return;
		if (TryResolveDataSideFromLawOwner(logicSide, out var dataSide))
		{
			if (TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideCurrentLevelMembers, out var sideLevel)) { result.NativeSideLevelKnown = true; result.NativeSideLevel = sideLevel; }
			if (TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideCurrentLawsPointsMembers, out var lawPoints)) { result.NativeLawPointsKnown = true; result.NativeLawPoints = lawPoints; }
		}
		if (result.CostKnown && TryInvokeExactBoolMethod(logicSide, GameSymbols.CustomFactionLawRuntime.LogicSideCanSpendLawPointsMethods, new object[] { result.Cost }, out var canAffordCost))
		{
			result.NativeCanAffordCostKnown = true;
			result.NativeCanAffordCost = canAffordCost;
		}
	}

	private static bool TryResolveLogicSideFromFractionLaws(object logicFractionLaws, out object logicSide)
	{
		logicSide = null;
		if (logicFractionLaws == null)
			return false;
		return TryReadExactObject(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsLogicSideMembers, out logicSide) && logicSide != null;
	}

	private static bool TryResolveLogicFractionLaws(object source, out object logicFractionLaws, out object dataFractionLaws)
	{
		logicFractionLaws = null;
		dataFractionLaws = null;
		if (source == null)
			return false;
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsDataMembers, out dataFractionLaws)
		    && LooksLikeDataFractionLaws(dataFractionLaws))
		{
			logicFractionLaws = source;
			return true;
		}
		if (TryReadExactObject(source, GameSymbols.CustomFactionLawRuntime.LogicSideFractionLawsMembers, out logicFractionLaws)
		    && logicFractionLaws != null
		    && TryReadExactObject(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsDataMembers, out dataFractionLaws)
		    && LooksLikeDataFractionLaws(dataFractionLaws))
		{
			TryRegisterLogicFractionLawsForDataSide(source, null);
			return true;
		}
		if (TryResolveDataSideFromLawOwner(source, out var dataSide)
		    && TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var sideIndex))
		{
			lock (LogicFractionLawsBySideIndex)
			{
				if (LogicFractionLawsBySideIndex.TryGetValue(sideIndex, out logicFractionLaws)
				    && logicFractionLaws != null
				    && TryReadExactObject(logicFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsDataMembers, out dataFractionLaws)
				    && LooksLikeDataFractionLaws(dataFractionLaws))
					return true;
			}
		}
		return false;
	}

	private static bool TryRegisterLogicFractionLawsForDataSide(object logicSideOrFractionLaws, object knownDataSide)
	{
		if (logicSideOrFractionLaws == null)
			return false;
		object logicFractionLaws = null;
		object dataSide = knownDataSide;
		if (TryReadExactObject(logicSideOrFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicFractionLawsDataMembers, out _))
			logicFractionLaws = logicSideOrFractionLaws;
		else if (!TryReadExactObject(logicSideOrFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicSideFractionLawsMembers, out logicFractionLaws))
			return false;
		if (logicFractionLaws == null)
			return false;
		if (dataSide == null && !TryReadExactObject(logicSideOrFractionLaws, GameSymbols.CustomFactionLawRuntime.LogicSideDataSideMembers, out dataSide))
			return false;
		if (dataSide == null || !TryReadExactInt(dataSide, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers, out var sideIndex))
			return false;
		lock (LogicFractionLawsBySideIndex)
		{
			LogicFractionLawsBySideIndex[sideIndex] = logicFractionLaws;
		}
		return true;
	}
	private static bool TryBuildActiveLawState(object dataLaw, string factionSid, string expectedLawSid, int lawIndex, out ActiveLawState state)
	{
		state = default;
		if (dataLaw == null)
			return false;
		if (!TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLevelMembers, out var rank))
			return false;
		if (rank <= 0)
			return false;
		if (!TryReadExactBool(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawWasAppliedMembers, out var wasApplied))
			return false;
		if (!wasApplied)
			return false;
		if (!TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLineMembers, out var line))
			return false;
		if (!TryReadExactInt(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawGroupMembers, out var group))
			return false;
		if (!TryGetKnownLawFamily(lawIndex, out var family))
			return false;
		state = new ActiveLawState
		{
			FactionSid = factionSid,
			LawSid = expectedLawSid,
			Family = family,
			Index = lawIndex,
			Rank = rank,
			Line = line,
			Group = group,
			WasApplied = wasApplied,
		};
		return true;
	}

	private static int TryPatchNativeLawActivationDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; native FractionLaws activation diagnostics not registered.");
			return 0;
		}
		var type = FindFirstRuntimeType(GameSymbols.CustomFactionLawRuntime.LogicFractionLawsTypeHints);
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: exact Logic.FractionLaws runtime type was not found; native activation diagnostics not registered.");
			return 0;
		}

		var patched = 0;
		foreach (var methodName in GameSymbols.CustomFactionLawRuntime.LogicFractionLawCanApplyMethods)
			patched += PatchExact(harmony, log, type, methodName, 2, nameof(PostfixNativeLawCanApply));
		foreach (var methodName in GameSymbols.CustomFactionLawRuntime.LogicFractionLawApplyMethods)
			patched += PatchExactPrefixPostfix(harmony, log, type, methodName, 2, nameof(PrefixNativeLawApply), nameof(PostfixNativeLawApply));
		if (patched == 0)
			log?.LogWarning("Homm3CustomFactionLawRuntime: no exact Logic.FractionLaws activation diagnostic surfaces were registered.");
		return patched;
	}

	private static int TryPatchLawViewDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; law-rank diagnostics not registered.");
			return 0;
		}

		var patched = 0;
		var type = FindRuntimeType("Hex.Session.UI.BhFractionLawView");
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: BhFractionLawView type not found; law-rank diagnostics not registered.");
			return 0;
		}

		foreach (var methodName in GameSymbols.CustomFactionLawRuntime.FractionLawViewBind.NameHints)
			patched += PatchExact(harmony, log, type, methodName, 2, nameof(PostfixFractionLawViewBind));
		foreach (var methodName in GameSymbols.CustomFactionLawRuntime.FractionLawViewRefresh.NameHints)
			patched += PatchExact(harmony, log, type, methodName, 0, nameof(PostfixFractionLawViewRefresh));
		if (patched == 0)
			log?.LogWarning("Homm3CustomFactionLawRuntime: no exact BhFractionLawView diagnostics surfaces were registered.");
		return patched;
	}

	private static int TryPatchDataSideInitPreseedDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; Data.Side init preseed diagnostics not registered.");
			return 0;
		}
		var type = FindRuntimeType("Hex.Session.Data.Side");
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Hex.Session.Data.Side type not found; Data.Side init preseed diagnostics not registered.");
			return 0;
		}
		return PatchExactDataLifecycleSignature(
			harmony,
			log,
			type,
			typeof(void),
			new[] { "Int32", "StartInfo", "StartSide", "MapData", "SerializableRandom", "DifficultyEconomic" },
			expectedMatches: 1,
			nameof(PostfixDataSideInitPreseed),
			GameSymbols.CustomFactionLawRuntime.DataSideInit.Id);
	}
	private static int TryPatchDataSidesPreseedDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; DataSides preseed diagnostics not registered.");
			return 0;
		}

		var type = FindRuntimeType("Hex.Session.Data.DataSides");
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Hex.Session.Data.DataSides type not found; DataSides preseed diagnostics not registered.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactDataSidesSignature(harmony, log, type, new[] { "StartInfo", "MapData", "SerializableRandom", "DifficultyEconomic" }, nameof(PostfixDataSidesPreseed), GameSymbols.CustomFactionLawRuntime.DataSidesNewGamePopulate.Id);
		patched += PatchExactDataSidesSignature(harmony, log, type, new[] { "jo" }, nameof(PostfixDataSidesPreseed), GameSymbols.CustomFactionLawRuntime.DataSidesLoadPopulate.Id);
		patched += PatchExactDataSidesSignature(harmony, log, type, new[] { "StartInfo", "MetaInfo" }, nameof(PostfixDataSidesPreseed), GameSymbols.CustomFactionLawRuntime.DataSidesMetaPopulate.Id);
		if (patched == 0)
			log?.LogWarning("Homm3CustomFactionLawRuntime: no exact DataSides preseed diagnostics surfaces were registered.");
		return patched;
	}

	private static int TryPatchDataRootPreseedDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; Data root preseed diagnostics not registered.");
			return 0;
		}

		var type = FindRuntimeType("Hex.Session.Data.Data");
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Hex.Session.Data.Data type not found; Data root preseed diagnostics not registered.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactDataLifecycleSignature(harmony, log, type, typeof(void), new[] { "ObjectPublicStchSeMachDi2SichStUnique" }, expectedMatches: 1, nameof(PostfixDataRootPreseed), GameSymbols.CustomFactionLawRuntime.DataRootConstructFromSession.Id);
		patched += PatchExactDataLifecycleSignature(harmony, log, type, typeof(bool), new[] { "StartInfo" }, expectedMatches: 2, nameof(PostfixDataRootPreseed), GameSymbols.CustomFactionLawRuntime.DataRootNewGamePopulate.Id + "/" + GameSymbols.CustomFactionLawRuntime.DataRootRestartPopulate.Id);
		patched += PatchExactDataLifecycleSignature(harmony, log, type, typeof(void), new[] { "StartInfo", "MetaInfo" }, expectedMatches: 1, nameof(PostfixDataRootPreseed), GameSymbols.CustomFactionLawRuntime.DataRootMetaPopulate.Id);
		if (patched == 0)
			log?.LogWarning("Homm3CustomFactionLawRuntime: no exact Data root preseed diagnostics surfaces were registered.");
		return patched;
	}

	private static int TryPatchLogicRootPreseedDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; Logic root preseed diagnostics not registered.");
			return 0;
		}
		var type = FindFirstRuntimeType(GameSymbols.CustomFactionLawRuntime.GlobalLogicRootTypeHints);
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: exact Logic root runtime type was not found; dto side-collection diagnostics not registered.");
			return 0;
		}
		return PatchExactDataLifecycleSignature(harmony, log, type, typeof(void), GameSymbols.CustomFactionLawRuntime.LogicRootInitParameterTypes, expectedMatches: 2, nameof(PostfixLogicRootPreseed), "customFactionLaw.logicRoot.sideCollectionInit");
	}
	private static int TryPatchLogicSidePreseedDiagnostics(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Harmony was null; Logic side preseed diagnostics not registered.");
			return 0;
		}

		var type = FindFirstRuntimeType(GameSymbols.CustomFactionLawRuntime.LogicSideRuntimeTypeNames);
		if (type == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: exact Logic side runtime type was not found; Logic.FractionLaws preseed diagnostics not registered.");
			return 0;
		}

		ConstructorInfo selected = null;
		var matches = 0;
		foreach (var ctor in type.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			var ps = ctor.GetParameters();
			if (ps.Length != GameSymbols.CustomFactionLawRuntime.LogicSideConstructorParameterTypes.Length)
				continue;
			if (!ParameterTypesMatch(ps, GameSymbols.CustomFactionLawRuntime.LogicSideConstructorParameterTypes))
				continue;
			selected = ctor;
			matches++;
		}
		if (matches != 1 || selected == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Logic side preseed surface failed closed; expected exactly one constructor on "
				+ type.FullName + " with (" + string.Join(",", GameSymbols.CustomFactionLawRuntime.LogicSideConstructorParameterTypes)
				+ "), found=" + matches.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".");
			return 0;
		}
		var postfix = typeof(Homm3CustomFactionLawRuntime).GetMethod(nameof(PostfixLogicSidePreseed), BindingFlags.Static | BindingFlags.NonPublic);
		harmony.Patch(selected, postfix: new HarmonyMethod(postfix));
		log?.LogInfo("Homm3CustomFactionLawRuntime: Logic side constructor preseed postfix registered on " + FormatMethod(selected) + ". Diagnostic observation only.");
		return 1;
	}
	private static int PatchExactDataSidesSignature(Harmony harmony, ManualLogSource log, Type owner, string[] parameterTypeNames, string postfixName, string symbolId)
	{
		if (harmony == null || owner == null || parameterTypeNames == null)
			return 0;
		MethodInfo selected = null;
		var matches = 0;
		foreach (var method in owner.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != parameterTypeNames.Length)
				continue;
			var same = true;
			for (var i = 0; i < ps.Length; i++)
			{
				var expected = parameterTypeNames[i];
				var actual = ps[i].ParameterType.Name;
				var actualFull = ps[i].ParameterType.FullName ?? actual;
				if (!string.Equals(actual, expected, StringComparison.Ordinal)
				    && !string.Equals(actualFull, expected, StringComparison.Ordinal)
				    && !actualFull.EndsWith("." + expected, StringComparison.Ordinal))
				{
					same = false;
					break;
				}
			}
			if (!same)
				continue;
			selected = method;
			matches++;
		}
		if (matches != 1 || selected == null)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: DataSides preseed surface '" + symbolId + "' failed closed; expected exactly one void(" + string.Join(",", parameterTypeNames) + ") method on " + owner.FullName + ", found=" + matches.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".");
			return 0;
		}
		var postfix = typeof(Homm3CustomFactionLawRuntime).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: refusing incompatible DataSides preseed postfix for " + FormatMethod(selected) + ": " + reason);
			return 0;
		}
		harmony.Patch(selected, postfix: new HarmonyMethod(postfix));
		log?.LogInfo("Homm3CustomFactionLawRuntime: DataSides preseed postfix registered on " + FormatMethod(selected) + " for '" + symbolId + "'. Diagnostic observation only.");
		return 1;
	}

	private static int PatchExactDataLifecycleSignature(Harmony harmony, ManualLogSource log, Type owner, Type requiredReturnType, string[] parameterTypeNames, int expectedMatches, string postfixName, string symbolId)
	{
		if (harmony == null || owner == null || parameterTypeNames == null)
			return 0;
		var selected = new List<MethodInfo>();
		foreach (var method in owner.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (requiredReturnType != null && method.ReturnType != requiredReturnType)
				continue;
			var ps = method.GetParameters();
			if (ps.Length != parameterTypeNames.Length)
				continue;
			if (!ParameterTypesMatch(ps, parameterTypeNames))
				continue;
			selected.Add(method);
		}
		if (selected.Count != expectedMatches)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: Data root preseed surface '" + symbolId + "' failed closed; expected exactly "
				+ expectedMatches.ToString(System.Globalization.CultureInfo.InvariantCulture) + " "
				+ (requiredReturnType == null ? "any" : requiredReturnType.Name)
				+ "(" + string.Join(",", parameterTypeNames) + ") method(s) on " + owner.FullName
				+ ", found=" + selected.Count.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".");
			return 0;
		}
		var postfix = typeof(Homm3CustomFactionLawRuntime).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		var patched = 0;
		foreach (var method in selected)
		{
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
			{
				log?.LogWarning("Homm3CustomFactionLawRuntime: refusing incompatible Data root preseed postfix for " + FormatMethod(method) + ": " + reason);
				continue;
			}
			harmony.Patch(method, postfix: new HarmonyMethod(postfix));
			patched++;
			log?.LogInfo("Homm3CustomFactionLawRuntime: Data root preseed postfix registered on " + FormatMethod(method) + " for '" + symbolId + "'. Diagnostic observation only.");
		}
		return patched;
	}

	private static bool ParameterTypesMatch(ParameterInfo[] ps, string[] parameterTypeNames)
	{
		for (var i = 0; i < ps.Length; i++)
		{
			var expected = parameterTypeNames[i];
			var actual = ps[i].ParameterType.Name;
			var actualFull = ps[i].ParameterType.FullName ?? actual;
			if (!string.Equals(actual, expected, StringComparison.Ordinal)
			    && !string.Equals(actualFull, expected, StringComparison.Ordinal)
			    && !actualFull.EndsWith("." + expected, StringComparison.Ordinal))
				return false;
		}
		return true;
	}

	private static int PatchExactPrefixPostfix(Harmony harmony, ManualLogSource log, Type owner, string methodName, int parameterCount, string prefixName, string postfixName)
	{
		if (string.IsNullOrWhiteSpace(methodName))
			return 0;
		try
		{
			MethodInfo selected = null;
			foreach (var method in owner.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name == methodName && method.GetParameters().Length == parameterCount)
				{
					selected = method;
					break;
				}
			}
			if (selected == null)
				return 0;

			var prefix = string.IsNullOrWhiteSpace(prefixName) ? null : typeof(Homm3CustomFactionLawRuntime).GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
			var postfix = string.IsNullOrWhiteSpace(postfixName) ? null : typeof(Homm3CustomFactionLawRuntime).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (prefix != null && !GameMember.IsHarmonyPatchCompatible(selected, prefix, out var prefixReason))
			{
				log?.LogWarning("Homm3CustomFactionLawRuntime: refusing incompatible prefix for " + FormatMethod(selected) + ": " + prefixReason);
				return 0;
			}
			if (postfix != null && !GameMember.IsHarmonyPatchCompatible(selected, postfix, out var postfixReason))
			{
				log?.LogWarning("Homm3CustomFactionLawRuntime: refusing incompatible postfix for " + FormatMethod(selected) + ": " + postfixReason);
				return 0;
			}

			harmony.Patch(selected, prefix: prefix == null ? null : new HarmonyMethod(prefix), postfix: postfix == null ? null : new HarmonyMethod(postfix));
			log?.LogInfo("Homm3CustomFactionLawRuntime: diagnostic prefix/postfix registered on " + FormatMethod(selected) + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: failed to patch " + owner.FullName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchExact(Harmony harmony, ManualLogSource log, Type owner, string methodName, int parameterCount, string postfixName)
	{
		if (string.IsNullOrWhiteSpace(methodName))
			return 0;
		try
		{
			MethodInfo selected = null;
			foreach (var method in owner.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name == methodName && method.GetParameters().Length == parameterCount)
				{
					selected = method;
					break;
				}
			}
			if (selected == null)
				return 0;

			var postfix = typeof(Homm3CustomFactionLawRuntime).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3CustomFactionLawRuntime: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}

			harmony.Patch(selected, postfix: new HarmonyMethod(postfix));
			log?.LogInfo("Homm3CustomFactionLawRuntime: diagnostic postfix registered on " + FormatMethod(selected) + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomFactionLawRuntime: failed to patch " + owner.FullName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static bool TryReadKnownCustomLawArgs(object[] args, out string lawSid, out int rank, out string factionSid, out int lawIndex, out string family)
	{
		lawSid = null;
		rank = 0;
		factionSid = null;
		lawIndex = 0;
		family = null;
		if (args == null || args.Length < 2)
			return false;
		lawSid = args[0] as string;
		if (!(args[1] is int nativeRank))
			return false;
		rank = nativeRank;
		return TryParseKnownCustomLawId(lawSid, out factionSid, out lawIndex, out family);
	}

	private static void PostfixNativeLawCanApply(object __instance, object[] __args, bool __result, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		if (!TryReadKnownCustomLawArgs(__args, out var lawSid, out var rank, out var factionSid, out var lawIndex, out var family))
			return;
		if (_loggedNativeLawCanApply++ >= 60)
			return;
		Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: native law canApply observed method="
			+ FormatMethod(__originalMethod)
			+ " law='" + lawSid + "' faction='" + factionSid + "' index=" + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " family='" + family + "' requestedRank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " result=" + __result
			+ " current=" + ExplainActiveKnownCustomLawResolution(__instance, lawIndex)
			+ ". Diagnostic observation only.");
	}

	private static void PrefixNativeLawApply(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		if (!TryReadKnownCustomLawArgs(__args, out var lawSid, out var rank, out var factionSid, out var lawIndex, out var family))
			return;
		if (_loggedNativeLawApply++ >= 80)
			return;
		Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: native law apply prefix observed method="
			+ FormatMethod(__originalMethod)
			+ " law='" + lawSid + "' faction='" + factionSid + "' index=" + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " family='" + family + "' requestedRank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " before=" + ExplainActiveKnownCustomLawResolution(__instance, lawIndex)
			+ ". Diagnostic observation only.");
	}

	private static void PostfixNativeLawApply(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		if (!TryReadKnownCustomLawArgs(__args, out var lawSid, out var rank, out var factionSid, out var lawIndex, out var family))
			return;
		if (_loggedNativeLawApply++ >= 80)
			return;
		var after = TryResolveActiveKnownCustomLaw(__instance, lawIndex, out var state)
			? "after=" + state
			: "after=" + ExplainActiveKnownCustomLawResolution(__instance, lawIndex);
		Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: native law apply postfix proof candidate method="
			+ FormatMethod(__originalMethod)
			+ " law='" + lawSid + "' faction='" + factionSid + "' index=" + lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " family='" + family + "' requestedRank=" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " " + after
			+ ". This proves only legal native apply observation if paired with canApply/visible law-tree evidence; packet gameplay remains disabled.");
	}

	private static void PostfixLogicRootPreseed(object __instance, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		try
		{
			PreseedLogicRootSideCollection(__instance, "logic-root-init:" + FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: Logic root side-collection preseed failed closed after "
				+ FormatMethod(__originalMethod)
				+ ": " + ex.Message + ". Diagnostic observation only.");
		}
	}
	private static void PostfixLogicSidePreseed(object __instance, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		try
		{
			if (!TryRegisterLogicFractionLawsForDataSide(__instance, null))
			{
				LogNativeLawSeed("logic-side constructor observed but exact Logic.FractionLaws/Data.Side registration failed after " + FormatMethod(__originalMethod) + ".");
				return;
			}
			if (TryResolveDataSideFromLawOwner(__instance, out var dataSide))
				TryPreseedDataSide(dataSide, "logic-side-constructor:" + FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: Logic side preseed failed closed after "
				+ FormatMethod(__originalMethod)
				+ ": " + ex.Message + ". Diagnostic observation only.");
		}
	}
	private static void PostfixDataSideInitPreseed(object __instance, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		try
		{
			TryPreseedDataSide(__instance, FormatMethod(__originalMethod as MethodInfo));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: Data.Side init preseed failed closed after "
				+ FormatMethod(__originalMethod as MethodInfo)
				+ ": " + ex.Message + ". Diagnostic observation only.");
		}
	}
	private static void PostfixDataSidesPreseed(object __instance, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		try
		{
			PreseedDataSidesArray(__instance, FormatMethod(__originalMethod as MethodInfo));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: DataSides preseed failed closed after "
				+ FormatMethod(__originalMethod as MethodInfo)
				+ ": " + ex.Message + ". Diagnostic observation only.");
		}
	}

	private static void PostfixDataRootPreseed(object __instance, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		try
		{
			PreseedDataRoot(__instance, FormatMethod(__originalMethod as MethodInfo));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CustomFactionLawRuntime: Data root preseed failed closed after "
				+ FormatMethod(__originalMethod as MethodInfo)
				+ ": " + ex.Message + ". Diagnostic observation only.");
		}
	}

	private static void PostfixFractionLawViewBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		if (_loggedBind++ >= 30)
			return;

		var side = __args != null && __args.Length > 0 ? __args[0] : null;
		var law = __args != null && __args.Length > 1 ? __args[1] : null;
		if (side != null)
			_lastLawTreeLogicSide = side;
		if (TryResolveDataSideFromLawOwner(side, out var lawViewDataSide))
		{
			_lastLawTreeDataSide = lawViewDataSide;
			TryPreseedDataSide(lawViewDataSide, "law-view-bind-side");
		}
		Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: bind "
			+ FormatMethod(__originalMethod as MethodInfo)
			+ " view=" + DescribeObject(__instance)
			+ " side=" + DescribeSideCandidate(side)
			+ " law=" + DescribeLawCandidate(law)
			+ ".");
	}

	private static void PostfixFractionLawViewRefresh(object __instance, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		if (_loggedRefresh++ >= 20)
			return;
		Plugin.LogSource?.LogInfo("Homm3CustomFactionLawRuntime: refresh "
			+ FormatMethod(__originalMethod as MethodInfo)
			+ " view=" + DescribeObject(__instance)
			+ ".");
	}

	private static string DescribeSideCandidate(object side)
	{
		if (side == null)
			return "null";
		var type = side.GetType();
		var sb = new StringBuilder();
		sb.Append(DescribeObject(side));
		AppendResolverProbe(sb, side);
		AppendNamedValues(sb, side, type, GameSymbols.CustomFactionLawRuntime.SideFactionFields, "side");
		AppendExactGetterObjects(sb, side, type, GameSymbols.CustomFactionLawRuntime.SideRootGetters, "side");
		AppendExactGetterObjects(sb, side, type, GameSymbols.CustomFactionLawRuntime.SideFractionLawsGetters, "side");
		foreach (var field in GameSymbols.CustomFactionLawRuntime.SideFractionConfigFields)
		{
			var config = TryGetMemberValue(side, type, field);
			if (config == null)
				continue;
			sb.Append(" ").Append(field).Append("->").Append(DescribeObject(config));
			AppendNamedValues(sb, config, config.GetType(), GameSymbols.CustomFactionLawRuntime.FractionConfigIdFields, field);
		}
		return sb.ToString();
	}

	private static void AppendResolverProbe(StringBuilder sb, object side)
	{
		var matched = 0;
		var first = true;
		foreach (var lawIndex in KnownRuntimeLawIndices)
		{
			if (!TryResolveActiveKnownCustomLaw(side, lawIndex, out var state))
				continue;
			if (first)
			{
				sb.Append(" activeCustomLaws=[");
				first = false;
			}
			else
			{
				sb.Append("; ");
			}
			sb.Append(state);
			matched++;
			if (matched >= 8)
				break;
		}
		if (!first)
			sb.Append("]");
	}

	private static string DescribeLawCandidate(object law)
	{
		if (law == null)
			return "null";
		var sb = new StringBuilder();
		DescribeLawCandidate(law, new HashSet<int>(), 0, sb, "law");
		return sb.ToString();
	}

	private static void DescribeLawCandidate(object law, HashSet<int> seen, int depth, StringBuilder sb, string label)
	{
		if (law == null || depth > 3 || sb.Length > 1600)
			return;
		var key = RuntimeHelpersGetHashCode(law);
		if (!seen.Add(key))
			return;

		var type = law.GetType();
		if (sb.Length > 0)
			sb.Append(" ");
		sb.Append(label).Append("=").Append(DescribeObject(law));
		AppendNamedValues(sb, law, type, GameSymbols.CustomFactionLawRuntime.LawDataFields, label);
		AppendExactGetterValues(sb, law, type, GameSymbols.CustomFactionLawRuntime.LawLevelGetters, label);
		AppendDataFractionLawIdentity(sb, law, label);

		foreach (var field in GameSymbols.CustomFactionLawRuntime.LawRuntimeFields)
		{
			var nested = TryGetMemberValue(law, type, field);
			if (nested == null || nested is string)
				continue;
			DescribeLawCandidate(nested, seen, depth + 1, sb, label + "." + field);
		}
		foreach (var getter in GameSymbols.CustomFactionLawRuntime.LawDataGetters)
		{
			var nested = TryInvokeExactNoArgGetter(law, type, getter);
			if (nested == null || nested is string)
				continue;
			DescribeLawCandidate(nested, seen, depth + 1, sb, label + "." + getter + "()");
		}
		foreach (var getter in GameSymbols.CustomFactionLawRuntime.LawConfigGetters)
		{
			var nested = TryInvokeExactNoArgGetter(law, type, getter);
			if (nested == null || nested is string)
				continue;
			DescribeLawCandidate(nested, seen, depth + 1, sb, label + "." + getter + "()");
		}
	}

	private static bool TryExtractDataFractionLawForDiagnostic(object candidate, out object dataLaw)
	{
		dataLaw = null;
		if (candidate == null)
			return false;
		if (TryReadExactString(candidate, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, out _))
		{
			dataLaw = candidate;
			return true;
		}
		if (TryReadExactObject(candidate, GameSymbols.CustomFactionLawRuntime.LawDataGetters, out dataLaw)
			&& dataLaw != null)
			return true;
		foreach (var field in GameSymbols.CustomFactionLawRuntime.LawRuntimeFields)
		{
			var nested = TryGetMemberValueDeep(candidate, candidate.GetType(), field);
			if (nested == null || nested is string)
				continue;
			if (TryReadExactString(nested, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, out _))
			{
				dataLaw = nested;
				return true;
			}
		}
		return false;
	}
	private static void AppendDataFractionLawIdentity(StringBuilder sb, object candidate, string prefix)
	{
		if (!TryExtractDataFractionLawForDiagnostic(candidate, out var dataLaw))
			return;
		AppendExactStringValue(sb, dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, prefix + ".dataLaw.sid");
		AppendExactIntValue(sb, dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLevelMembers, prefix + ".dataLaw.level");
		AppendExactIntValue(sb, dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawLineMembers, prefix + ".dataLaw.line");
		AppendExactIntValue(sb, dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawGroupMembers, prefix + ".dataLaw.group");
		AppendExactBoolValue(sb, dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawWasAppliedMembers, prefix + ".dataLaw.wasApplied");
		if (TryReadExactString(dataLaw, GameSymbols.CustomFactionLawRuntime.DataFractionLawSidMembers, out var lawSid)
			&& TryParseKnownCustomLawId(lawSid, out var factionSid, out var lawIndex, out var family))
		{
			sb.Append(" ").Append(prefix).Append(".knownCustomLaw faction='").Append(factionSid)
				.Append("' index=").Append(lawIndex.ToString(System.Globalization.CultureInfo.InvariantCulture))
				.Append(" family='").Append(family).Append("'");
		}
	}
	private static void AppendExactStringValue(StringBuilder sb, object obj, string[] names, string label)
	{
		if (TryReadExactString(obj, names, out var value))
		{
			sb.Append(" ").Append(label).Append("='").Append(value).Append("'");
			AppendKnownCustomLawParse(sb, value, label);
		}
	}

	private static void AppendExactIntValue(StringBuilder sb, object obj, string[] names, string label)
	{
		if (TryReadExactInt(obj, names, out var value))
			sb.Append(" ").Append(label).Append("=").Append(value.ToString(System.Globalization.CultureInfo.InvariantCulture));
	}

	private static void AppendExactBoolValue(StringBuilder sb, object obj, string[] names, string label)
	{
		if (TryReadExactBool(obj, names, out var value))
			sb.Append(" ").Append(label).Append("=").Append(value ? "true" : "false");
	}
	private static void AppendNamedValues(StringBuilder sb, object obj, Type type, string[] names, string prefix)
	{
		foreach (var name in names)
		{
			var value = TryGetMemberValue(obj, type, name);
			if (value == null)
				continue;
			if (value is string s)
			{
				sb.Append(" ").Append(prefix).Append(".").Append(name).Append("='").Append(s).Append("'");
				AppendKnownCustomLawParse(sb, s, prefix + "." + name);
			}
			else if (value.GetType().IsPrimitive || value is decimal)
				sb.Append(" ").Append(prefix).Append(".").Append(name).Append("=").Append(value);
		}
	}

	private static object TryGetMemberValue(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (field != null)
				return field.GetValue(obj);
		}
		catch { }
		return null;
	}

	private static bool TryReadExactObject(object obj, string[] names, out object value)
	{
		value = null;
		if (obj == null || names == null)
			return false;
		var type = obj.GetType();
		foreach (var name in names)
		{
			value = TryGetMemberValueDeep(obj, type, name);
			if (value != null)
				return true;
			value = TryInvokeExactNoArgGetterDeep(obj, type, name);
			if (value != null)
				return true;
		}
		return false;
	}

	private static object TryGetMemberValueDeep(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			var value = TryGetMemberValue(obj, current, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryInvokeExactNoArgGetterDeep(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			var value = TryInvokeExactNoArgGetter(obj, current, name);
			if (value != null)
				return value;
		}
		foreach (var iface in type.GetInterfaces())
		{
			var value = TryInvokeExactNoArgGetter(obj, iface, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static bool TryReadExactString(object obj, string[] names, out string value)
	{
		value = null;
		if (!TryReadExactObject(obj, names, out var raw))
			return false;
		value = raw as string;
		return !string.IsNullOrWhiteSpace(value);
	}

	private static bool TryReadExactInt(object obj, string[] names, out int value)
	{
		value = 0;
		if (!TryReadExactObject(obj, names, out var raw))
			return false;
		if (raw is int i)
		{
			value = i;
			return true;
		}
		return false;
	}

	private static bool TryReadExactBool(object obj, string[] names, out bool value)
	{
		value = false;
		if (!TryReadExactObject(obj, names, out var raw))
			return false;
		if (raw is bool b)
		{
			value = b;
			return true;
		}
		return false;
	}

	private static void AppendExactGetterValues(StringBuilder sb, object obj, Type type, string[] names, string prefix)
	{
		foreach (var name in names)
		{
			var value = TryInvokeExactNoArgGetter(obj, type, name);
			if (value == null)
				continue;
			if (value is string s)
			{
				sb.Append(" ").Append(prefix).Append(".").Append(name).Append("()='").Append(s).Append("'");
				AppendKnownCustomLawParse(sb, s, prefix + "." + name + "()");
			}
			else if (value.GetType().IsPrimitive || value is decimal)
				sb.Append(" ").Append(prefix).Append(".").Append(name).Append("()=").Append(value);
		}
	}

	private static void AppendKnownCustomLawParse(StringBuilder sb, string lawSid, string label)
	{
		if (!TryParseKnownCustomLawId(lawSid, out var factionSid, out var index, out var family))
			return;
		sb.Append(" ")
			.Append(label)
			.Append(".parsed={faction='")
			.Append(factionSid)
			.Append("' index=")
			.Append(index)
			.Append(" family='")
			.Append(family)
			.Append("'}");
	}

	private static void AppendExactGetterObjects(StringBuilder sb, object obj, Type type, string[] names, string prefix)
	{
		foreach (var name in names)
		{
			var value = TryInvokeExactNoArgGetter(obj, type, name);
			if (value == null || value is string)
				continue;
			sb.Append(" ").Append(prefix).Append(".").Append(name).Append("()->").Append(DescribeObject(value));
		}
	}

	private static bool TryInvokeExactObjectMethod(object obj, string[] names, object[] args, out object value)
	{
		value = null;
		if (obj == null || names == null || args == null)
			return false;
		var type = obj.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				foreach (var method in methods)
				{
					if (method.Name != name || method.ContainsGenericParameters || method.ReturnType == typeof(void))
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length != args.Length)
						continue;
					var compatible = true;
					for (var i = 0; i < parameters.Length; i++)
					{
						if (args[i] != null && !parameters[i].ParameterType.IsInstanceOfType(args[i]))
						{
							compatible = false;
							break;
						}
					}
					if (!compatible)
						continue;
					value = method.Invoke(obj, args);
					return value != null;
				}
			}
			catch { }
		}
		return false;
	}

	private static bool TryInvokeExactBoolMethod(object obj, string[] names, object[] args, out bool value)
	{
		value = false;
		if (!TryInvokeExactObjectMethod(obj, names, args, out var raw))
			return false;
		if (raw is bool b)
		{
			value = b;
			return true;
		}
		return false;
	}

	private static bool TryInvokeExactIntMethod(object obj, string[] names, object[] args, out int value)
	{
		value = 0;
		if (!TryInvokeExactObjectMethod(obj, names, args, out var raw)) return false;
		if (raw is int i) { value = i; return true; }
		return false;
	}

	private static bool TryInvokeExactVoidMethod(object obj, string[] names, object[] args, out string failure)
	{
		failure = null;
		if (obj == null)
		{
			failure = "target object is null";
			return false;
		}
		if (names == null || args == null)
		{
			failure = "method names or arguments are null";
			return false;
		}
		var type = obj.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				foreach (var method in methods)
				{
					if (method.Name != name || method.ContainsGenericParameters || method.ReturnType != typeof(void))
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length != args.Length)
						continue;
					var compatible = true;
					for (var i = 0; i < parameters.Length; i++)
					{
						if (args[i] != null && !parameters[i].ParameterType.IsInstanceOfType(args[i]))
						{
							compatible = false;
							break;
						}
					}
					if (!compatible)
						continue;
					method.Invoke(obj, args);
					return true;
				}
			}
			catch (Exception ex)
			{
				failure = "exception invoking " + type.FullName + "." + name + ": " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}
		failure = "no exact void method matched on " + (type.FullName ?? type.Name);
		return false;
	}
	private static object TryInvokeExactNoArgGetter(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var method = type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly, null, Type.EmptyTypes, null);
			if (method == null || method.ContainsGenericParameters || method.ReturnType == typeof(void))
				return null;
			return method.Invoke(obj, null);
		}
		catch { }
		return null;
	}

	private static Type FindFirstRuntimeType(string[] fullNames)
	{
		if (fullNames == null)
			return null;
		for (var i = 0; i < fullNames.Length; i++)
		{
			var type = FindRuntimeType(fullNames[i]);
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type FindRuntimeType(string fullName)
	{
		var type = ModActions.GetHexType(fullName);
		if (type != null)
			return type;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				type = asm.GetType(fullName, throwOnError: false);
				if (type != null)
					return type;
			}
			catch { }
		}
		return null;
	}

	private static string JsonEscape(string value)
	{
		if (string.IsNullOrEmpty(value)) return "";
		return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
	}

	private static string DescribeObject(object obj)
	{
		if (obj == null)
			return "null";
		return obj.GetType().FullName ?? obj.GetType().Name;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static int RuntimeHelpersGetHashCode(object obj)
	{
		return obj == null ? 0 : System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
	}
}



