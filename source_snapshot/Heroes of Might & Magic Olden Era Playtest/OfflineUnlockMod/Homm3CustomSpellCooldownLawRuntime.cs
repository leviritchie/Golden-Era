using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Packet-gated spell cooldown law runtime entry points.
/// This class registers no Harmony hooks. Future exact spell/cast/Focus hooks
/// must call this class only after runtime proof establishes cooldown storage,
/// cast-gate, and spellbook UI synchronization ordering.
/// </summary>
internal static class Homm3CustomSpellCooldownLawRuntime
{
		internal const string TowerTierOneNoCooldownPilotFlag = "homm3_tower_tier_one_no_cooldown_runtime_pilot.flag";
	private const int LogCap = 48;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;

		if (!Homm3CustomLawPacketGate.IsGameplayAllowed(Homm3CustomLawPacketGate.SpellCooldown, out var packetFail)
		    && !Homm3DiagnosticFlags.IsEnabled(TowerTierOneNoCooldownPilotFlag))
		{
			_registrationAuditStatus = "BLOCKED_BY_PACKET_GATE: " + packetFail;
			log?.LogInfo("HoMM3 spell-cooldown runtime not registered: " + packetFail);
			return;
		}
		if (Homm3DiagnosticFlags.IsEnabled(TowerTierOneNoCooldownPilotFlag))
			log?.LogWarning("HoMM3 Tower tier-1 no-cooldown runtime pilot flag is enabled; spell-cooldown packet proof remains unpromoted.");

		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellLogic);
		if (type == null)
		{
			_registrationAuditStatus = "FAILED_CLOSED: exact battle spell logic type not found";
			log?.LogWarning("HoMM3 spell-cooldown runtime failed closed: exact battle spell logic type not found.");
			return;
		}

		var method = ResolveExactMethod(type, GameSymbols.SpellCooldownLaws.AddCooldownIfReady.NameHints, typeof(void), new[] { "Int32" });
		if (method == null)
		{
			_registrationAuditStatus = "FAILED_CLOSED: exact AddCooldownIfReady method not found";
			log?.LogWarning("HoMM3 spell-cooldown runtime failed closed: exact AddCooldownIfReady method not found.");
			return;
		}

		var prefix = AccessTools.Method(typeof(Homm3CustomSpellCooldownLawRuntime), nameof(PrefixAddCooldownIfReady));
		var postfix = AccessTools.Method(typeof(Homm3CustomSpellCooldownLawRuntime), nameof(PostfixAddCooldownIfReady));
		string reason = null;
		if (prefix == null || !GameMember.IsHarmonyPatchCompatible(method, prefix, out reason))
		{
			_registrationAuditStatus = "FAILED_CLOSED: incompatible AddCooldownIfReady prefix: " + (reason ?? "prefix not found");
			log?.LogWarning("HoMM3 spell-cooldown runtime failed closed: incompatible AddCooldownIfReady prefix: " + (reason ?? "prefix not found"));
			return;
		}
		if (postfix == null || !GameMember.IsHarmonyPatchCompatible(method, postfix, out reason))
		{
			_registrationAuditStatus = "FAILED_CLOSED: incompatible AddCooldownIfReady postfix: " + (reason ?? "postfix not found");
			log?.LogWarning("HoMM3 spell-cooldown runtime failed closed: incompatible AddCooldownIfReady postfix: " + (reason ?? "postfix not found"));
			return;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(prefix) { priority = Priority.First }, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		_registrationAuditStatus = "REGISTERED_EXACT_ADD_COOLDOWN_PREFIX_POSTFIX=" + FormatMethod(method);
		log?.LogInfo("HoMM3 spell-cooldown runtime registered exact AddCooldownIfReady prefix/postfix on " + FormatMethod(method) + ".");
	}

	private static void PrefixAddCooldownIfReady(object __instance, MethodBase __originalMethod, object[] __args)
	{
		try
		{
			if (__args == null || __args.Length != 1 || __args[0] is not int requestedCooldown)
			{
				LogLimited("HoMM3 spell-cooldown runtime failed closed: AddCooldownIfReady prefix argument shape changed.");
				return;
			}

			if (TryApplyFortressBogHexCooldownPenalty(__instance, requestedCooldown, out var adjustedCooldown, out var detail, out var failReason))
			{
				__args[0] = adjustedCooldown;
				LogLimited("HoMM3 Fortress Bog Hex cooldown penalty applied before native AddCooldownIfReady: method=" + FormatMethod(__originalMethod) + " " + detail);
			}
			else
			{
				LogLimited("HoMM3 Fortress Bog Hex cooldown penalty skipped: " + failReason);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 spell-cooldown runtime failed closed during AddCooldownIfReady prefix: " + ex.Message);
		}
	}

	private static void PostfixAddCooldownIfReady(object __instance, MethodBase __originalMethod, object[] __args)
	{
		try
		{
			if (__args == null || __args.Length != 1 || __args[0] is not int requestedCooldown)
			{
				LogLimited("HoMM3 spell-cooldown runtime failed closed: AddCooldownIfReady argument shape changed.");
				return;
			}

			var applied = false;
			if (TryArmTowerSpellcastDamageCsvLaw(__instance, requestedCooldown, out var towerCastDetail, out var towerCastFailReason))
			{
				applied = true;
				LogLimited("HoMM3 Tower spellcast battle-local damage runtime armed: method=" + FormatMethod(__originalMethod) + " " + towerCastDetail);
			}
			else
			{
				LogLimited("HoMM3 Tower spellcast battle-local damage runtime skipped: " + towerCastFailReason);
			}

			if (TryApplyTowerTierOneNoCooldown(__instance, requestedCooldown, out var tierOneDetail, out var tierOneFailReason))
			{
				applied = true;
				LogLimited("HoMM3 Tower tier-1 no-cooldown runtime applied: method=" + FormatMethod(__originalMethod) + " " + tierOneDetail);
			}
			else
			{
				LogLimited("HoMM3 Tower tier-1 no-cooldown runtime skipped: " + tierOneFailReason);
			}

			if (TryApplyPostCooldownProfileCredit(__instance, requestedCooldown, out var profileDetail, out var profileFailReason))
			{
				applied = true;
				LogLimited("HoMM3 spell-cooldown profile credit applied: method=" + FormatMethod(__originalMethod) + " " + profileDetail);
			}
			else
			{
				LogLimited("HoMM3 spell-cooldown profile credit skipped: " + profileFailReason);
			}

			if (!applied)
				return;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 spell-cooldown runtime failed closed during AddCooldownIfReady postfix: " + ex.Message);
		}
	}

	private static bool TryApplyFortressBogHexCooldownPenalty(
		object battleSpell,
		int requestedCooldown,
		out int adjustedCooldown,
		out string detail,
		out string failReason)
	{
		adjustedCooldown = requestedCooldown;
		detail = null;
		if (requestedCooldown <= 0)
		{
			failReason = "native requested cooldown is not positive";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveDataSideFromBattleObject(battleSpell, out var casterDataSide, out failReason))
			return false;
		if (!Homm3CustomFactionLawRuntime.TryResolveAllowedActiveKnownCustomLawForRegisteredFactionExcludingDataSide(
			    Homm3CustomLawEffectProfiles.Fortress,
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    casterDataSide,
			    out var fortressLaw,
			    out _,
			    out failReason))
		{
			return false;
		}
		if (fortressLaw.Rank <= 0)
		{
			failReason = "Fortress Bog Hex law rank is not positive";
			return false;
		}
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var spellInfo, out failReason))
			return false;

		adjustedCooldown = requestedCooldown + 1;
		detail = "law=" + fortressLaw
		         + " spell={" + spellInfo + "}"
		         + " requestedCooldown=" + requestedCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " adjustedCooldown=" + adjustedCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture);
		failReason = null;
		return true;
	}
	private static bool TryApplyPostCooldownProfileCredit(object battleSpell, int requestedCooldown, out string detail, out string failReason)
	{
		detail = null;
		if (requestedCooldown <= 0)
		{
			failReason = "native requested cooldown is not positive";
			return false;
		}
		if (!TryPlanAllowedSpellCooldownEffect(battleSpell, out var profile, out var context, out var plan, out failReason))
			return false;
		if (profile.CooldownDelta >= 0)
		{
			failReason = "profile has no cooldown credit delta: " + profile.EffectKey;
			return false;
		}
		if (!TryRequirePostCooldownProfileSpellMatch(battleSpell, profile, out var matchDetail, out failReason))
			return false;
		if (!Homm3SpellCooldownNativeAdapter.TryReadEffectiveCooldown(battleSpell, out var currentCooldown, out failReason))
			return false;
		if (currentCooldown <= 0)
		{
			failReason = "native cooldown remained zero after AddCooldownIfReady";
			return false;
		}
		var credit = Math.Max(1, context.Law.Rank);
		if (!Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(battleSpell, credit, out failReason))
			return false;
		detail = "law=" + context.Law
		         + " effect=" + profile.EffectKey
		         + " match=" + matchDetail
		         + " requestedCooldown=" + requestedCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " cooldownBeforeCredit=" + currentCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " credit=" + credit.ToString(System.Globalization.CultureInfo.InvariantCulture);
		failReason = null;
		return true;
	}

	private static bool TryRequirePostCooldownProfileSpellMatch(object battleSpell, Homm3CustomLawEffectProfiles.SpellCooldownProfile profile, out string detail, out string failReason)
	{
		detail = null;
		if (string.Equals(profile.EffectKey, "tower.overclock-cooldown-and-cast-gate", StringComparison.Ordinal))
		{
			if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var spellInfo, out failReason))
				return false;
			detail = "tower-any-spell {" + spellInfo + "}";
			failReason = null;
			return true;
		}
		if (string.Equals(profile.EffectKey, "cove.movement-storm-sea-cooldown", StringComparison.Ordinal))
			return TryRequireSpellTaxonomyTagsForDetail(battleSpell, new[] { "movement", "storm", "sea" }, out detail, out failReason);
		if (string.Equals(profile.EffectKey, "dungeon.night-curse-kill-cooldown", StringComparison.Ordinal))
			return TryRequireSpellTaxonomyTagsForDetail(battleSpell, new[] { "night", "curse" }, out detail, out failReason);
		if (string.Equals(profile.EffectKey, "conflux.elemental-family-cooldown", StringComparison.Ordinal))
			return TryRequireSpellTaxonomyTagsForDetail(battleSpell, new[] { "fire", "storm" }, out detail, out failReason);
		if (string.Equals(profile.EffectKey, "inferno.fire-gating-sacrifice-cooldown", StringComparison.Ordinal))
			return TryRequireSpellTaxonomyTagsForDetail(battleSpell, new[] { "fire", "summon" }, out detail, out failReason);
		failReason = "spell-cooldown profile has no post-cooldown credit implementation: " + profile.EffectKey;
		return false;
	}

	private static bool TryRequireSpellTaxonomyTagsForDetail(object battleSpell, string[] tags, out string detail, out string failReason)
	{
		detail = null;
		if (!TryRequireSpellTaxonomyTags(battleSpell, tags, out var taxonomy, out failReason))
			return false;
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var spellInfo, out failReason))
			return false;
		detail = "taxonomy school=" + (taxonomy.School ?? "unknown") + " tags=" + string.Join(",", taxonomy.Tags ?? Array.Empty<string>()) + " spell={" + spellInfo + "}";
		failReason = null;
		return true;
	}
	private static bool TryArmTowerSpellcastDamageCsvLaw(object battleSpell, int requestedCooldown, out string detail, out string failReason)
	{
		detail = null;
		if (requestedCooldown <= 0)
		{
			failReason = "native requested cooldown is not positive";
			return false;
		}
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(
			    battleSpell,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var lawOwner,
			    out failReason))
			return false;
		if (!Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(
			    lawOwner,
			    Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex,
			    out var context,
			    out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Tower, StringComparison.Ordinal))
		{
			failReason = "active law is not Tower spellcast law: " + context.Law;
			return false;
		}
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var spellInfo, out failReason))
			return false;
		var percentDelta = Math.Max(1, context.Law.Rank) * 5;
		if (!Homm3BattleLocalLawState.TryAddTowerSpellcastDamagePercent(
			    lawOwner,
			    percentDelta,
			    out var oldPercent,
			    out var newPercent,
			    out failReason))
			return false;
		detail = "law=" + context.Law
		         + " spell={" + spellInfo + "}"
		         + " requestedCooldown=" + requestedCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " percentDelta=" + percentDelta.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " oldPercent=" + oldPercent.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " newPercent=" + newPercent.ToString(System.Globalization.CultureInfo.InvariantCulture);
		failReason = null;
		return true;
	}
	private static bool TryApplyTowerTierOneNoCooldown(object battleSpell, int requestedCooldown, out string detail, out string failReason)
	{
		detail = null;
		if (requestedCooldown <= 0)
		{
			failReason = "native requested cooldown is not positive";
			return false;
		}
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var spellInfo, out failReason))
			return false;
		if (spellInfo.Rank != 0)
		{
			failReason = "spell is not tier 1: " + spellInfo;
			return false;
		}
		if (!TryEnterTowerPreparedNoCooldownHandler(battleSpell, out var handlerKey, out var lawSummary, out failReason))
			return false;
		if (!Homm3SpellCooldownNativeAdapter.TryReadEffectiveCooldown(battleSpell, out var currentCooldown, out failReason))
			return false;
		if (currentCooldown <= 0)
		{
			failReason = "native cooldown remained zero after AddCooldownIfReady";
			return false;
		}
		if (!Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(battleSpell, currentCooldown, out failReason))
			return false;
		detail = "handler=" + handlerKey
		         + " law=" + lawSummary
		         + " spell={" + spellInfo + "}"
		         + " requestedCooldown=" + requestedCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture)
		         + " removedCooldown=" + currentCooldown.ToString(System.Globalization.CultureInfo.InvariantCulture);
		failReason = null;
		return true;
	}

	private static bool TryEnterTowerPreparedNoCooldownHandler(object lawOwner, out string handlerKey, out string lawSummary, out string failReason)
	{
		handlerKey = null;
		lawSummary = null;
		if (TryEnterTowerHandler(lawOwner, "spell.low", Homm3CustomFactionLawRuntime.SpellSchoolAccessLowIndex, out lawSummary, out failReason))
		{
			handlerKey = "spell.low";
			return true;
		}
		var lowFailure = failReason;
		if (TryEnterTowerHandler(lawOwner, "spell.high", Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex, out lawSummary, out failReason))
		{
			handlerKey = "spell.high";
			return true;
		}
		var highFailure = failReason;
		failReason = "no active Tower Prepared Artifice no-cooldown law handler; low=" + lowFailure + "; high=" + highFailure;
		return false;
	}

	private static bool TryEnterTowerHandler(object lawOwner, string handlerKey, int lawIndex, out string lawSummary, out string failReason)
	{
		lawSummary = null;
		if (!Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(lawOwner, lawIndex, out var context, out failReason))
			return false;
		if (!string.Equals(context.Law.FactionSid, Homm3CustomLawEffectProfiles.Tower, StringComparison.Ordinal))
		{
			failReason = "active law is not Tower for " + handlerKey + ": " + context.Law;
			return false;
		}
		lawSummary = context.Law.ToString();
		failReason = null;
		return true;
	}
internal static bool TryGetAllowedSpellCooldownProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellCooldownProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetSpellCooldownProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryGetCandidateSpellCooldownProfile(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellCooldownProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out string failReason)
	{
		profile = default;
		context = default;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out context,
			    out failReason))
		{
			return false;
		}

		return Homm3CustomLawEffectProfiles.TryGetSpellCooldownProfile(
			context.Law.FactionSid,
			context.Law.Rank,
			out profile,
			out failReason);
	}

	internal static bool TryPlanCandidateSpellCooldownEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellCooldownProfile profile,
		out Homm3CustomLawRuntimeGuard.CandidateLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetCandidateSpellCooldownProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanSpellCooldownEffect(profile, out plan, out failReason);
	}

	internal static bool TryPlanAllowedSpellCooldownEffect(
		object lawOwner,
		out Homm3CustomLawEffectProfiles.SpellCooldownProfile profile,
		out Homm3CustomLawRuntimeGuard.AllowedLawContext context,
		out Homm3CustomLawEffectPlans.ProfileEffectPlan plan,
		out string failReason)
	{
		plan = default;
		if (!TryGetAllowedSpellCooldownProfile(lawOwner, out profile, out context, out failReason))
			return false;
		return Homm3CustomLawEffectPlans.TryPlanSpellCooldownEffect(profile, out plan, out failReason);
	}

	internal static bool TryApplyRankedCooldownCredit(object lawOwner, object battleSpell, out string failReason)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out var context,
			    out failReason))
			return false;

		var amount = Math.Max(1, context.Law.Rank);
		return Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(battleSpell, amount, out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSchool(
		object lawOwner,
		object battleSpell,
		string requiredSchoolName,
		out string failReason)
	{
		if (!Homm3SpellIdentityNativeAdapter.TryRequireSchool(battleSpell, requiredSchoolName, out _, out failReason))
			return false;
		return TryApplyRankedCooldownCredit(lawOwner, battleSpell, out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSpellSid(
		object lawOwner,
		object battleSpell,
		string requiredSpellSid,
		out string failReason)
	{
		if (!Homm3SpellIdentityNativeAdapter.TryRequireSpellSid(battleSpell, requiredSpellSid, out _, out failReason))
			return false;
		return TryApplyRankedCooldownCredit(lawOwner, battleSpell, out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSpellTaxonomyTags(
		object lawOwner,
		object battleSpell,
		string[] requiredTags,
		out string failReason)
	{
		if (!TryRequireSpellTaxonomyTags(battleSpell, requiredTags, out _, out failReason))
			return false;
		return TryApplyRankedCooldownCredit(lawOwner, battleSpell, out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSchoolInPool(
		object lawOwner,
		object battleSpellPool,
		string requiredSchoolName,
		out int affectedSpells,
		out string failReason)
	{
		return TryApplyRankedCooldownCreditInPool(
			lawOwner,
			battleSpellPool,
			requiredSchoolName,
			null,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSpellSidInPool(
		object lawOwner,
		object battleSpellPool,
		string requiredSpellSid,
		out int affectedSpells,
		out string failReason)
	{
		return TryApplyRankedCooldownCreditInPool(
			lawOwner,
			battleSpellPool,
			null,
			requiredSpellSid,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSpellTaxonomyTagsInPool(
		object lawOwner,
		object battleSpellPool,
		string[] requiredTags,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!TryEnterCooldownHandler(lawOwner, out var rank, out failReason))
			return false;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolSpells(battleSpellPool, out var battleSpells, out failReason))
			return false;
		if (!TryValidateTaxonomyTags(requiredTags, out failReason))
			return false;

		for (var i = 0; i < battleSpells.Length; i++)
		{
			var spell = battleSpells[i];
			if (!TrySpellMatchesTaxonomyTags(spell, requiredTags, out var matches, out failReason))
				return false;
			if (!matches)
				continue;
			if (!Homm3SpellCooldownNativeAdapter.TryReadEffectiveCooldown(spell, out var currentCooldown, out failReason))
				return false;
			if (currentCooldown <= 0)
				continue;
			if (!Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(spell, rank, out failReason))
				return false;
			affectedSpells++;
		}

		if (affectedSpells > 0)
			return true;
		failReason = "no spell in pool matched the required cooldown taxonomy credit filter";
		return false;
	}

	internal static bool TryApplyRankedCooldownCreditForSchoolInPoolFromCaster(
		object battleSpellPool,
		string requiredSchoolName,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolCooldownLawOwner(battleSpellPool, out var lawOwner, out failReason))
			return false;
		return TryApplyRankedCooldownCreditForSchoolInPool(
			lawOwner,
			battleSpellPool,
			requiredSchoolName,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownCreditForSpellSidInPoolFromCaster(
		object battleSpellPool,
		string requiredSpellSid,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolCooldownLawOwner(battleSpellPool, out var lawOwner, out failReason))
			return false;
		return TryApplyRankedCooldownCreditForSpellSidInPool(
			lawOwner,
			battleSpellPool,
			requiredSpellSid,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpell(object lawOwner, object battleSpell, out string failReason)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out var context,
			    out failReason))
			return false;

		var cooldown = Math.Max(1, context.Law.Rank);
		return Homm3SpellCooldownNativeAdapter.TryAddCooldownIfReady(battleSpell, cooldown, out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellForSchool(
		object lawOwner,
		object battleSpell,
		string requiredSchoolName,
		out string failReason)
	{
		if (!Homm3SpellIdentityNativeAdapter.TryRequireSchool(battleSpell, requiredSchoolName, out _, out failReason))
			return false;
		return TryApplyRankedCooldownToReadySpell(lawOwner, battleSpell, out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellForSpellSid(
		object lawOwner,
		object battleSpell,
		string requiredSpellSid,
		out string failReason)
	{
		if (!Homm3SpellIdentityNativeAdapter.TryRequireSpellSid(battleSpell, requiredSpellSid, out _, out failReason))
			return false;
		return TryApplyRankedCooldownToReadySpell(lawOwner, battleSpell, out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellForSpellTaxonomyTags(
		object lawOwner,
		object battleSpell,
		string[] requiredTags,
		out string failReason)
	{
		if (!TryRequireSpellTaxonomyTags(battleSpell, requiredTags, out _, out failReason))
			return false;
		return TryApplyRankedCooldownToReadySpell(lawOwner, battleSpell, out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellsForSchoolInPool(
		object lawOwner,
		object battleSpellPool,
		string requiredSchoolName,
		out int affectedSpells,
		out string failReason)
	{
		return TryApplyRankedCooldownToReadySpellsInPool(
			lawOwner,
			battleSpellPool,
			requiredSchoolName,
			null,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellsForSpellSidInPool(
		object lawOwner,
		object battleSpellPool,
		string requiredSpellSid,
		out int affectedSpells,
		out string failReason)
	{
		return TryApplyRankedCooldownToReadySpellsInPool(
			lawOwner,
			battleSpellPool,
			null,
			requiredSpellSid,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellsForSpellTaxonomyTagsInPool(
		object lawOwner,
		object battleSpellPool,
		string[] requiredTags,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!TryEnterCooldownHandler(lawOwner, out var rank, out failReason))
			return false;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolSpells(battleSpellPool, out var battleSpells, out failReason))
			return false;
		if (!TryValidateTaxonomyTags(requiredTags, out failReason))
			return false;

		for (var i = 0; i < battleSpells.Length; i++)
		{
			var spell = battleSpells[i];
			if (!TrySpellMatchesTaxonomyTags(spell, requiredTags, out var matches, out failReason))
				return false;
			if (!matches)
				continue;
			if (!Homm3SpellCooldownNativeAdapter.TryAddCooldownIfReady(spell, rank, out failReason))
				return false;
			affectedSpells++;
		}

		if (affectedSpells > 0)
			return true;
		failReason = "no spell in pool matched the required ready-cooldown taxonomy filter";
		return false;
	}

	internal static bool TryApplyRankedCooldownToReadySpellsForSchoolInPoolFromCaster(
		object battleSpellPool,
		string requiredSchoolName,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolCooldownLawOwner(battleSpellPool, out var lawOwner, out failReason))
			return false;
		return TryApplyRankedCooldownToReadySpellsForSchoolInPool(
			lawOwner,
			battleSpellPool,
			requiredSchoolName,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryApplyRankedCooldownToReadySpellsForSpellSidInPoolFromCaster(
		object battleSpellPool,
		string requiredSpellSid,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolCooldownLawOwner(battleSpellPool, out var lawOwner, out failReason))
			return false;
		return TryApplyRankedCooldownToReadySpellsForSpellSidInPool(
			lawOwner,
			battleSpellPool,
			requiredSpellSid,
			out affectedSpells,
			out failReason);
	}

	internal static bool TryRequireSpellTaxonomyTags(
		object battleSpell,
		string[] requiredTags,
		out Homm3SpellTaxonomyRegistry.Entry taxonomy,
		out string failReason)
	{
		taxonomy = default;
		if (requiredTags == null || requiredTags.Length == 0)
		{
			failReason = "required spell taxonomy tags are empty";
			return false;
		}
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var info, out failReason))
			return false;
		var spellSid = !string.IsNullOrWhiteSpace(info.MagicConfigSid) ? info.MagicConfigSid : info.Sid;
		if (string.IsNullOrWhiteSpace(spellSid))
		{
			failReason = "spell taxonomy cannot resolve a spell SID";
			return false;
		}
		if (!Homm3SpellTaxonomyRegistry.TryGet(spellSid, out taxonomy))
		{
			failReason = "spell taxonomy has no entry for " + spellSid;
			return false;
		}
		for (var i = 0; i < requiredTags.Length; i++)
		{
			var tag = requiredTags[i];
			if (string.IsNullOrWhiteSpace(tag))
			{
				failReason = "required spell taxonomy tag is empty";
				return false;
			}
			if (Homm3SpellTaxonomyRegistry.HasTag(spellSid, tag))
			{
				failReason = null;
				return true;
			}
		}
		failReason = "spell " + spellSid + " has no required taxonomy tag";
		return false;
	}

	private static bool TryApplyRankedCooldownCreditInPool(
		object lawOwner,
		object battleSpellPool,
		string requiredSchoolName,
		string requiredSpellSid,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!TryEnterCooldownHandler(lawOwner, out var rank, out failReason))
			return false;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolSpells(battleSpellPool, out var battleSpells, out failReason))
			return false;
		if (!TryValidatePoolFilter(requiredSchoolName, requiredSpellSid, out failReason))
			return false;

		for (var i = 0; i < battleSpells.Length; i++)
		{
			var spell = battleSpells[i];
			if (!TrySpellMatchesFilter(spell, requiredSchoolName, requiredSpellSid, out var matches, out failReason))
				return false;
			if (!matches)
				continue;
			if (!Homm3SpellCooldownNativeAdapter.TryReadEffectiveCooldown(spell, out var currentCooldown, out failReason))
				return false;
			if (currentCooldown <= 0)
				continue;
			if (!Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(spell, rank, out failReason))
				return false;
			affectedSpells++;
		}

		if (affectedSpells > 0)
			return true;
		failReason = "no spell in pool matched the required cooldown credit filter";
		return false;
	}

	private static bool TryApplyRankedCooldownToReadySpellsInPool(
		object lawOwner,
		object battleSpellPool,
		string requiredSchoolName,
		string requiredSpellSid,
		out int affectedSpells,
		out string failReason)
	{
		affectedSpells = 0;
		if (!TryEnterCooldownHandler(lawOwner, out var rank, out failReason))
			return false;
		if (!Homm3SpellCooldownNativeAdapter.TryReadSpellPoolSpells(battleSpellPool, out var battleSpells, out failReason))
			return false;
		if (!TryValidatePoolFilter(requiredSchoolName, requiredSpellSid, out failReason))
			return false;

		for (var i = 0; i < battleSpells.Length; i++)
		{
			var spell = battleSpells[i];
			if (!TrySpellMatchesFilter(spell, requiredSchoolName, requiredSpellSid, out var matches, out failReason))
				return false;
			if (!matches)
				continue;
			if (!Homm3SpellCooldownNativeAdapter.TryAddCooldownIfReady(spell, rank, out failReason))
				return false;
			affectedSpells++;
		}

		if (affectedSpells > 0)
			return true;
		failReason = "no spell in pool matched the required ready-cooldown filter";
		return false;
	}

	private static bool TryEnterCooldownHandler(object lawOwner, out int rank, out string failReason)
	{
		rank = 0;
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out var context,
			    out failReason))
			return false;
		rank = Math.Max(1, context.Law.Rank);
		return true;
	}

	private static bool TryValidatePoolFilter(string requiredSchoolName, string requiredSpellSid, out string failReason)
	{
		var hasSchool = !string.IsNullOrWhiteSpace(requiredSchoolName);
		var hasSid = !string.IsNullOrWhiteSpace(requiredSpellSid);
		if (hasSchool == hasSid)
		{
			failReason = "spell pool cooldown filter must specify exactly one school or spell SID";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TrySpellMatchesFilter(
		object battleSpell,
		string requiredSchoolName,
		string requiredSpellSid,
		out bool matches,
		out string failReason)
	{
		matches = false;
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var info, out failReason))
			return false;
		if (!string.IsNullOrWhiteSpace(requiredSchoolName))
		{
			matches = string.Equals(info.SchoolName, requiredSchoolName, StringComparison.OrdinalIgnoreCase);
			failReason = null;
			return true;
		}
		if (!string.IsNullOrWhiteSpace(requiredSpellSid))
		{
			matches = string.Equals(info.Sid, requiredSpellSid, StringComparison.Ordinal)
			          || string.Equals(info.MagicConfigSid, requiredSpellSid, StringComparison.Ordinal);
			failReason = null;
			return true;
		}
		failReason = "spell pool cooldown filter is empty";
		return false;
	}

	private static bool TryValidateTaxonomyTags(string[] requiredTags, out string failReason)
	{
		if (requiredTags == null || requiredTags.Length == 0)
		{
			failReason = "spell taxonomy filter must specify at least one tag";
			return false;
		}
		for (var i = 0; i < requiredTags.Length; i++)
		{
			if (string.IsNullOrWhiteSpace(requiredTags[i]))
			{
				failReason = "spell taxonomy filter contains an empty tag";
				return false;
			}
		}
		failReason = null;
		return true;
	}

	private static bool TrySpellMatchesTaxonomyTags(
		object battleSpell,
		string[] requiredTags,
		out bool matches,
		out string failReason)
	{
		matches = false;
		if (!TryValidateTaxonomyTags(requiredTags, out failReason))
			return false;
		if (!Homm3SpellIdentityNativeAdapter.TryReadSpellIdentity(battleSpell, out var info, out failReason))
			return false;
		var spellSid = !string.IsNullOrWhiteSpace(info.MagicConfigSid) ? info.MagicConfigSid : info.Sid;
		if (string.IsNullOrWhiteSpace(spellSid))
		{
			failReason = "spell taxonomy cannot resolve a spell SID";
			return false;
		}
		if (!Homm3SpellTaxonomyRegistry.TryGet(spellSid, out _))
		{
			failReason = "spell taxonomy has no entry for " + spellSid;
			return false;
		}
		matches = Homm3SpellTaxonomyRegistry.HasAnyTag(spellSid, requiredTags);
		failReason = null;
		return true;
	}

	private static MethodInfo ResolveExactMethod(Type type, string[] names, Type requiredReturnType, string[] parameterTypeNames)
	{
		if (type == null)
			return null;
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName)
					continue;
				if (requiredReturnType != null && method.ReturnType != requiredReturnType)
					continue;
				if (!ParametersMatch(method, parameterTypeNames))
					continue;
				return method;
			}
		}
		return null;
	}

	private static bool ParametersMatch(MethodInfo method, string[] parameterTypeNames)
	{
		var parameters = method.GetParameters();
		parameterTypeNames ??= Array.Empty<string>();
		if (parameters.Length != parameterTypeNames.Length)
			return false;
		for (var i = 0; i < parameters.Length; i++)
		{
			var expected = parameterTypeNames[i];
			if (string.IsNullOrWhiteSpace(expected))
				continue;
			var actual = parameters[i].ParameterType;
			var actualName = actual.Name;
			var actualFullName = actual.FullName ?? actualName;
			var actualObfuscatedName = GameMember.ReadObfuscatedName(actual);
			if (!string.Equals(actualName, expected, StringComparison.Ordinal)
			    && !string.Equals(actualFullName, expected, StringComparison.Ordinal)
			    && !actualFullName.EndsWith("." + expected, StringComparison.Ordinal)
			    && !string.Equals(actualObfuscatedName, expected, StringComparison.Ordinal))
				return false;
		}
		return true;
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged >= LogCap)
			return;
		_logged++;
		Plugin.LogSource?.LogInfo(message);
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}}





