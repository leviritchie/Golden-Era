using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.UI.City;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using BuildingData = Hex.Session.Data.BuildingData;

namespace OfflineUnlockMod;

/// <summary>
/// Shared custom UI icon key support for native and direct-bound UI surfaces.
/// Keep this hook limited to known custom key prefixes; vanilla sprite resolution must remain untouched.
/// </summary>
internal static class Homm3CustomUiIconHook
{
	private static bool _patched;
	private static int _loggedResolverPatch;
	private static int _loggedResolverReplace;
	private static int _loggedSurfacePatch;
	private static int _loggedSurfaceReplace;
	private static int _loggedSurfaceDiag;
	private static int _loggedHireOverlay;
	private static int _loggedHireDonorAlias;
	private static int _loggedHireNativeVisualHidden;
	private static int _loggedBattleAbilityReplace;
	private static int _loggedBattleAbilityIconDiag;
	private static int _loggedBattleAbilityFocusMarkers;
	private static int _loggedLoadedSpriteFallback;
	private static int _loggedCityHudDiag;
	private static int _loggedBuildingTooltipReplace;
	private static int _loggedBuildingViewReplace;
	private static int _loggedBuildingIconProbe;
	private static int _loggedBuildingViewSuccessHierarchy;
	private static int _loggedBuildingHireResolveDiag;
	private static int _loggedBattleResultIconProbe;
	private static int _loggedRecruitmentPanelReplace;
	private static int _loggedHireUnitModelListSuppressed;
	private static int _loggedHireAbilityRebind;
	private static int _loggedHireAbilityContext;
	private static int _loggedHeroStatRewardReplace;
	private static int _loggedSpellbookMagicIconReplace;
	private static int _loggedSpellbookMagicIconMiss;
	private static int _loggedRecruitmentItemDiag;
	private static int _loggedRecruitmentRuntimeTypeResolveFailure;
	private static int _loggedRecruitmentWrapperNormalizeFailure;
	private static int _loggedRecruitmentWrapperCloneFailure;
	private static int _loggedRecruitmentOwnerSidMiss;
	private static readonly Dictionary<long, string> RecruitmentSidByItem = new();
	private static readonly Dictionary<long, string> BuildingIconKeyByView = new();
	private static readonly Dictionary<long, List<string>> TooltipUnitSidsByView = new();
	private static readonly Dictionary<long, string> BattleAbilityIconKeyByView = new();
	private static readonly Dictionary<string, Sprite> LoadedSpriteByKey = new(StringComparer.Ordinal);
	private static readonly HashSet<int> AdjustedCityHudImages = new();
	private const string HirePortraitOverlayName = "HOMM3_HIRE_UNIT_PORTRAIT";
	private const string BattleAbilityIconOverlayName = "HOMM3_BATTLE_ABILITY_ICON";

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		var patched = 0;
		patched += TryPatchKnownStringResolvers(h, log);
		patched += TryPatchKnownUiSurfaces(h, log);

		if (patched == 0)
			log?.LogWarning("Homm3CustomUiIcon: no resolver/UI surface patches registered.");
		else
			log?.LogInfo("Homm3CustomUiIcon: " + patched + " custom icon fallback patch(es) registered.");

		_patched = true;
	}

	internal static void TryRegisterReleaseSafeUiSlice(Harmony h, ManualLogSource log)
	{
		RegisterReleaseSafeUiSlice(h, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeUiSlice(Harmony h, ManualLogSource log)
	{
		RegisterReleaseSafeUiSlice(h, log, required: true);
	}

	private static void RegisterReleaseSafeUiSlice(Harmony h, ManualLogSource log, bool required)
	{
		if (_patched)
			return;
		if (h == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required Homm3CustomUiIcon release-safe UI registration.");
			return;
		}

		var patched = 0;
		var missing = new List<string>();

		patched += Required("cko.sfo sprite resolver", () => PatchNativeSpriteResolverSfo(h, log));

		int Required(string label, Func<int> patch)
		{
			var count = patch();
			if (required && count == 0)
				missing.Add(label);
			return count;
		}

		int RequiredAnyBySymbol(string label, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName)
		{
			var count = PatchAnyBySymbol(h, log, typeName, symbol, parameterTypes, postfixName, false);
			if (required && count == 0)
				missing.Add(label);
			return count;
		}
int RequiredExactAnyBySymbolWithPrefix(string label, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string prefixName, string postfixName)
		{
			var count = PatchExactAnyBySymbolWithPrefix(h, log, typeName, symbol, parameterTypes, prefixName, postfixName, false);
			if (required && count == 0)
				missing.Add(label);
			return count;
		}

		patched += Required("Hex.Session.Hud.BhCityUIElement.Init", () => PatchByName(h, log, "Hex.Session.Hud.BhCityUIElement", "Init", null, nameof(PostfixCityUiElementInit)));
		patched += RequiredAnyBySymbol("Hex.Session.Hud.BhCityUIElement indexed refresh", "Hex.Session.Hud.BhCityUIElement", GameSymbols.ReleaseTownUi.CityUiElementRefreshIndexed, new[] { typeof(int) }, nameof(PostfixCityUiElementRefresh));
		patched += RequiredAnyBySymbol("Hex.Session.Hud.BhCityUIElement refresh", "Hex.Session.Hud.BhCityUIElement", GameSymbols.ReleaseTownUi.CityUiElementRefresh, Array.Empty<Type>(), nameof(PostfixCityUiElementRefresh));

		patched += Required("Hex.UI.City.BhBuildingView bind", () => PatchBuildingViewBindByShape(h, log));
		patched += Required("Hex.UI.City.BhBuildingView secondary bind", () => PatchBuildingViewSecondaryBindByShape(h, log));
		patched += Required("Hex.UI.City.BhBuildingView hover refresh", () => PatchBuildingViewHoverRefreshByShape(h, log));
		patched += Required("Hex.UI.City.BhBuildingView.UpdateView", () => PatchByName(h, log, "Hex.UI.City.BhBuildingView", "UpdateView", null, nameof(PostfixBuildingViewBind)));
		patched += Required("Hex.UI.BhTooltipBuilding", () => PatchBuildingTooltipByShape(h, log));
		patched += Required("Hex.UI.Tooltips.BhTooltipUnitsView bind", () => PatchTooltipUnitsViewBindByShape(h, log));
		patched += Required("Hex.UI.City.BhHireUnitItemView.UpdateView(string)", () => PatchByNameWithPrefix(h, log, "Hex.UI.City.BhHireUnitItemView", "UpdateView", typeof(string), nameof(PrefixStringArg0DonorSurface), nameof(PostfixStringArg0DonorSurface)));
		patched += Required("Hex.UI.City.BhHireUnitItemView.Init", () => PatchByNameWithPrefix(h, log, "Hex.UI.City.BhHireUnitItemView", "Init", null, nameof(PrefixHireUnitItemInit), nameof(PostfixHireUnitItemInit)));
		patched += Required("Hex.UI.City.BhHireUnitItemView refresh", () => PatchHireUnitItemRefreshByShape(h, log));
		patched += Required("Hex.UI.City.BhCitySpecialView.Init", () => PatchByName(h, log, "Hex.UI.City.BhCitySpecialView", "Init", null, nameof(PostfixCitySpecialRecruitmentPanel)));
		patched += RequiredAnyBySymbol("Hex.UI.City.BhCitySpecialView refresh", "Hex.UI.City.BhCitySpecialView", GameSymbols.ReleaseTownUi.CitySpecialRefresh, Array.Empty<Type>(), nameof(PostfixCitySpecialRecruitmentPanel));
		patched += Required("Hex.UI.City.BhCityUnitSpecialSelection.Show", () => PatchByName(h, log, "Hex.UI.City.BhCityUnitSpecialSelection", "Show", null, nameof(PostfixCityUnitSpecialSelectionShow)));
		patched += Required("Hex.UI.City.BhCityHireIncrementItemView bind", () => PatchHireIncrementItemByShape(h, log, withSpritePrefix: false));
		patched += Required("Hex.UI.City.BhCityHireIncrementItemView sprite", () => PatchHireIncrementItemByShape(h, log, withSpritePrefix: true));
		patched += Required("Hex.UI.City.BhHireUnitItemView model list", () => PatchHireUnitItemModelByShape(h, log, listMode: true));
		patched += Required("Hex.UI.City.BhHireUnitItemView model out", () => PatchHireUnitItemModelByShape(h, log, listMode: false));
		patched += Required("Hex.Session.City.BhHireUnitAbilityItemView.Init(string)", () => PatchByName(h, log, "Hex.Session.City.BhHireUnitAbilityItemView", "Init", typeof(string), nameof(PostfixStringArg0Surface)));
		patched += RequiredAnyBySymbol("Hex.Session.City.BhHireUnitAbilityItemView primary ability bind", "Hex.Session.City.BhHireUnitAbilityItemView", GameSymbols.UnitPreviewAbilityIcons.AbilityItemPrimaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: false), nameof(PostfixAbilityConfigArg1Surface));
		patched += RequiredAnyBySymbol("Hex.Session.City.BhHireUnitAbilityItemView secondary ability bind", "Hex.Session.City.BhHireUnitAbilityItemView", GameSymbols.UnitPreviewAbilityIcons.AbilityItemSecondaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: false), nameof(PostfixAbilityConfigArg1Surface));
		patched += RequiredAnyBySymbol("Hex.Session.City.BhHireUnitAbilityView primary ability bind", "Hex.Session.City.BhHireUnitAbilityView", GameSymbols.UnitPreviewAbilityIcons.AbilityViewPrimaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: true), nameof(PostfixAbilityConfigArg1Surface));
		patched += RequiredAnyBySymbol("Hex.Session.City.BhHireUnitAbilityView secondary ability bind", "Hex.Session.City.BhHireUnitAbilityView", GameSymbols.UnitPreviewAbilityIcons.AbilityViewSecondaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: false), nameof(PostfixAbilityConfigArg0Surface));
		patched += Required("Hex.BhHireUnitAbilities bind", () => PatchHireUnitAbilitiesBindByShape(h, log));
		patched += Required("Hex.Session.Battle.BhUnitAbilityView ability bind", () => PatchBattleAbilityViewBindByShape(h, log));
		patched += RequiredAnyBySymbol("Hex.UI.City.BhRewardNotificationHeroStat show", "Hex.UI.City.BhRewardNotificationHeroStat", GameSymbols.ReleaseTownUi.HeroStatRewardShow, Array.Empty<Type>(), nameof(PostfixHeroStatRewardNotification));
		patched += Required("Hex.UI.City.BhRewardNotificationHeroStat.Update", () => PatchByName(h, log, "Hex.UI.City.BhRewardNotificationHeroStat", "Update", null, nameof(PostfixHeroStatRewardNotification)));
		patched += Required("Hex.UI.City.BhRewardNotificationHeroStat.OnHide", () => PatchAnyByName(h, log, "Hex.UI.City.BhRewardNotificationHeroStat", GameSymbols.ReleaseTownUi.HeroStatRewardHide.NameHints, null, nameof(PostfixHeroStatRewardNotificationHidden)));
		patched += RequiredAnyBySymbol("Hex.UI.City.BhRewardNotificationHeroStat hide/apply", "Hex.UI.City.BhRewardNotificationHeroStat", GameSymbols.ReleaseTownUi.HeroStatRewardHideOrApply, Array.Empty<Type>(), nameof(PostfixHeroStatRewardNotificationHidden));
		patched += Required("Hex.Session.UI.HeroProfile.BhHeroSpecializationView bind", () => PatchHeroProfileIconViewByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroSpecializationView", nameof(PostfixHeroProfileSpecializationIcon)));
		patched += Required("Hex.Session.UI.HeroProfile.BhHeroSkillView bind", () => PatchHeroProfileIconViewByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroSkillView", nameof(PostfixHeroProfileSkillIcon)));
		patched += Required("Hex.Session.UI.HeroProfile.BhHeroSubSkillView bind", () => PatchHeroProfileIconViewByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroSubSkillView", nameof(PostfixHeroProfileSubSkillIcon)));
		patched += Required("Hex.Session.UI.BhLevelUpSkillView.Init", () => PatchByName(h, log, "Hex.Session.UI.BhLevelUpSkillView", "Init", null, nameof(PostfixLevelUpSkillIcon)));
		patched += Required("Hex.Session.UI.BhMagicItemView.Show", () => PatchMagicItemViewShowByShape(h, log));

		if (missing.Count > 0)
			throw new InvalidOperationException("required Homm3CustomUiIcon release-safe UI surface(s) missing: " + string.Join(", ", missing));

		if (patched == 0)
			log?.LogWarning("Homm3CustomUiIcon release-safe UI slice: no UI icon patches registered.");
		else if (required)
			log?.LogInfo("Homm3CustomUiIcon release-safe UI slice: " + patched + " required UI icon patch(es) registered.");
		else
			log?.LogInfo("Homm3CustomUiIcon release-safe UI slice: " + patched + " UI icon patch(es) registered.");

		_patched = true;
	}

	internal static bool TryResolveSprite(string key, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(key))
			return false;

		var sid = key.Trim();
		if (Homm3StrongholdCityIconSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3StrongholdBuildingIconSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3ArtifactIconSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3StrongholdLawIconSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite)
			return true;
		if (TryResolveFactionUiSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3DialogPortraitCatalog.TryResolveCustomDialogPortraitSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(sid, out sprite) && sprite)
			return true;
		if (TryResolveHeroSpecializationSprite(sid, out sprite) && sprite)
			return true;
		if (Homm3HeroSpecializationIconSpriteCache.IsKnownSpecializationIconKey(sid)
		    && Homm3HeroSpecializationIconSpriteCache.TryResolveSprite(sid, out sprite)
		    && sprite)
			return true;
		if (IsHomm3UnitSid(sid) && Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite)
			return true;
		if (IsDungeonSubclassIconKey(sid) && TryFindLoadedSprite(sid, out sprite) && sprite)
			return true;
		if (IsStrongholdAbilityDonorIconKey(sid) && TryFindLoadedSprite(sid, out sprite) && sprite)
			return true;
		var semanticAbilityIconKey = ResolveStrongholdAbilitySemanticIconKey(sid);
		if (!string.IsNullOrWhiteSpace(semanticAbilityIconKey)
		    && !string.Equals(semanticAbilityIconKey, sid, StringComparison.Ordinal)
		    && TryResolveSprite(semanticAbilityIconKey, out sprite)
		    && sprite)
		{
			return true;
		}
		return false;
	}

	internal static bool TryResolveLoadedVanillaSprite(string key, out Sprite sprite)
	{
		return TryFindLoadedSprite(key, out sprite) && sprite;
	}

	internal static bool PrewarmBattleAbilityIconForConfig(object abilityViewConfig, out string iconKey)
	{
		iconKey = ResolveStrongholdAbilityIconKey(abilityViewConfig);
		if (string.IsNullOrWhiteSpace(iconKey))
			return false;
		return TryResolveSprite(iconKey, out var sprite) && sprite;
	}

	private static bool IsCustomKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var sid = key.Trim();
		return Homm3CustomFactionRegistry.IsCustomUnitSid(sid)
			|| !string.IsNullOrWhiteSpace(ResolveStrongholdAbilitySemanticIconKey(sid))
			|| Homm3CustomFactionRegistry.IsCustomHeroSid(sid)
			|| Homm3DialogPortraitCatalog.IsCustomDialogPortraitKey(sid)
			|| Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(sid)
			|| Homm3StrongholdBuildingIconSpriteCache.IsStrongholdBuildingIconKey(sid)
			|| Homm3ArtifactIconSpriteCache.IsArtifactIconKey(sid)
			|| IsCustomFactionUiIconKey(sid)
			|| IsCustomHeroSpecializationIconKey(sid)
			|| IsDungeonSubclassIconKey(sid)
			|| IsStrongholdAbilityDonorIconKey(sid)
			|| Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(sid)
			|| Homm3StrongholdLawIconSpriteCache.IsStrongholdLawIconKey(sid)
			|| Homm3HeroSpecializationIconSpriteCache.IsKnownSpecializationIconKey(sid);
	}

	private static bool TryResolveHeroSpecializationSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		if (!IsCustomHeroSpecializationIconKey(sid))
			return false;
		var heroIconKey = sid.Trim().Substring(0, sid.Trim().Length - "_specialization_icon".Length);
		return Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(heroIconKey, out sprite) && sprite;
	}

	private static bool IsCustomHeroSpecializationIconKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		if (!key.EndsWith("_specialization_icon", StringComparison.Ordinal))
			return false;
		var heroIconKey = key.Substring(0, key.Length - "_specialization_icon".Length);
		return Homm3CustomFactionRegistry.IsCustomHeroSid(heroIconKey);
	}

	private static bool TryResolveFactionUiSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		if (Homm3CustomFactionRegistry.TryGetFactionSpriteAssetByKey(sid, out var factionSid, out var card))
			return card
				? Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateCardSpriteForFaction(factionSid, out sprite)
				: Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out sprite);
		if (Homm3CustomFactionRegistry.TryGetFactionSidForCustomUiIconKey(sid, out factionSid))
			return Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out sprite);
		if (TryResolveFactionSkillIconSprite(sid, out sprite))
			return true;
		return false;
	}

	private static bool IsCustomFactionUiIconKey(string sid)
	{
		return Homm3CustomFactionRegistry.TryGetFactionSpriteAssetByKey(sid, out _, out _)
			|| Homm3CustomFactionRegistry.TryGetFactionSidForCustomUiIconKey(sid, out _)
			|| IsRegisteredFactionSkillIconKey(sid);
	}

	private static bool TryResolveFactionSkillIconSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		if (!TryGetRegisteredFactionSkillIconFaction(sid, out _))
			return false;
		return Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(sid, out sprite) && sprite;
	}

	private static bool IsRegisteredFactionSkillIconKey(string sid)
	{
		return TryGetRegisteredFactionSkillIconFaction(sid, out _);
	}

	private static bool TryGetRegisteredFactionSkillIconFaction(string sid, out string factionSid)
	{
		return Homm3FactionSkillIconSpriteCache.TryGetFactionSkillIconFaction(sid, out factionSid);
	}

	private static bool IsHomm3UnitSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid) && sid.Trim().StartsWith("h3_", StringComparison.Ordinal);
	}

	private static bool IsDungeonSubclassIconKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		return string.Equals(key, "sub_class_dungeon_might_1_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_class_dungeon_might_2_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_class_dungeon_magic_1_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_class_dungeon_magic_2_icon", StringComparison.Ordinal);
	}

	private static bool IsStrongholdAbilityDonorIconKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		return string.Equals(key, "pet_blood_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_early_start_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_sharp_edge_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_fatal_decay_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_favorable_wind_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_healing_water_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_inner_light_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_nairas_kiss_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_shorten_shadow_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_unnatural_calm_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "magic_vulnerability_effect_icon", StringComparison.Ordinal)
			|| string.Equals(key, "minos_buff_icon", StringComparison.Ordinal)
			|| string.Equals(key, "skill_leadership", StringComparison.Ordinal)
			|| string.Equals(key, "skill_luck", StringComparison.Ordinal)
			|| string.Equals(key, "skill_tactics", StringComparison.Ordinal)
			|| string.Equals(key, "sub_skill_assault_1_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_skill_assault_2_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_skill_resistance_1_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_skill_siege_1_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_skill_siege_2_icon", StringComparison.Ordinal)
			|| string.Equals(key, "wasp_debuff_icon", StringComparison.Ordinal)
			|| string.Equals(key, "assassin_buff_icon", StringComparison.Ordinal)
			|| string.Equals(key, "primal_1_magic_thunderbolt", StringComparison.Ordinal)
			|| string.Equals(key, "space_6_magic_blink", StringComparison.Ordinal)
			|| string.Equals(key, "neutral_magic_second_sight", StringComparison.Ordinal)
			|| string.Equals(key, "bonus_magic_pure_bolt", StringComparison.Ordinal)
			|| string.Equals(key, "dragon_hunter_blood_icon", StringComparison.Ordinal)
			|| string.Equals(key, "crossbowman_buff_icon", StringComparison.Ordinal)
			|| string.Equals(key, "crossbowman_debuff_icon", StringComparison.Ordinal)
			|| string.Equals(key, "sub_skill_units_attackPen_icon", StringComparison.Ordinal);
	}

	private static bool TryFindLoadedSprite(string key, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var sid = key.Trim();
		if (LoadedSpriteByKey.TryGetValue(sid, out sprite) && sprite)
			return true;

		try
		{
			foreach (var prefix in new[]
			{
				"icons/hero_sub_classes/",
				"icons/hero_skills/",
				"icons/skills/",
				"icons/buffs/",
				"icons/hero_magics/",
				"icons/abilities/",
				"icons/artifacts/",
			})
			{
				sprite = Resources.Load<Sprite>(prefix + sid);
				if (sprite)
				{
					LoadedSpriteByKey[sid] = sprite;
					LogLoadedSpriteFallback(sid, sprite);
					return true;
				}
			}

			var sprites = Resources.FindObjectsOfTypeAll<Sprite>();
			Sprite best = null;
			for (var i = 0; i < sprites.Length; i++)
			{
				var s = sprites[i];
				if (!s || string.IsNullOrWhiteSpace(s.name))
					continue;
				if (string.Equals(s.name, sid, StringComparison.Ordinal))
				{
					best = s;
					break;
				}
				if (best == null && s.name.IndexOf(sid, StringComparison.Ordinal) >= 0)
					best = s;
			}
			if (!best)
				return false;
			LoadedSpriteByKey[sid] = best;
			sprite = best;
			LogLoadedSpriteFallback(sid, best);
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: loaded sprite scan failed for key='" + sid + "': " + ex.Message);
			return false;
		}
	}

	private static int TryPatchKnownStringResolvers(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			var name = asm.GetName().Name;
			if (!string.Equals(name, "Hex", StringComparison.Ordinal)
				&& !string.Equals(name, "Hex.Shared", StringComparison.Ordinal)
				&& !string.Equals(name, "Assembly-CSharp", StringComparison.Ordinal))
				continue;

			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types; }
			catch { continue; }

			foreach (var type in types)
			{
				if (type == null)
					continue;
				MethodInfo[] methods;
				try { methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static); }
				catch { continue; }

				foreach (var method in methods)
				{
					if (method == null || method.ContainsGenericParameters)
						continue;
					var returnType = method.ReturnType;
					if (returnType != typeof(Sprite) && returnType != typeof(Texture) && returnType != typeof(Texture2D))
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length < 1 || parameters[0].ParameterType != typeof(string))
						continue;
					if (IsUnsafeGlobalResolverTarget(method))
						continue;

					try
					{
						if (returnType == typeof(Sprite))
							h.Patch(method, prefix: new HarmonyMethod(typeof(Homm3CustomUiIconHook), nameof(PrefixSpriteResolver)));
						else if (returnType == typeof(Texture2D))
							h.Patch(method, prefix: new HarmonyMethod(typeof(Homm3CustomUiIconHook), nameof(PrefixTexture2DResolver)));
						else
							h.Patch(method, prefix: new HarmonyMethod(typeof(Homm3CustomUiIconHook), nameof(PrefixTextureResolver)));
						patched++;
						LogResolverPatch(log, method);
					}
					catch (Exception ex)
					{
						log?.LogDebug("Homm3CustomUiIcon: resolver patch failed on " + FormatMethod(method) + ": " + ex.Message);
					}
				}
			}
		}
		return patched;
	}

	private static bool IsUnsafeGlobalResolverTarget(MethodInfo method)
	{
		var typeName = method?.DeclaringType?.FullName ?? method?.DeclaringType?.Name ?? "";
		if (typeName.IndexOf("BhUnitPreviews", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		return false;
	}

	private static int PatchNativeSpriteResolverSfo(Harmony h, ManualLogSource log)
	{
		var type = FindRuntimeType(Homm3NativeSpriteCatalogRegistrar.ResolverTypeName);
		if (type == null)
		{
			log?.LogWarning("Homm3CustomUiIcon: native sprite resolver type not found: " + Homm3NativeSpriteCatalogRegistrar.ResolverTypeName + " (cko).");
			return 0;
		}

		var prefix = typeof(Homm3CustomUiIconHook).GetMethod(nameof(PrefixSpriteResolver), BindingFlags.Static | BindingFlags.NonPublic);
		var patched = 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method.ReturnType != typeof(Sprite))
				continue;
			var parameters = method.GetParameters();
			// cko.sfo(string) and cko.sfn(string, bool) both resolve dialog icon paths.
			var isSfo = method.Name == Homm3NativeSpriteCatalogRegistrar.ResolverMethodName
			            && parameters.Length == 1
			            && parameters[0].ParameterType == typeof(string);
			var isSfn = parameters.Length == 2
			            && parameters[0].ParameterType == typeof(string)
			            && parameters[1].ParameterType == typeof(bool)
			            && (method.Name.IndexOf("sfn", StringComparison.OrdinalIgnoreCase) >= 0
			                || method.Name.Contains("Sprite_String_Boolean", StringComparison.Ordinal));
			if (!isSfo && !isSfn)
				continue;
			if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var reason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible native sprite resolver prefix for " + FormatMethod(method) + ": " + reason);
				continue;
			}
			h.Patch(method, prefix: new HarmonyMethod(prefix));
			LogResolverPatch(log, method);
			patched++;
		}

		if (patched == 0)
		{
			log?.LogWarning("Homm3CustomUiIcon: native sprite resolver method not found: " + Homm3NativeSpriteCatalogRegistrar.ResolverTypeName + "." + Homm3NativeSpriteCatalogRegistrar.ResolverMethodName + "(string) / cko.sfo.");
		}
		return patched;
	}

	private static int TryPatchKnownUiSurfaces(Harmony h, ManualLogSource log)
	{
		var patched = 0;

		patched += PatchByName(h, log, "Hex.Session.City.BhHireUnitAbilityItemView", "Init", typeof(string), nameof(PostfixStringArg0Surface));
		patched += PatchAnyBySymbol(h, log, "Hex.Session.City.BhHireUnitAbilityItemView", GameSymbols.UnitPreviewAbilityIcons.AbilityItemPrimaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: false), nameof(PostfixAbilityConfigArg1Surface), false);
		patched += PatchAnyBySymbol(h, log, "Hex.Session.City.BhHireUnitAbilityItemView", GameSymbols.UnitPreviewAbilityIcons.AbilityItemSecondaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: false), nameof(PostfixAbilityConfigArg1Surface), false);
		patched += PatchAnyBySymbol(h, log, "Hex.Session.City.BhHireUnitAbilityView", GameSymbols.UnitPreviewAbilityIcons.AbilityViewPrimaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: true), nameof(PostfixAbilityConfigArg1Surface), false);
		patched += PatchAnyBySymbol(h, log, "Hex.Session.City.BhHireUnitAbilityView", GameSymbols.UnitPreviewAbilityIcons.AbilityViewSecondaryBind, ResolveAbilityViewConfigBindParameterTypes(swapOrder: false), nameof(PostfixAbilityConfigArg0Surface), false);
		patched += PatchAnyByNameWithPrefix(h, log, "Hex.BhHireUnitAbilities", GameSymbols.UnitPreviewAbilityIcons.HireUnitAbilitiesBind.NameHints, typeof(Unit), nameof(PrefixHireUnitAbilitiesBind), nameof(PostfixHireUnitAbilitiesBind), nameof(FinalizerHireUnitAbilitiesBind));

		patched += PatchByNameWithPrefix(h, log, "Hex.UI.City.BhHireUnitItemView", "UpdateView", typeof(string), nameof(PrefixStringArg0DonorSurface), nameof(PostfixStringArg0DonorSurface));
		foreach (var methodName in GameSymbols.ReleaseTownUi.HireUnitItemRefresh.NameHints)
			patched += PatchByName(h, log, "Hex.UI.City.BhHireUnitItemView", methodName, null, nameof(PostfixNoArgSurfaceDiag));

		patched += PatchByName(h, log, "Hex.Session.Hud.BhCityUIElement", "Init", null, nameof(PostfixCityUiElementInit));
		patched += PatchAnyByName(h, log, "Hex.Session.Hud.BhCityUIElement", GameSymbols.ReleaseTownUi.CityUiElementRefreshIndexed.NameHints, typeof(int), nameof(PostfixCityUiElementRefresh));
		patched += PatchAnyByName(h, log, "Hex.Session.Hud.BhCityUIElement", GameSymbols.ReleaseTownUi.CityUiElementRefresh.NameHints, null, nameof(PostfixCityUiElementRefresh));
		patched += PatchHeroProfileIconViewByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroSpecializationView", nameof(PostfixHeroProfileSpecializationIcon));
		patched += PatchHeroProfileIconViewByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroSkillView", nameof(PostfixHeroProfileSkillIcon));
		patched += PatchHeroProfileIconViewByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroSubSkillView", nameof(PostfixHeroProfileSubSkillIcon));
		patched += PatchByName(h, log, "Hex.Session.UI.BhLevelUpSkillView", "Init", null, nameof(PostfixLevelUpSkillIcon));
		patched += PatchMagicItemViewShowByShape(h, log);
		patched += PatchAnyByName(h, log, "Hex.UI.BhTooltipBuilding", GameSymbols.ReleaseTownUi.BuildingTooltipBind.NameHints, null, nameof(PostfixBuildingTooltipFromCity));
		patched += PatchAnyByNameWithPrefixByFirstParameterTypeName(h, log, "Hex.Session.Battle.BhUnitAbilityView", GameSymbols.SelectedUnitHud.AbilityViewBind.NameHints, GameSymbols.SelectedUnitHud.AbilityViewWrapperTypeNames, null, nameof(PostfixBattleAbilityViewBind));
		patched += TryPatchBattleResultIconProbes(h, log);

		return patched;
	}

	private static int TryPatchBattleResultIconProbes(Harmony h, ManualLogSource log)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return 0;

		// Real-name type: Hex.Session.Hud on Golden Era, moved to Hex.UI.SimBattle on build 25672315.
		var typeName = FindRuntimeType("Hex.Session.Hud.BhSimulatedBattle") != null
			? "Hex.Session.Hud.BhSimulatedBattle"
			: "Hex.UI.SimBattle.BhSimulatedBattle";
		var patched = 0;
		foreach (var methodName in GameSymbols.ReleaseTownUi.SimulatedBattleResultRefresh.NameHints)
		{
			if (string.IsNullOrWhiteSpace(methodName) || GameSymbolScope.IsSentinel(methodName))
				continue;
			patched += PatchByName(h, log, typeName, methodName, null, nameof(PostfixBattleResultIconProbe));
		}
		return patched;
	}

	private static int PatchByRuntimeType(Harmony h, ManualLogSource log, Type type, string methodName, Type firstParameterType, string postfixName)
	{
		try
		{
			if (type == null)
				return 0;

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name != methodName)
					continue;
				var parameters = method.GetParameters();
				if (firstParameterType != null && (parameters.Length == 0 || !GameInteropTypes.TypesMatch(parameters[0].ParameterType, firstParameterType)))
					continue;
				selected = method;
				break;
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + type.FullName + "." + methodName);
				return 0;
			}

			var postfix = typeof(Homm3CustomUiIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible runtime-type postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			LogSurfacePatch(log, selected);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + type?.FullName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static Type _abilityViewConfigType;
	private static Type _battleUnitType;

	private static Type ResolveAbilityViewConfigType()
	{
		if (_abilityViewConfigType != null)
			return _abilityViewConfigType;
		try { _abilityViewConfigType = typeof(Hex.Configs.AbilityViewConfig); }
		catch { _abilityViewConfigType = GameMember.FindType("ability.view.config", "AbilityViewConfig"); }
		return _abilityViewConfigType;
	}

	private static Type ResolveBattleUnitType()
	{
		if (_battleUnitType != null)
			return _battleUnitType;
		try { _battleUnitType = typeof(Hex.Session.Battle.Unit); }
		catch { _battleUnitType = GameMember.FindType("battle.unit", "Unit"); }
		return _battleUnitType;
	}

	private static Type[] ResolveAbilityViewConfigBindParameterTypes(bool swapOrder)
	{
		var configType = ResolveAbilityViewConfigType();
		if (configType == null)
			return null;
		return swapOrder
			? new[] { configType, null }
			: new[] { null, configType };
	}

	private static int PatchAnyBySymbol(Harmony h, ManualLogSource log, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName, bool logCandidates)
	{
		if (TrySelectSurfaceMethod(typeName, symbol, parameterTypes, null, out var selected))
			return TryApplySurfacePatch(h, log, selected, postfixName) ? 1 : 0;

		if (parameterTypes != null && parameterTypes.Length == 0)
		{
			var type = FindRuntimeType(typeName);
			var fallback = FindBestParameterlessVoidMethods(type);
			if (fallback.Length > 0 && TryApplySurfacePatch(h, log, fallback[0], postfixName))
				return 1;
		}

		if (logCandidates)
			log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + typeName + " symbol=" + symbol.Id + " shape=(" + DescribeParameterTypes(parameterTypes) + ")");
		return 0;
	}

	private static int PatchAnyBySymbolWithPrefix(Harmony h, ManualLogSource log, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string prefixName, string postfixName, bool logCandidates)
	{
		if (TrySelectSurfaceMethod(typeName, symbol, parameterTypes, null, out var selected))
			return TryApplySurfacePatchWithPrefixFinalizer(h, log, selected, prefixName, postfixName, null) ? 1 : 0;

		if (logCandidates)
			log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + typeName + " symbol=" + symbol.Id + " shape=(" + DescribeParameterTypes(parameterTypes) + ")");
		return 0;
	}
	private static int PatchExactAnyBySymbolWithPrefix(Harmony h, ManualLogSource log, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string prefixName, string postfixName, bool logCandidates)
	{
		if (TrySelectSurfaceMethodByExactSymbol(typeName, symbol, parameterTypes, out var selected))
			return TryApplySurfacePatchWithPrefixFinalizer(h, log, selected, prefixName, postfixName, null) ? 1 : 0;

		if (logCandidates)
			log?.LogWarning("Homm3CustomUiIcon: exact surface method not found: " + typeName + " symbol=" + symbol.Id + " shape=(" + DescribeParameterTypes(parameterTypes) + ")");
		return 0;
	}
	private static int PatchAllBySymbol(Harmony h, ManualLogSource log, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName, bool logCandidates)
	{
		var type = FindRuntimeType(typeName);
		if (type == null)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
			return 0;
		}

		var methods = GameMember.FindMethods(type, typeof(void), parameterTypes, symbol);
		if (methods.Length == 0)
			methods = FindMethodsByParameterShape(type, parameterTypes, typeof(void));

		if (methods.Length == 0 && parameterTypes != null && parameterTypes.Length == 0)
			methods = FindBestParameterlessVoidMethods(type);

		var patched = 0;
		var seen = new HashSet<MethodInfo>();
		foreach (var method in methods)
		{
			if (method == null || !seen.Add(method))
				continue;
			if (TryApplySurfacePatch(h, log, method, postfixName))
				patched++;
		}

		if (patched == 0 && logCandidates)
			log?.LogWarning("Homm3CustomUiIcon: surface method group not found: " + typeName + " symbol=" + symbol.Id + " shape=(" + DescribeParameterTypes(parameterTypes) + ")");
		return patched;
	}
	private static bool TrySelectSurfaceMethodByExactSymbol(string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, out MethodInfo selected)
	{
		selected = null;
		var type = FindRuntimeType(typeName);
		if (type == null || symbol.NameHints == null)
			return false;

		var paramCount = parameterTypes?.Length ?? -1;
		foreach (var hint in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, hint, StringComparison.Ordinal))
					continue;
				if (paramCount >= 0 && method.GetParameters().Length != paramCount)
					continue;
				if (parameterTypes != null && !ParametersMatchShape(method.GetParameters(), parameterTypes))
					continue;
				selected = method;
				return true;
			}
		}

		return false;
	}

	private static bool TrySelectSurfaceMethod(string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string exactName, out MethodInfo selected)
	{
		selected = null;
		var type = FindRuntimeType(typeName);
		if (type == null)
			return false;

		var paramCount = parameterTypes?.Length ?? -1;
		if (!string.IsNullOrWhiteSpace(exactName))
		{
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, exactName, StringComparison.Ordinal))
					continue;
				if (paramCount >= 0 && method.GetParameters().Length != paramCount)
					continue;
				selected = method;
				return true;
			}
		}

		if (!string.IsNullOrEmpty(symbol.Id) && symbol.NameHints != null)
		{
			foreach (var hint in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(hint))
					continue;
				foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
				{
					if (!string.Equals(method.Name, hint, StringComparison.Ordinal))
						continue;
					if (paramCount >= 0 && method.GetParameters().Length != paramCount)
						continue;
					if (parameterTypes != null && !ParametersMatchShape(method.GetParameters(), parameterTypes))
						continue;
					selected = method;
					return true;
				}
			}
		}

		if (!string.IsNullOrEmpty(symbol.Id) && parameterTypes != null)
		{
			selected = GameMember.FindFirstMethod(type, typeof(void), parameterTypes, symbol);
			if (selected != null)
				return true;
		}

		var shapeMatches = FindMethodsByParameterShape(type, parameterTypes, typeof(void));
		if (shapeMatches.Length > 0)
		{
			selected = shapeMatches[0];
			return true;
		}

		return false;
	}

	private static MethodInfo[] FindMethodsByParameterShape(Type type, Type[] parameterTypes, Type returnType)
	{
		if (type == null || parameterTypes == null)
			return Array.Empty<MethodInfo>();
		var matches = new List<MethodInfo>();
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
		{
			if (!IsPatchableInstanceMethod(method))
				continue;
			if (returnType != null && method.ReturnType != returnType)
				continue;
			if (!ParametersMatchShape(method.GetParameters(), parameterTypes))
				continue;
			matches.Add(method);
		}
		matches.Sort(CompareDeobfuscatedMethodRank);
		return matches.ToArray();
	}

	private static bool ParametersMatchShape(ParameterInfo[] parameters, Type[] expected)
	{
		if (parameters == null || expected == null || parameters.Length != expected.Length)
			return false;
		for (var i = 0; i < expected.Length; i++)
		{
			if (expected[i] == null)
				continue;
			if (!GameInteropTypes.TypesMatch(parameters[i].ParameterType, expected[i]))
				return false;
		}
		return true;
	}

	private static MethodInfo[] FindBestParameterlessVoidMethods(Type type)
	{
		if (type == null)
			return Array.Empty<MethodInfo>();
		var matches = new List<MethodInfo>();
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method.IsStatic || method.IsConstructor)
				continue;
			if (method.GetParameters().Length != 0 || method.ReturnType != typeof(void))
				continue;
			if (string.Equals(method.Name, "Finalize", StringComparison.Ordinal))
				continue;
			if (IsUnityLifecycleMethod(method.Name))
				continue;
			matches.Add(method);
		}
		if (matches.Count == 0)
			return Array.Empty<MethodInfo>();
		matches.Sort(CompareDeobfuscatedMethodRank);
		return new[] { matches[0] };
	}

	private static bool IsUnityLifecycleMethod(string methodName)
	{
		if (string.IsNullOrWhiteSpace(methodName))
			return false;
		return string.Equals(methodName, "Awake", StringComparison.Ordinal)
		       || string.Equals(methodName, "Start", StringComparison.Ordinal)
		       || string.Equals(methodName, "Update", StringComparison.Ordinal)
		       || string.Equals(methodName, "FixedUpdate", StringComparison.Ordinal)
		       || string.Equals(methodName, "LateUpdate", StringComparison.Ordinal)
		       || string.Equals(methodName, "OnEnable", StringComparison.Ordinal)
		       || string.Equals(methodName, "OnDisable", StringComparison.Ordinal)
		       || string.Equals(methodName, "OnDestroy", StringComparison.Ordinal)
		       || string.Equals(methodName, "OnExit", StringComparison.Ordinal)
		       || string.Equals(methodName, "OnHover", StringComparison.Ordinal)
		       || string.Equals(methodName, "DeleteModel", StringComparison.Ordinal)
		       || string.Equals(methodName, "ResetSlider", StringComparison.Ordinal);
	}

	private static int CompareDeobfuscatedMethodRank(MethodInfo a, MethodInfo b)
	{
		int Score(MethodInfo method)
		{
			if (method == null)
				return int.MaxValue;
			var score = 0;
			if (!method.IsPublic)
				score += 100;
			if (method.Name.Contains("_PDM_", StringComparison.Ordinal))
				score += 50;
			if (!method.Name.StartsWith("Method_", StringComparison.Ordinal))
				score += 200;
			var match = System.Text.RegularExpressions.Regex.Match(method.Name, @"_(\d+)$");
			if (match.Success && int.TryParse(match.Groups[1].Value, out var ordinal))
				score += ordinal;
			return score;
		}
		return Score(a).CompareTo(Score(b));
	}

	private static bool TryApplySurfacePatch(Harmony h, ManualLogSource log, MethodInfo selected, string postfixName)
	{
		if (selected == null)
			return false;
		var postfix = typeof(Homm3CustomUiIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
		{
			log?.LogWarning("Homm3CustomUiIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
			return false;
		}
		h.Patch(selected, postfix: new HarmonyMethod(postfix));
		LogSurfacePatch(log, selected);
		return true;
	}

	private static bool TryApplySurfacePatchWithPrefixFinalizer(Harmony h, ManualLogSource log, MethodInfo selected, string prefixName, string postfixName, string finalizerName)
	{
		if (selected == null)
			return false;
		var hookType = typeof(Homm3CustomUiIconHook);
		var prefix = string.IsNullOrWhiteSpace(prefixName) ? null : hookType.GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
		var postfix = string.IsNullOrWhiteSpace(postfixName) ? null : hookType.GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		var finalizer = string.IsNullOrWhiteSpace(finalizerName) ? null : hookType.GetMethod(finalizerName, BindingFlags.Static | BindingFlags.NonPublic);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(selected, prefix, out var prefixReason))
		{
			log?.LogWarning("Homm3CustomUiIcon: refusing incompatible prefix for " + FormatMethod(selected) + ": " + prefixReason);
			return false;
		}
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(selected, postfix, out var postfixReason))
		{
			log?.LogWarning("Homm3CustomUiIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + postfixReason);
			return false;
		}
		if (finalizer != null && !GameMember.IsHarmonyPatchCompatible(selected, finalizer, out var finalizerReason))
		{
			log?.LogWarning("Homm3CustomUiIcon: refusing incompatible finalizer for " + FormatMethod(selected) + ": " + finalizerReason);
			return false;
		}
		h.Patch(selected,
			prefix: prefix != null ? new HarmonyMethod(prefix) : null,
			postfix: postfix != null ? new HarmonyMethod(postfix) : null,
			finalizer: finalizer != null ? new HarmonyMethod(finalizer) : null);
		LogSurfacePatch(log, selected);
		return true;
	}

	private static string DescribeParameterTypes(Type[] parameterTypes)
	{
		if (parameterTypes == null || parameterTypes.Length == 0)
			return "";
		return string.Join(", ", Array.ConvertAll(parameterTypes, t => t?.Name ?? "*"));
	}

	private static int PatchBuildingViewHoverRefreshByShape(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		patched += PatchSingleMethodByShape(h, log, "Hex.UI.City.BhBuildingView", GameSymbols.ReleaseTownUi.BuildingViewHoverRefresh.NameHints,
			parameters => parameters.Length == 3 && ParameterTypeNameMatches(parameters[1], GameSymbols.ReleaseTownUi.BuildingModelTypeNames) && parameters[2].ParameterType == typeof(int),
			nameof(PostfixBuildingViewBind), "building-view hover refresh 3-arg");
		if (patched > 0)
			return patched;
		patched += PatchSingleMethodByShape(h, log, "Hex.UI.City.BhBuildingView", GameSymbols.ReleaseTownUi.BuildingViewHoverRefresh.NameHints,
			parameters => parameters.Length == 2 && parameters[0].ParameterType == typeof(int) && parameters[1].ParameterType == typeof(int),
			nameof(PostfixBuildingViewBind), "building-view hover refresh 2-arg");
		if (patched > 0)
			return patched;
		return PatchSingleMethodByShape(h, log, "Hex.UI.City.BhBuildingView", GameSymbols.ReleaseTownUi.BuildingViewHoverRefresh.NameHints,
			parameters => parameters.Length == 0,
			nameof(PostfixBuildingViewBind), "building-view hover refresh 0-arg");
	}

	private static int PatchBuildingTooltipByShape(Harmony h, ManualLogSource log)
	{
		var typeName = "Hex.UI.BhTooltipBuilding";
		if (TrySelectSurfaceMethod(typeName, GameSymbols.ReleaseTownUi.BuildingTooltipBind, new[] { null, null, typeof(int), null }, null, out var selected)
		    || TrySelectSurfaceMethod(typeName, GameSymbols.ReleaseTownUi.BuildingTooltipBind, new[] { null, null, typeof(int) }, null, out selected))
		{
			return TryApplySurfacePatch(h, log, selected, nameof(PostfixBuildingTooltipFromCity)) ? 1 : 0;
		}

		var type = FindRuntimeType(typeName);
		if (type == null)
			return 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			var ps = method.GetParameters();
			if (method.ReturnType != typeof(void))
				continue;
			if (ps.Length == 4 && ps[0].ParameterType.Name.IndexOf("BhBuildingView", StringComparison.Ordinal) >= 0
			    && ParameterTypeNameMatches(ps[1], GameSymbols.ReleaseTownUi.BuildingModelTypeNames)
			    && ps[2].ParameterType == typeof(int))
				return TryApplySurfacePatch(h, log, method, nameof(PostfixBuildingTooltipFromCity)) ? 1 : 0;
			if (ps.Length == 3 && ParameterTypeNameMatches(ps[0], GameSymbols.ReleaseTownUi.BuildingModelTypeNames)
			    && ParameterTypeNameMatches(ps[1], GameSymbols.ReleaseTownUi.BuildingModelTypeNames)
			    && ps[2].ParameterType == typeof(int))
				return TryApplySurfacePatch(h, log, method, nameof(PostfixBuildingTooltipFromCity)) ? 1 : 0;
		}
		log?.LogWarning("Homm3CustomUiIcon: compatible building-tooltip bind method not found on " + typeName + ".");
		return 0;
	}

	private static int PatchHireUnitItemRefreshByShape(Harmony h, ManualLogSource log)
	{
		var typeName = "Hex.UI.City.BhHireUnitItemView";
		var symbol = GameSymbols.ReleaseTownUi.HireUnitItemRefresh;
		var hireArgsType = FindRuntimeType("Hex.UI.HireArgs");
		if (hireArgsType != null)
		{
			var patched = PatchAnyBySymbol(h, log, typeName, symbol, new[] { hireArgsType, typeof(int) }, nameof(PostfixHireUnitItemInit), false);
			if (patched > 0)
				return patched;
		}
		var intOnly = PatchAnyBySymbol(h, log, typeName, symbol, new[] { typeof(int) }, nameof(PostfixHireUnitItemInit), false);
		if (intOnly > 0)
			return intOnly;
		return PatchAnyBySymbol(h, log, typeName, symbol, Array.Empty<Type>(), nameof(PostfixHireUnitItemInit), false);
	}

	private static int PatchHireIncrementItemByShape(Harmony h, ManualLogSource log, bool withSpritePrefix)
	{
		var typeName = "Hex.UI.City.BhCityHireIncrementItemView";
		var symbol = withSpritePrefix
			? GameSymbols.ReleaseTownUi.HireIncrementItemSprite
			: GameSymbols.ReleaseTownUi.HireIncrementItemBind;
		var type = FindRuntimeType(typeName);
		if (type == null)
			return 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			var ps = method.GetParameters();
			if (method.ReturnType != typeof(void) || ps.Length == 0 || ps[0].ParameterType != typeof(Sprite))
				continue;
			if (withSpritePrefix)
				return TryApplySurfacePatchWithPrefixFinalizer(h, log, method, nameof(PrefixRecruitmentIncrementItemSprite), nameof(PostfixRecruitmentIncrementItemView), null) ? 1 : 0;
			return TryApplySurfacePatch(h, log, method, nameof(PostfixRecruitmentIncrementItemView)) ? 1 : 0;
		}
		log?.LogWarning("Homm3CustomUiIcon: compatible hire-increment sprite bind not found on " + typeName + ".");
		return 0;
	}

	private static int PatchHireUnitItemModelByShape(Harmony h, ManualLogSource log, bool listMode)
	{
		var typeName = "Hex.UI.City.BhHireUnitItemView";
		var symbol = listMode
			? GameSymbols.ReleaseTownUi.HireUnitItemModelList
			: GameSymbols.ReleaseTownUi.HireUnitItemModelOut;
		if (TrySelectHireUnitModelMethod(typeName, symbol, listMode, out var selected))
			return PatchByNameWithFinalizer(h, log, typeName, selected.Name, null, nameof(FinalizerHireUnitModelListStronghold));

		log?.LogWarning("Homm3CustomUiIcon: compatible hire-unit model " + (listMode ? "list" : "out") + " method not found on " + typeName + ".");
		return 0;
	}

	private static bool TrySelectHireUnitModelMethod(string typeName, GameSymbols.MethodSymbol symbol, bool listMode, out MethodInfo selected)
	{
		selected = null;
		var type = FindRuntimeType(typeName);
		if (type == null)
			return false;

		if (symbol.NameHints != null)
		{
			foreach (var hint in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(hint))
					continue;
				foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
				{
					if (!IsPatchableInstanceMethod(method) || method.Name != hint)
						continue;
					if (!IsHireUnitModelMethodShape(method, listMode))
						continue;
					selected = method;
					return true;
				}
			}
		}

		MethodInfo best = null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (!IsPatchableInstanceMethod(method) || !IsHireUnitModelMethodShape(method, listMode))
				continue;
			if (best == null || CompareDeobfuscatedMethodRank(method, best) < 0)
				best = method;
		}

		selected = best;
		return selected != null;
	}

	private static bool IsHireUnitModelMethodShape(MethodInfo method, bool listMode)
	{
		if (method == null || method.ReturnType != typeof(void))
			return false;
		var ps = method.GetParameters();
		if (listMode)
			return ps.Length == 1 && IsIReadOnlyListOfString(ps[0].ParameterType);
		return ps.Length == 2
		       && ps[0].ParameterType == typeof(string)
		       && ps[1].ParameterType.IsByRef;
	}

	private static bool IsIReadOnlyListOfString(Type type)
	{
		if (type == null)
			return false;
		var name = type.FullName ?? type.Name ?? string.Empty;
		return name.IndexOf("IReadOnlyList", StringComparison.Ordinal) >= 0
		       && name.IndexOf("String", StringComparison.Ordinal) >= 0;
	}

	private static bool IsPatchableInstanceMethod(MethodInfo method)
	{
		if (method == null || method.IsConstructor || method.IsStatic)
			return false;
		var name = method.Name;
		return !name.StartsWith("get_", StringComparison.Ordinal)
		       && !name.StartsWith("set_", StringComparison.Ordinal)
		       && !name.StartsWith("add_", StringComparison.Ordinal)
		       && !name.StartsWith("remove_", StringComparison.Ordinal)
		       && !name.StartsWith("Method_Public_add_", StringComparison.Ordinal)
		       && !name.StartsWith("Method_Public_rem_", StringComparison.Ordinal);
	}

	private static int PatchHireUnitAbilitiesBindByShape(Harmony h, ManualLogSource log)
	{
		var unitType = ResolveBattleUnitType();
		if (unitType == null)
			return 0;
		var typeName = "Hex.BhHireUnitAbilities";
		if (TrySelectSurfaceMethod(typeName, GameSymbols.UnitPreviewAbilityIcons.HireUnitAbilitiesBind, new[] { unitType }, null, out var selected))
			return TryApplySurfacePatchWithPrefixFinalizer(h, log, selected, nameof(PrefixHireUnitAbilitiesBind), nameof(PostfixHireUnitAbilitiesBind), nameof(FinalizerHireUnitAbilitiesBind)) ? 1 : 0;
		log?.LogWarning("Homm3CustomUiIcon: compatible hire-unit abilities bind not found on " + typeName + ".");
		return 0;
	}

	private static int PatchBattleAbilityViewBindByShape(Harmony h, ManualLogSource log)
	{
		var typeName = "Hex.Session.Battle.BhUnitAbilityView";
		var type = FindRuntimeType(typeName);
		if (type == null)
			return 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			var ps = method.GetParameters();
			if (method.ReturnType != typeof(void) || ps.Length != 2 || ps[1].ParameterType != typeof(bool))
				continue;
			if (!FirstParameterTypeNameMatches(ps, GameSymbols.SelectedUnitHud.AbilityViewWrapperTypeNames))
				continue;
			return TryApplySurfacePatchWithPrefixFinalizer(h, log, method, nameof(PrefixBattleAbilityViewBindRelease), nameof(PostfixBattleAbilityViewBindRelease), null) ? 1 : 0;
		}
		log?.LogWarning("Homm3CustomUiIcon: compatible battle ability-view bind not found on " + typeName + ".");
		return 0;
	}

	private static int PatchByName(Harmony h, ManualLogSource log, string typeName, string methodName, Type firstParameterType, string postfixName)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name != methodName)
					continue;
				var parameters = method.GetParameters();
				if (firstParameterType != null && (parameters.Length == 0 || !GameInteropTypes.TypesMatch(parameters[0].ParameterType, firstParameterType)))
					continue;
				selected = method;
				break;
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + typeName + "." + methodName);
				return 0;
			}

			var postfix = typeof(Homm3CustomUiIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			LogSurfacePatch(log, selected);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchByRuntimeType(Harmony h, ManualLogSource log, Type type, GameSymbols.MethodSymbol symbol, Type firstParameterType, string postfixName)
	{
		try
		{
			if (type == null)
				return 0;

			MethodInfo selected = null;
			var names = symbol.NameHints ?? Array.Empty<string>();
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (Array.IndexOf(names, method.Name) < 0)
					continue;
				var parameters = method.GetParameters();
				if (firstParameterType != null && (parameters.Length == 0 || !GameInteropTypes.TypesMatch(parameters[0].ParameterType, firstParameterType)))
					continue;
				selected = method;
				break;
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + type.FullName + "." + symbol.Id);
				return 0;
			}

			var postfix = typeof(Homm3CustomUiIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible runtime-type postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			LogSurfacePatch(log, selected);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + type?.FullName + "." + symbol.Id + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchAnyByName(Harmony h, ManualLogSource log, string typeName, IEnumerable<string> methodNames, Type firstParameterType, string postfixName)
	{
		if (methodNames == null)
			return 0;

		var patched = 0;
		var seen = new HashSet<string>(StringComparer.Ordinal);
		foreach (var methodName in methodNames)
		{
			if (string.IsNullOrWhiteSpace(methodName) || !seen.Add(methodName))
				continue;
			patched += PatchByName(h, log, typeName, methodName, firstParameterType, postfixName);
		}
		return patched;
	}

	private static int PatchBuildingViewBindByShape(Harmony h, ManualLogSource log)
	{
		return PatchSingleBuildingViewMethodByShape(
			h,
			log,
			GameSymbols.ReleaseTownUi.BuildingViewBind.NameHints,
			parameters => parameters.Length == 3 && ParameterTypeNameMatches(parameters[1], GameSymbols.ReleaseTownUi.BuildingModelTypeNames) && parameters[2].ParameterType == typeof(int),
			nameof(PostfixBuildingViewBind),
			"argument-bearing bind");
	}

	private static int PatchBuildingViewSecondaryBindByShape(Harmony h, ManualLogSource log)
	{
		return PatchSingleBuildingViewMethodByShape(
			h,
			log,
			GameSymbols.ReleaseTownUi.BuildingViewSecondaryBind.NameHints,
			parameters => parameters.Length == 2 && parameters[0].ParameterType == typeof(int) && parameters[1].ParameterType == typeof(int),
			nameof(PostfixBuildingViewBind),
			"secondary bind");
	}

	private static int PatchTooltipUnitsViewBindByShape(Harmony h, ManualLogSource log)
	{
		return PatchSingleMethodByShape(
			h,
			log,
			"Hex.UI.Tooltips.BhTooltipUnitsView",
			GameSymbols.ReleaseTownUi.TooltipUnitsViewBind.NameHints,
			parameters => parameters.Length == 2 && ParameterTypeNameMatches(parameters[0], GameSymbols.ReleaseTownUi.BuildingModelTypeNames) && parameters[1].ParameterType == typeof(int),
			nameof(PostfixTooltipUnitsView),
			"tooltip-units building bind");
	}

	private static int PatchMagicItemViewShowByShape(Harmony h, ManualLogSource log)
	{
		return PatchSingleMethodByShape(
			h,
			log,
			"Hex.Session.UI.BhMagicItemView",
			new[] { "Show" },
			parameters => parameters.Length == 5
			              && ParameterTypeNameMatches(parameters[0], GameSymbols.ReleaseTownUi.MagicItemShowArg0TypeHints)
			              && ParameterTypeNameMatches(parameters[2], GameSymbols.ReleaseTownUi.MagicItemShowArg2TypeHints)
			              && parameters[4].ParameterType == typeof(bool),
			nameof(PostfixMagicItemViewShow),
			"spellbook magic-item show" );
	}

	private static int PatchSingleBuildingViewMethodByShape(
		Harmony h,
		ManualLogSource log,
		IEnumerable<string> methodNames,
		Func<ParameterInfo[], bool> parameterPredicate,
		string postfixName,
		string surfaceLabel)
	{
		return PatchSingleMethodByShape(h, log, "Hex.UI.City.BhBuildingView", methodNames, parameterPredicate, postfixName, "building-view " + surfaceLabel);
	}

	private static int PatchSingleMethodByShape(
		Harmony h,
		ManualLogSource log,
		string typeName,
		IEnumerable<string> methodNames,
		Func<ParameterInfo[], bool> parameterPredicate,
		string postfixName,
		string surfaceLabel)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
				return 0;
			}

			var postfix = typeof(Homm3CustomUiIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			var names = new HashSet<string>(StringComparer.Ordinal);
			if (methodNames != null)
			{
				foreach (var methodName in methodNames)
				{
					if (!string.IsNullOrWhiteSpace(methodName))
						names.Add(methodName.Trim());
				}
			}

			MethodInfo selected = null;
			if (names.Count > 0)
			{
				foreach (var methodName in names)
				{
					foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
					{
						if (method.Name != methodName)
							continue;
						var parameters = method.GetParameters();
						if (parameterPredicate != null && !parameterPredicate(parameters))
							continue;
						selected = method;
						break;
					}
					if (selected != null)
						break;
				}
			}

			if (selected == null)
			{
				foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
				{
					var parameters = method.GetParameters();
					if (parameterPredicate != null && !parameterPredicate(parameters))
						continue;
					if (selected == null || CompareDeobfuscatedMethodRank(method, selected) < 0)
						selected = method;
				}
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: compatible " + surfaceLabel + " method not found on " + type.FullName + ".");
				return 0;
			}

			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible " + surfaceLabel + " postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			LogSurfacePatch(log, selected);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: " + surfaceLabel + " patch failed: " + ex.Message);
			return 0;
		}
	}

	private static bool ParameterTypeNameMatches(ParameterInfo parameter, IEnumerable<string> acceptedTypeNames)
	{
		if (parameter == null)
			return false;
		var allowed = new HashSet<string>(StringComparer.Ordinal);
		if (acceptedTypeNames != null)
		{
			foreach (var acceptedName in acceptedTypeNames)
			{
				if (!string.IsNullOrWhiteSpace(acceptedName))
					allowed.Add(acceptedName.Trim());
			}
		}
		if (allowed.Count == 0)
			return true;

		var type = parameter.ParameterType;
		var parameterTypeName = StripGenericArity(type?.Name);
		var fullName = StripGenericArity(type?.FullName);
		if ((!string.IsNullOrWhiteSpace(parameterTypeName) && allowed.Contains(parameterTypeName))
		    || (!string.IsNullOrWhiteSpace(fullName) && allowed.Contains(fullName)))
			return true;

		foreach (var acceptedName in allowed)
		{
			var resolved = GameMember.FindType("release.townUi.type." + acceptedName, acceptedName);
			if (resolved != null && GameInteropTypes.TypesMatch(type, resolved))
				return true;
		}
		return false;
	}

	private static int PatchHeroProfileIconViewByShape(Harmony h, ManualLogSource log, string typeName, string postfixName)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
				return 0;
			}

			var postfix = typeof(Homm3CustomUiIconHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			var patched = 0;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				if (!IsHeroProfileIconBindCandidate(method))
					continue;
				if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
				{
					log?.LogWarning("Homm3CustomUiIcon: refusing incompatible hero-profile icon postfix for " + FormatMethod(method) + ": " + reason);
					continue;
				}
				h.Patch(method, postfix: new HarmonyMethod(postfix));
				LogSurfacePatch(log, method);
				log?.LogInfo("Homm3CustomUiIcon: hero-profile icon bind postfix registered on " + FormatMethod(method) + ".");
				patched++;
			}
			if (patched == 0)
				LogHeroProfileIconCandidates(type, log);
			return patched;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + typeName + " hero-profile icon bind: " + ex.Message);
			return 0;
		}
	}

	private static bool IsHeroProfileIconBindCandidate(MethodInfo method)
	{
		if (method == null || method.ContainsGenericParameters || method.ReturnType != typeof(void))
			return false;
		if (method.IsSpecialName)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != 1)
			return false;
		var parameterType = parameters[0].ParameterType;
		if (parameterType == typeof(bool) || parameterType == typeof(int) || parameterType == typeof(string))
			return false;
		var parameterTypeName = parameterType.FullName ?? parameterType.Name;
		if (parameterTypeName.Contains("UnityEngine.EventSystems.PointerEventData"))
			return false;
		return true;
	}

	private static void LogHeroProfileIconCandidates(Type type, ManualLogSource log)
	{
		if (type == null || log == null)
			return;
		try
		{
			var logged = 0;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				if (logged++ >= 12)
					break;
				log.LogWarning("Homm3CustomUiIcon diag: hero-profile icon candidate " + FormatMethod(method) + ".");
			}
		}
		catch (Exception ex)
		{
			log.LogWarning("Homm3CustomUiIcon diag: hero-profile icon candidate dump failed for " + (type.FullName ?? type.Name) + ": " + ex.Message);
		}
	}

	private static int PatchByNameWithPrefix(Harmony h, ManualLogSource log, string typeName, string methodName, Type firstParameterType, string prefixName, string postfixName, string finalizerName = null)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name != methodName)
					continue;
				var parameters = method.GetParameters();
				if (firstParameterType != null && (parameters.Length == 0 || !GameInteropTypes.TypesMatch(parameters[0].ParameterType, firstParameterType)))
					continue;
				selected = method;
				break;
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + typeName + "." + methodName);
				return 0;
			}

			var hookType = typeof(Homm3CustomUiIconHook);
			var prefix = string.IsNullOrWhiteSpace(prefixName) ? null : hookType.GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
			var postfix = hookType.GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			var finalizer = string.IsNullOrWhiteSpace(finalizerName) ? null : hookType.GetMethod(finalizerName, BindingFlags.Static | BindingFlags.NonPublic);
			if (prefix != null && !GameMember.IsHarmonyPatchCompatible(selected, prefix, out var prefixReason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible prefix for " + FormatMethod(selected) + ": " + prefixReason);
				return 0;
			}
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var postfixReason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + postfixReason);
				return 0;
			}
			if (finalizer != null && !GameMember.IsHarmonyPatchCompatible(selected, finalizer, out var finalizerReason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible finalizer for " + FormatMethod(selected) + ": " + finalizerReason);
				return 0;
			}
			h.Patch(selected,
				prefix: prefix != null ? new HarmonyMethod(prefix) : null,
				postfix: new HarmonyMethod(postfix),
				finalizer: finalizer != null ? new HarmonyMethod(finalizer) : null);
			LogSurfacePatch(log, selected);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchAnyByNameWithPrefix(Harmony h, ManualLogSource log, string typeName, IEnumerable<string> methodNames, Type firstParameterType, string prefixName, string postfixName, string finalizerName = null)
	{
		if (methodNames == null)
			return 0;

		var patched = 0;
		var seen = new HashSet<string>(StringComparer.Ordinal);
		foreach (var methodName in methodNames)
		{
			if (string.IsNullOrWhiteSpace(methodName) || !seen.Add(methodName))
				continue;
			patched += PatchByNameWithPrefix(h, log, typeName, methodName, firstParameterType, prefixName, postfixName, finalizerName);
		}
		return patched;
	}

	private static int PatchAnyByNameWithPrefixByFirstParameterTypeName(Harmony h, ManualLogSource log, string typeName, IEnumerable<string> methodNames, IEnumerable<string> firstParameterTypeNames, string prefixName, string postfixName, string finalizerName = null)
	{
		if (methodNames == null)
			return 0;

		var patched = 0;
		var seen = new HashSet<string>(StringComparer.Ordinal);
		foreach (var methodName in methodNames)
		{
			if (string.IsNullOrWhiteSpace(methodName) || !seen.Add(methodName))
				continue;
			patched += PatchByNameWithPrefixByFirstParameterTypeName(h, log, typeName, methodName, firstParameterTypeNames, prefixName, postfixName, finalizerName);
		}
		return patched;
	}

	private static int PatchByNameWithPrefixByFirstParameterTypeName(Harmony h, ManualLogSource log, string typeName, string methodName, IEnumerable<string> firstParameterTypeNames, string prefixName, string postfixName, string finalizerName = null)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name != methodName)
					continue;
				var parameters = method.GetParameters();
				if (!FirstParameterTypeNameMatches(parameters, firstParameterTypeNames))
					continue;
				selected = method;
				break;
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + typeName + "." + methodName);
				return 0;
			}

			var hookType = typeof(Homm3CustomUiIconHook);
			var prefix = hookType.GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
			var postfix = hookType.GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			var finalizer = string.IsNullOrWhiteSpace(finalizerName) ? null : hookType.GetMethod(finalizerName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, prefix, out var prefixReason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible prefix for " + FormatMethod(selected) + ": " + prefixReason);
				return 0;
			}
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var postfixReason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible postfix for " + FormatMethod(selected) + ": " + postfixReason);
				return 0;
			}
			if (finalizer != null && !GameMember.IsHarmonyPatchCompatible(selected, finalizer, out var finalizerReason))
			{
				log?.LogWarning("Homm3CustomUiIcon: refusing incompatible finalizer for " + FormatMethod(selected) + ": " + finalizerReason);
				return 0;
			}
			h.Patch(selected,
				prefix: new HarmonyMethod(prefix),
				postfix: new HarmonyMethod(postfix),
				finalizer: finalizer != null ? new HarmonyMethod(finalizer) : null);
			LogSurfacePatch(log, selected);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static bool FirstParameterTypeNameMatches(ParameterInfo[] parameters, IEnumerable<string> acceptedTypeNames)
	{
		if (parameters == null || parameters.Length == 0)
			return false;
		var allowed = new HashSet<string>(StringComparer.Ordinal);
		if (acceptedTypeNames != null)
		{
			foreach (var acceptedName in acceptedTypeNames)
			{
				if (!string.IsNullOrWhiteSpace(acceptedName))
					allowed.Add(acceptedName.Trim());
			}
		}
		if (allowed.Count == 0)
			return true;

		var type = parameters[0].ParameterType;
		var parameterTypeName = StripGenericArity(type?.Name);
		var fullName = StripGenericArity(type?.FullName);
		if ((!string.IsNullOrWhiteSpace(parameterTypeName) && allowed.Contains(parameterTypeName))
		    || (!string.IsNullOrWhiteSpace(fullName) && allowed.Contains(fullName)))
			return true;

		foreach (var acceptedName in allowed)
		{
			var resolved = GameMember.FindType("battle.selectedUnit.wrapper." + acceptedName, acceptedName);
			if (resolved != null && GameInteropTypes.TypesMatch(type, resolved))
				return true;
		}
		return false;
	}

	private static string StripGenericArity(string typeName)
	{
		if (string.IsNullOrWhiteSpace(typeName))
			return typeName;
		var arity = typeName.IndexOf('`');
		return arity < 0 ? typeName : typeName.Substring(0, arity);
	}

	private static int PatchAnyByNameWithFinalizer(Harmony h, ManualLogSource log, string typeName, IEnumerable<string> methodNames, Type firstParameterType, string finalizerName)
	{
		if (methodNames == null)
			return 0;

		var patched = 0;
		var seen = new HashSet<string>(StringComparer.Ordinal);
		foreach (var methodName in methodNames)
		{
			if (string.IsNullOrWhiteSpace(methodName) || !seen.Add(methodName))
				continue;
			patched += PatchByNameWithFinalizer(h, log, typeName, methodName, firstParameterType, finalizerName);
		}
		return patched;
	}

	private static int PatchByNameWithFinalizer(Harmony h, ManualLogSource log, string typeName, string methodName, Type firstParameterType, string finalizerName)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (!IsPatchableInstanceMethod(method) || method.Name != methodName)
					continue;
				var parameters = method.GetParameters();
				if (firstParameterType != null && (parameters.Length == 0 || !GameInteropTypes.TypesMatch(parameters[0].ParameterType, firstParameterType)))
					continue;
				selected = method;
				break;
			}

			if (selected == null)
			{
				log?.LogWarning("Homm3CustomUiIcon: surface method not found: " + typeName + "." + methodName);
				return 0;
			}

			return ApplyFinalizerPatch(h, log, selected, finalizerName);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3CustomUiIcon: surface patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int ApplyFinalizerPatch(Harmony h, ManualLogSource log, MethodInfo selected, string finalizerName)
	{
		var finalizer = typeof(Homm3CustomUiIconHook).GetMethod(finalizerName, BindingFlags.Static | BindingFlags.NonPublic);
		if (!GameMember.IsHarmonyPatchCompatible(selected, finalizer, out var reason))
		{
			log?.LogWarning("Homm3CustomUiIcon: refusing incompatible finalizer for " + FormatMethod(selected) + ": " + reason);
			return 0;
		}
		h.Patch(selected, finalizer: new HarmonyMethod(finalizer));
		LogSurfacePatch(log, selected);
		return 1;
	}

	// Contract (validate_native_hook_safety_contract.py): this prefix runs inside native
	// Method_Public_Sprite_String_0. An exception escaping it has black-screened the Fortress city
	// UI and aborted every custom-faction build panel. It must never throw: an unresolved custom key
	// declines (native keeps its own miss behaviour) and is logged once per key.
	private static bool PrefixSpriteResolver([HarmonyArgument(0)] string key, ref Sprite __result, MethodBase __originalMethod)
	{
		try
		{
			return PrefixSpriteResolverCore(key, ref __result, __originalMethod);
		}
		catch (Exception ex)
		{
			LogSpriteResolverDecline(key, "exception " + ex.GetType().Name + ": " + ex.Message, __originalMethod);
			return true;
		}
	}

	private static readonly HashSet<string> SpriteResolverDeclinedKeys = new(StringComparer.Ordinal);

	private static void LogSpriteResolverDecline(string key, string reason, MethodBase method)
	{
		var logKey = key ?? "(null)";
		lock (SpriteResolverDeclinedKeys)
		{
			if (!SpriteResolverDeclinedKeys.Add(logKey))
				return;
		}
		Plugin.LogSource?.LogWarning(
			"Homm3CustomUiIcon: custom sprite key '" + logKey + "' unresolved (" + (reason ?? "unknown")
			+ "); declined to native via " + FormatMethod(method) + ". Logged once per key.");
	}

	private static bool PrefixSpriteResolverCore(string key, ref Sprite __result, MethodBase __originalMethod)
	{
		if (!IsCustomKey(key))
			return true;
		if (!Homm3NativeSpriteCatalogRegistrar.TryEnsureRegistered(key, TryResolveSprite, out var sprite, out var reason))
		{
			LogResolverReplace("SpriteCatalogMiss", key, reason ?? "unknown", __originalMethod);
			LogSpriteResolverDecline(key, "native-catalog " + (reason ?? "unknown"), __originalMethod);
			return true;
		}
		LogResolverReplace("SpriteCatalog", key, sprite ? sprite.name : "registered", __originalMethod);
		// Dialog hero portraits: seeding the native catalog then returning true still left
		// dialogue UI blank. Short-circuit only that key class; other custom icons must let
		// native cko.sfo continue after registration (battle ability / city UI contract).
		if (Homm3DialogPortraitCatalog.IsDialogHeroPortraitKey(key))
		{
			__result = sprite;
			Plugin.LogSource?.LogInfo(
				"Homm3DialogPortrait: sfo short-circuit key='"
				+ key
				+ "' sprite='"
				+ (sprite ? sprite.name : "null")
				+ "' tex="
				+ (sprite && sprite.texture ? sprite.texture.width + "x" + sprite.texture.height : "none")
				+ " via "
				+ FormatMethod(__originalMethod)
				+ ".");
			return false;
		}
		if (Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(key))
			TryApplyAllCityUiElements("resolver " + FormatMethod(__originalMethod), key, sprite);
		return true;
	}

	private static bool PrefixTextureResolver([HarmonyArgument(0)] string key, ref Texture __result, MethodBase __originalMethod)
	{
		if (!TryResolveSprite(key, out var sprite) || !sprite || !sprite.texture)
			return true;
		__result = sprite.texture;
		LogResolverReplace("Texture", key, sprite.texture.name, __originalMethod);
		if (Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(key))
			TryApplyAllCityUiElements("resolver " + FormatMethod(__originalMethod), key, sprite);
		return false;
	}

	private static bool PrefixTexture2DResolver([HarmonyArgument(0)] string key, ref Texture2D __result, MethodBase __originalMethod)
	{
		if (!TryResolveSprite(key, out var sprite) || !sprite || !sprite.texture)
			return true;
		var texture = sprite.texture as Texture2D;
		if (!texture)
			return true;
		__result = texture;
		LogResolverReplace("Texture2D", key, texture.name, __originalMethod);
		if (Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(key))
			TryApplyAllCityUiElements("resolver " + FormatMethod(__originalMethod), key, sprite);
		return false;
	}

	private static void PostfixMagicItemViewShow(object __instance, [HarmonyArgument(0)] object magic, MethodBase __originalMethod)
	{
		try
		{
			magic ??= TryGetMemberValue(__instance, "cdnm");
			var key = ResolveMagicItemIconKey(magic);
			if (!TryApplyMagicItemViewIconSurface(__instance, key, FormatMethod(__originalMethod))
			    && _loggedSpellbookMagicIconMiss++ < 24
			    && Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(key))
			{
				Plugin.LogSource?.LogInfo("Homm3CustomUiIcon: spellbook magic icon not applied key=" + (key ?? "(null)")
				                             + " source=" + FormatMethod(__originalMethod)
				                             + " view=" + DescribeIconSurface(__instance) + ".");
			}
		}
		catch (Exception ex)
		{
			if (_loggedSpellbookMagicIconReplace++ < 10)
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: spellbook magic icon replacement failed: " + ex.Message);
		}
	}

	private static void PostfixStringArg0Surface(object __instance, [HarmonyArgument(0)] string key, MethodBase __originalMethod)
	{
		TryApplyToSurface(__instance, key, FormatMethod(__originalMethod));
	}

	private static void PostfixHeroProfileSpecializationIcon(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var payload = __args != null && __args.Length > 0 ? __args[0] : null;
			TryApplyHeroProfileSpecializationIconSurface(__instance, FormatMethod(__originalMethod), payload);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: inventory specialization icon failed: " + ex.Message);
		}
	}

	internal static bool TryApplyHeroProfileSpecializationIconSurface(object view, string source, object heroPayload = null)
	{
		if (Homm3HeroSpecializationIconUi.TryApplyForSpecializationView(view, heroPayload, source))
			return true;

		var heroConfig = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(heroPayload) != null
			? heroPayload
			: null;
		var heroSid = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(heroPayload);
		return Homm3HeroSpecializationIconUi.TryApplyForHeroConfig(heroConfig, heroSid, view, "inventory-specialization-icon");
	}

	private static void PostfixHeroProfileSkillIcon(object __instance, MethodBase __originalMethod)
	{
		try
		{
			var key = ResolveHeroProfileSkillIconKey(__instance);
			TryApplyHeroProfileIconSurface(__instance, key, FormatMethod(__originalMethod), "inventory-skill-icon");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: inventory skill icon failed: " + ex.Message);
		}
	}

	private static void PostfixHeroProfileSubSkillIcon(object __instance, MethodBase __originalMethod)
	{
		try
		{
			var key = ResolveHeroProfileSubSkillIconKey(__instance);
			TryApplyHeroProfileIconSurface(__instance, key, FormatMethod(__originalMethod), "inventory-subskill-icon");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: inventory subskill icon failed: " + ex.Message);
		}
	}

	private static void PostfixLevelUpSkillIcon(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var runtime = __args != null && __args.Length > 1 ? __args[1] : null;
			var key = ResolveSkillRuntimeIconKey(runtime);
			TryApplyLevelUpIconSurface(__instance, key, FormatMethod(__originalMethod), "level-up-skill-icon");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: level-up skill icon failed: " + ex.Message);
		}
	}

	private static void PrefixStringArg0DonorSurface(object __instance, [HarmonyArgument(0)] ref string key, ref string __state, MethodBase __originalMethod)
	{
		__state = null;
		if (!Homm3CustomFactionRegistry.IsCustomUnitSid(key))
			return;
		// Identity-bearing native bind path: preserve the custom SID and leave donor mappings to view-only repaint helpers.
		__state = key;
		RememberRecruitmentItemSid(__instance, __state);
		if (_loggedHireDonorAlias < 16)
		{
			_loggedHireDonorAlias++;
			Plugin.LogSource?.LogInfo("Homm3CustomUiIcon: hire item custom sid '" + __state + "' preserved for " + FormatMethod(__originalMethod) + ".");
		}
	}

	private static void PostfixStringArg0DonorSurface(object __instance, [HarmonyArgument(0)] string key, string __state, MethodBase __originalMethod)
	{
		var resolvedSid = string.IsNullOrWhiteSpace(__state) ? key : __state;
		TryApplyToSurface(__instance, resolvedSid, FormatMethod(__originalMethod));
		TryApplyRecruitmentItemView(__instance, -1, FormatMethod(__originalMethod) + ".hire-card", resolvedSid);
	}

	private sealed class HireAbilityBindState
	{
		internal Unit Unit;
		internal UnitLogicConfig OldLogic;
		internal UnitViewConfig OldView;
		internal string CustomSid;
		internal string DonorSid;
	}


	private sealed class HireAbilityBindConfig
	{
		internal AbilityLogicConfig Logic;
		internal AbilityViewConfig View;
	}


	private static void PrefixHireUnitAbilitiesBind(object __instance, [HarmonyArgument(0)] Unit unit, ref HireAbilityBindState __state, MethodBase __originalMethod)
	{
		__state = null;
		if (unit == null)
			return;
		if (!IsCurrentHomm3RecruitmentCity())
			return;
		var unitSid = ResolveUnitConfigSid(unit);
		if (string.IsNullOrWhiteSpace(unitSid))
			return;
		if (!TryResolveRecruitmentAbilityOwnerSid(__instance, out var customSid))
		{
			if (TryGetCustomRecruitmentSidForCurrentFaction(unitSid, out var ownerlessCustomSid))
				throw new InvalidOperationException("HoMM3 recruitment ability bind reached donor unit config '" + unitSid + "' without owning custom hire-card SID; expected current-faction custom card '" + ownerlessCustomSid + "' in " + FormatMethod(__originalMethod) + ".");
			return;
		}
		if (string.Equals(unitSid, customSid, StringComparison.OrdinalIgnoreCase))
			return;
		if (StrongholdUnitSidMapping.TryGetDonorSid(customSid, out var donorSid) && string.Equals(unitSid, donorSid, StringComparison.OrdinalIgnoreCase))
			throw new InvalidOperationException("HoMM3 recruitment ability bind reached donor unit config '" + unitSid + "' for custom hire card '" + customSid + "' in " + FormatMethod(__originalMethod) + ".");
	}

	private static void PostfixHireUnitAbilitiesBind(HireAbilityBindState __state)
	{
		RestoreHireAbilityBindState(__state);
	}

	private static Exception FinalizerHireUnitAbilitiesBind(Exception __exception, HireAbilityBindState __state)
	{
		RestoreHireAbilityBindState(__state);
		return __exception;
	}

	private static void RestoreHireAbilityBindState(HireAbilityBindState state)
	{
		if (state == null)
			return;
		if (state.Unit == null)
			return;
		TrySetFirstMemberValue(state.Unit, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigFields, state.OldLogic);
		TrySetFirstMemberValue(state.Unit, GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigFields, state.OldView);
		state.Unit = null;
	}

	private static string ResolveUnitConfigSid(Unit unit)
	{
		var logic = TryGetFirstMemberValue(unit, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigFields);
		var sid = TryGetStringMember(logic, "id");
		if (!string.IsNullOrWhiteSpace(sid))
			return sid;
		var view = TryGetFirstMemberValue(unit, GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigFields);
		sid = TryGetStringMember(view, "id");
		if (!string.IsNullOrWhiteSpace(sid))
			return sid;
		var transfer = TryGetFirstMemberValue(unit, GameSymbols.BattleUi.UnitTransferFields);
		return TryGetStringMember(transfer, "configSid")
		       ?? TryGetStringMember(transfer, "sid")
		       ?? TryGetStringMember(transfer, "id");
	}

	private static bool TryResolveUnitConfigs(string sid, out UnitLogicConfig logic, out UnitViewConfig view)
	{
		logic = null;
		view = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var rootType = FindFirstRuntimeType(GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		var root = TryGetFirstStaticMemberValue(rootType, GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers);
		if (root == null)
			return false;
		var logicTable = TryGetFirstMemberValue(root, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigTables);
		var viewTable = TryGetFirstMemberValue(root, GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigTables);
		return TryLookupConfigBySid(logicTable, sid.Trim(), out logic)
		       && TryLookupConfigBySid(viewTable, sid.Trim(), out view)
		       && logic != null
		       && view != null;
	}

	private static bool TryLookupConfigBySid<T>(object table, string sid, out T value) where T : class
	{
		value = null;
		if (table == null || string.IsNullOrWhiteSpace(sid))
			return false;
		try
		{
			var method = FindMethodByNames(table.GetType(), GameSymbols.UnitPreviewAbilityIcons.ConfigTableTryGet.NameHints, 2);
			if (method == null)
				return false;
			var args = new object[] { sid, null };
			if (!(method.Invoke(table, args) is bool found) || !found)
				return false;
			value = args[1] as T;
			return value != null;
		}
		catch (Exception ex)
		{
			if (_loggedHireAbilityRebind < 16)
			{
				_loggedHireAbilityRebind++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: hire ability config lookup failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}
	private static List<HireAbilityBindConfig> BuildHireAbilityCustomBindConfigs(UnitLogicConfig customLogicConfig, UnitViewConfig customViewConfig)
	{
		var result = new List<HireAbilityBindConfig>();
		foreach (EAbilityType type in Enum.GetValues(typeof(EAbilityType)))
		{
			if (string.Equals(type.ToString(), "All", StringComparison.Ordinal))
				continue;
			AppendHireAbilityCustomBindConfigs(result, customLogicConfig, customViewConfig, type);
		}
		return result;
	}

	private static void AppendHireAbilityCustomBindConfigs(List<HireAbilityBindConfig> target, UnitLogicConfig customLogicConfig, UnitViewConfig customViewConfig, EAbilityType type)
	{
		if (target == null || customLogicConfig == null || customViewConfig == null)
			return;
		var customLogicArray = InvokeHireAbilityLogicArray(customLogicConfig, type);
		var customViewArray = InvokeHireAbilityViewArray(customViewConfig, type);
		var logicLength = customLogicArray != null ? customLogicArray.Length : 0;
		var viewLength = customViewArray != null ? customViewArray.Length : 0;
		if (logicLength == 0 && viewLength == 0)
			return;
		if (logicLength != viewLength)
			throw new InvalidOperationException("Recruitment custom ability logic/view count mismatch for " + type + ": logic=" + logicLength + " view=" + viewLength);
		for (var i = 0; i < logicLength; i++)
		{
			var customLogic = customLogicArray.GetValue(i) as AbilityLogicConfig;
			var customView = InvokeHireAbilityViewAt(customViewConfig, type, i)
			                 ?? (i < customViewArray.Length ? customViewArray.GetValue(i) as AbilityViewConfig : null);
			if (customLogic == null)
				throw new InvalidOperationException("Recruitment custom ability logic missing for " + type + " index=" + i);
			if (customView == null)
				throw new InvalidOperationException("Recruitment custom ability view missing for " + type + " index=" + i);
			if (target.Exists(existing => ReferenceEquals(existing.Logic, customLogic) || ReferenceEquals(existing.View, customView)))
				continue;
			target.Add(new HireAbilityBindConfig { Logic = customLogic, View = customView });
		}
	}

	private static Array InvokeHireAbilityLogicArray(UnitLogicConfig config, EAbilityType type)
	{
		if (config == null)
			return null;
		var method = FindHireAbilityLogicArrayMethod(config.GetType());
		if (method == null)
			throw new MissingMethodException(config.GetType().FullName, "UnitLogic ability bucket");
		try { return CoerceHireAbilityConfigArray(method.Invoke(config, new object[] { type }), typeof(AbilityLogicConfig)); }
		catch (Exception ex)
		{
			LogHireAbilityContext("logic-array-failed:" + ex.GetType().Name);
			throw;
		}
	}

	private static MethodInfo FindHireAbilityLogicArrayMethod(Type type)
	{
		if (type == null)
			return null;
		var method = GameMember.FindFirstMethodByNames(type, new[] { typeof(EAbilityType) }, GameSymbols.SelectedUnitHud.UnitLogicAbilityBucket);
		if (IsHireAbilityConfigArrayMethod(method, typeof(AbilityLogicConfig)))
			return method;
		return null;
	}
	private static List<AbilityViewConfig> BuildHireAbilityViewConfigs(UnitViewConfig viewConfig)
	{
		var result = new List<AbilityViewConfig>();
		foreach (EAbilityType type in Enum.GetValues(typeof(EAbilityType)))
		{
			if (string.Equals(type.ToString(), "All", StringComparison.Ordinal))
				continue;
			AppendHireAbilityViewConfigs(result, viewConfig, type);
		}
		return result;
	}

	private static void AppendHireAbilityViewConfigs(List<AbilityViewConfig> target, UnitViewConfig viewConfig, EAbilityType type)
	{
		if (target == null || viewConfig == null)
			return;
		var viewArray = InvokeHireAbilityViewArray(viewConfig, type);
		var length = viewArray != null ? viewArray.Length : 0;
		if (length <= 0)
			return;
		for (var i = 0; i < length; i++)
		{
			var view = InvokeHireAbilityViewAt(viewConfig, type, i)
			           ?? (i < viewArray.Length ? viewArray.GetValue(i) as AbilityViewConfig : null);
			if (view == null)
				continue;
			var key = ResolveStrongholdAbilityIconKey(view);
			if (string.IsNullOrWhiteSpace(key))
				continue;
			if (target.Exists(existing => ReferenceEquals(existing, view)))
				continue;
			target.Add(view);
		}
	}

	private static Array InvokeHireAbilityViewArray(UnitViewConfig config, EAbilityType type)
	{
		if (config == null)
			return null;
		var method = FindHireAbilityViewArrayMethod(config.GetType());
		if (method == null)
			throw new MissingMethodException(config.GetType().FullName, "UnitView ability bucket");
		try { return CoerceHireAbilityConfigArray(method.Invoke(config, new object[] { type }), typeof(AbilityViewConfig)); }
		catch (Exception ex)
		{
			LogHireAbilityContext("ability-array-failed:" + ex.GetType().Name);
			throw;
		}
	}

	private static AbilityViewConfig InvokeHireAbilityViewAt(UnitViewConfig config, EAbilityType type, int index)
	{
		if (config == null)
			return null;
		var method = FindHireAbilityViewAtMethod(config.GetType());
		if (method == null)
			return null;
		try { return method.Invoke(config, new object[] { type, index }) as AbilityViewConfig; }
		catch (Exception ex)
		{
			LogHireAbilityContext("ability-at-failed:" + ex.GetType().Name);
			return null;
		}
	}

	private static MethodInfo FindHireAbilityViewArrayMethod(Type type)
	{
		if (type == null)
			return null;
		var method = GameMember.FindFirstMethodByNames(type, new[] { typeof(EAbilityType) }, GameSymbols.SelectedUnitHud.UnitViewAbilityBucket);
		if (IsHireAbilityConfigArrayMethod(method, typeof(AbilityViewConfig)))
			return method;
		return null;
	}

	private static MethodInfo FindHireAbilityViewAtMethod(Type type)
	{
		if (type == null)
			return null;
		var method = GameMember.FindFirstMethodByNames(type, new[] { typeof(EAbilityType), typeof(int) }, GameSymbols.SelectedUnitHud.UnitViewAbilityAt);
		if (IsHireAbilityViewAtMethod(method))
			return method;
		return null;
	}

	private static bool IsHireAbilityViewAtMethod(MethodInfo method)
	{
		if (method == null || !TypesMatch(method.ReturnType, typeof(AbilityViewConfig)))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 2
		       && TypesMatch(ps[0].ParameterType, typeof(EAbilityType))
		       && ps[1].ParameterType == typeof(int);
	}

	private static bool IsHireAbilityConfigArrayMethod(MethodInfo method, Type elementType)
	{
		if (method == null || elementType == null)
			return false;
		var ps = method.GetParameters();
		return ps.Length == 1
		       && TypesMatch(ps[0].ParameterType, typeof(EAbilityType))
		       && IsHireAbilityArrayLikeReturnType(method.ReturnType, elementType);
	}

	private static bool IsHireAbilityArrayLikeReturnType(Type returnType, Type elementType)
	{
		if (returnType == null || elementType == null)
			return false;
		if (returnType.IsArray)
			return TypesMatch(returnType.GetElementType(), elementType);
		if (!returnType.IsGenericType || !returnType.Name.StartsWith("Il2CppReferenceArray", StringComparison.Ordinal))
			return false;
		var args = returnType.GetGenericArguments();
		return args.Length == 1 && TypesMatch(args[0], elementType);
	}

	private static Array CoerceHireAbilityConfigArray(object value, Type elementType)
	{
		if (value == null || elementType == null)
			return null;
		if (value is Array array)
			return array;
		try
		{
			var lengthProp = value.GetType().GetProperty("Length", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			var getItem = value.GetType().GetMethod("get_Item", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, new[] { typeof(int) }, null);
			if (lengthProp?.GetValue(value) is not int length || length <= 0 || getItem == null)
				return null;
			var result = Array.CreateInstance(elementType, length);
			for (var i = 0; i < length; i++)
				result.SetValue(getItem.Invoke(value, new object[] { i }), i);
			return result;
		}
		catch
		{
			return null;
		}
	}

	private static bool TypesMatch(Type actual, Type expected)
	{
		return GameInteropTypes.TypesMatch(actual, expected);
	}

	private static void LogHireAbilityContext(string reason)
	{
		if (_loggedHireAbilityContext >= 24)
			return;
		_loggedHireAbilityContext++;
		Plugin.LogSource?.LogInfo("Homm3CustomUiIcon: recruitment ability context " + reason + ".");
	}

	private static void LogHireAbilityRebind(string reason, string donorSid, string customSid, MethodBase method)
	{
		if (_loggedHireAbilityRebind >= 16)
			return;
		_loggedHireAbilityRebind++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: hire ability rebind " + reason
			+ " donor='" + (donorSid ?? "(null)")
			+ "' custom='" + (customSid ?? "(null)")
			+ "' via " + FormatMethod(method) + ".");
	}

	private static Exception FinalizerHireUnitModelListStronghold(Exception __exception, object __instance, [HarmonyArgument(0)] object unitSids, MethodBase __originalMethod)
	{
		if (__exception == null)
			return null;
		if (!IsNullReferenceException(__exception))
			return __exception;
		if (!IsCurrentHomm3RecruitmentCity() && !ContainsStrongholdSid(unitSids))
			return __exception;

		if (_loggedHireUnitModelListSuppressed < 10)
		{
			_loggedHireUnitModelListSuppressed++;
			Plugin.LogSource?.LogWarning(
				"Homm3CustomUiIcon: suppressed Stronghold hire model-list NRE in "
				+ FormatMethod(__originalMethod)
				+ "; full recruit panel can continue with UI portrait fallbacks. "
				+ __exception.Message);
		}
		TryApplyToSurface(__instance, null, FormatMethod(__originalMethod) + ".finalizer");
		return null;
	}

	private static bool IsNullReferenceException(Exception exception)
	{
		for (var e = exception; e != null; e = e.InnerException)
		{
			if (e.GetType().Name == "NullReferenceException")
				return true;
		}
		return false;
	}

	private static bool ContainsStrongholdSid(object value)
	{
		if (value == null)
			return false;
		if (value is string s)
			return IsHomm3UnitSid(s);
		if (value is System.Collections.IEnumerable en)
		{
			foreach (var item in en)
			{
				if (item is string itemString && IsHomm3UnitSid(itemString))
					return true;
			}
		}
		return false;
	}

	private static void PrefixRecruitmentIncrementItemSprite(
		object __instance,
		[HarmonyArgument(0)] ref Sprite sprite,
		object[] __args,
		MethodBase __originalMethod)
	{
		if (!IsCurrentHomm3RecruitmentCity())
			return;

		var key = __args != null && __args.Length > 1 ? __args[1] as string : null;
		var sid = NormalizeUnitSid(key) ?? ResolveRecruitmentItemSid(__instance, key, sprite, -1);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		RememberRecruitmentItemSid(__instance, sid);
		if (Homm3ImportVisuals.IsOwnedSkinnedUnitSid(sid))
		{
			LogRecruitmentPanelReplace(__instance, sid, sprite, FormatMethod(__originalMethod), "prefix-keep-mesh");
			return;
		}
		if (!TryResolveSprite(sid, out var replacement) || !replacement)
			return;

		sprite = replacement;
		LogRecruitmentPanelReplace(__instance, sid, replacement, FormatMethod(__originalMethod), "prefix");
	}

	private static void PostfixRecruitmentIncrementItemView(object __instance, MethodBase __originalMethod)
	{
		if (!IsCurrentHomm3RecruitmentCity())
			return;
		TryApplyRecruitmentItemView(__instance, -1, FormatMethod(__originalMethod));
	}

	private static void PrefixHireUnitItemInit(object __instance, object[] __args, MethodBase __originalMethod, ref bool __state)
	{
		__state = false;
		if (!IsCurrentHomm3RecruitmentCity() || __instance == null)
			return;
		var index = -1;
		if (__args != null && __args.Length > 1 && __args[1] is int i)
			index = i;
		var sid = ResolveRecruitmentIndexedBaseSid(index);
		if (!string.IsNullOrWhiteSpace(sid))
			RememberRecruitmentItemSid(__instance, sid);
		__state = TryPushOwnedSkinnedRecruitmentPreviewAlias(sid);
	}

	private static void PostfixHireUnitItemInit(object __instance, object[] __args, MethodBase __originalMethod, bool __state)
	{
		if (!IsCurrentHomm3RecruitmentCity())
			return;
		var index = -1;
		if (__args != null && __args.Length > 1 && __args[1] is int i)
			index = i;
		if (__state)
			TryPopOwnedSkinnedRecruitmentPreviewAlias(ResolveRecruitmentIndexedBaseSid(index));
		TryApplyRecruitmentItemView(__instance, index, FormatMethod(__originalMethod));
	}

	private static bool TryPushOwnedSkinnedRecruitmentPreviewAlias(string customSid)
	{
		if (string.IsNullOrWhiteSpace(customSid))
			return false;
		if (!StrongholdUnitSidMapping.TryGetDonorSid(customSid, out var donorSid))
			return false;
		if (!Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(customSid, Plugin.LogSource, out var entry)
		    || !Homm3ImportVisuals.IsOwnedSkinnedBattleEntry(entry))
			return false;
		Homm3ImportUnitPreviewModelHook.PushRecruitmentDonorAlias(donorSid, customSid);
		return true;
	}

	private static void TryPopOwnedSkinnedRecruitmentPreviewAlias(string customSid)
	{
		if (string.IsNullOrWhiteSpace(customSid))
			return;
		if (!StrongholdUnitSidMapping.TryGetDonorSid(customSid, out var donorSid))
			return;
		Homm3ImportUnitPreviewModelHook.PopRecruitmentDonorAlias(donorSid, customSid);
	}

	private static void PostfixCitySpecialRecruitmentPanel(object __instance, MethodBase __originalMethod)
	{
		TryApplyCitySpecialRecruitmentPanel(__instance, FormatMethod(__originalMethod));
	}

	private static void PostfixCityUnitSpecialSelectionShow(
		object __instance,
		object[] __args,
		MethodBase __originalMethod)
	{
		if (!IsCurrentHomm3RecruitmentCity())
			return;
		var set = __args != null && __args.Length > 2 ? __args[2] : null;
		var target = __args != null && __args.Length > 1 ? __args[1] : null;
		TryApplyCityUnitSpecialSelection(__instance, target, set, FormatMethod(__originalMethod));
	}
	private static int FindAbilityViewConfigArgumentIndex(object[] args)
	{
		if (args == null)
			return -1;
		for (var i = 0; i < args.Length; i++)
			if (LooksLikeAbilityViewConfig(args[i]))
				return i;
		return -1;
	}

	private static bool LooksLikeHireAbilityWrapper(object candidate)
	{
		if (candidate == null || LooksLikeAbilityViewConfig(candidate))
			return false;
		if (TryNormalizeHireAbilityWrapper(candidate, out _))
			return true;
		var typeName = candidate.GetType().FullName ?? candidate.GetType().Name ?? string.Empty;
		foreach (var wrapperTypeName in GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperTypeNames)
		{
			if (string.Equals(typeName, wrapperTypeName, StringComparison.Ordinal)
			    || typeName.EndsWith("." + wrapperTypeName, StringComparison.Ordinal))
				return true;
		}
		return TryGetFirstMemberValue(candidate, GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperLogicFields) is AbilityLogicConfig
		       || FindMethodByNames(candidate.GetType(), GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperClone.NameHints, 0) != null;
	}
	private static object CreateCustomHireAbilityWrapper(object donorAbility, AbilityLogicConfig customLogic)
	{
		if (donorAbility == null || customLogic == null)
			return null;
		if (!TryNormalizeHireAbilityWrapper(donorAbility, out var typedDonor))
			return null;
		foreach (var cloneMethod in EnumerateHireAbilityWrapperCloneMethods(typedDonor.GetType()))
		{
			object clone;
			try
			{
				clone = cloneMethod.Invoke(typedDonor, Array.Empty<object>());
			}
			catch (Exception ex)
			{
				if (_loggedRecruitmentWrapperCloneFailure < 12)
				{
					_loggedRecruitmentWrapperCloneFailure++;
					Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: recruitment wrapper clone failed via '" + cloneMethod.Name + "': " + ex.GetType().Name + ": " + ex.Message);
				}
				continue;
			}
			if (clone == null)
				continue;
			if (!TryNormalizeHireAbilityWrapper(clone, out clone))
				continue;
			if (TrySetFirstMemberValue(clone, GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperLogicFields, customLogic))
				return clone;
		}
		return null;
	}

	private static IEnumerable<MethodInfo> EnumerateHireAbilityWrapperCloneMethods(Type type)
	{
		if (type == null)
			yield break;
		var hints = GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperClone.NameHints ?? Array.Empty<string>();
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method.IsStatic || method.IsConstructor || method.GetParameters().Length != 0)
				continue;
			if (!ReferenceEquals(method.ReturnType, type) && !string.Equals(method.ReturnType.FullName, type.FullName, StringComparison.Ordinal))
				continue;
			if (Array.IndexOf(hints, method.Name) < 0)
				continue;
			yield return method;
		}
	}
	private static void PostfixAbilityConfigArg0Surface(object __instance, [HarmonyArgument(0)] object abilityViewConfig, object[] __args, MethodBase __originalMethod)
	{
		TryApplyAbilityConfigToSurface(__instance, ResolveAbilityViewConfigArgument(abilityViewConfig, __args), FormatMethod(__originalMethod));
	}

	private static void PostfixAbilityConfigArg1Surface(object __instance, [HarmonyArgument(1)] object abilityViewConfig, object[] __args, MethodBase __originalMethod)
	{
		TryApplyAbilityConfigToSurface(__instance, ResolveAbilityViewConfigArgument(abilityViewConfig, __args), FormatMethod(__originalMethod));
	}

	private static void PostfixNoArgSurfaceDiag(object __instance, MethodBase __originalMethod)
	{
		LogSurfaceDiag(__instance, null, FormatMethod(__originalMethod), "postfix fired");
	}

	private static void PostfixCityUiElementInit(object __instance, [HarmonyArgument(0)] object city, MethodBase __originalMethod)
	{
		TryApplyCityUiElement(__instance, city, FormatMethod(__originalMethod));
		TryApplyAllCityUiElements(FormatMethod(__originalMethod) + ".sweep");
	}

	private static void PostfixCityUiElementRefresh(object __instance, MethodBase __originalMethod)
	{
		TryApplyCityUiElement(__instance, null, FormatMethod(__originalMethod));
	}

	private static void PostfixBuildingTooltipFromCity(
		object __instance,
		object[] __args,
		MethodBase __originalMethod)
	{
		var buildingView = ResolveBuildingViewFromArgsOrTooltip(__instance, __args);
		var building = ResolveBuildingFromArgsOrView(__instance, __args);
		var level = ResolveBuildingLevelFromArgsOrView(__instance, __args);
		TryApplyBuildingTooltip(__instance, buildingView, building, level, FormatMethod(__originalMethod));
	}

	private static void PostfixBuildingTooltipFromView(
		object __instance,
		object[] __args,
		MethodBase __originalMethod)
	{
		var buildingView = ResolveBuildingViewFromArgsOrTooltip(__instance, __args);
		var building = ResolveBuildingFromArgsOrView(__instance, __args);
		var level = ResolveBuildingLevelFromArgsOrView(__instance, __args);
		TryApplyBuildingTooltip(__instance, buildingView, building, level, FormatMethod(__originalMethod));
	}

	private static void PostfixBuildingViewBind(
		object __instance,
		object[] __args,
		MethodBase __originalMethod)
	{
		try
		{
			ModActions.RememberReleaseTownUiCityWrapperFromBuildingViewBind(
				__args != null && __args.Length > 0 ? __args[0] : null,
				__originalMethod);
			var building = ResolveBuildingFromArgsOrView(__instance, __args);
			var level = ResolveBuildingLevelFromArgsOrView(__instance, __args);
			var source = FormatMethod(__originalMethod);
			LogBuildingViewBindProbe(__instance, building, level, source);
			RememberTownLayerBuildingData(__args != null && __args.Length > 0 ? __args[0] : null, building, source);
			TryApplyBuildingView(__instance, building, level, source);
		}
		catch (Exception ex)
		{
			if (_loggedBuildingIconProbe < 20)
			{
				_loggedBuildingIconProbe++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: building view postfix failed on " + FormatMethod(__originalMethod) + ": " + ex.Message);
			}
		}
	}

	private static void RememberTownLayerBuildingData(object townContext, object building, string source)
	{
		try
		{
			var data = ResolveBuildingModelData(building) as BuildingData;
			if (data == null)
				return;
			Homm3StrongholdTownLayers.RememberObservedBuildingData(ModActions.GetCurrentCityFraction(), townContext, data, source);
		}
		catch (Exception ex)
		{
			if (_loggedBuildingIconProbe < 80 && Homm3DiagnosticFlags.IsEnabled("homm3_town_layers_diag.flag"))
			{
				_loggedBuildingIconProbe++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: town layer building data observe failed: " + ex.Message);
			}
		}
	}

	private static void PostfixTooltipUnitsView(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!IsCurrentHomm3RecruitmentCity())
			return;
		try
		{
			var level = ResolveBuildingLevelFromArgsOrView(null, __args);
			var building = ResolveBuildingFromArgsOrView(null, __args);
			var sids = ResolveBuildingHireUnitSids(building, level, FormatMethod(__originalMethod) + ".unitViews");
			if (sids.Count > 0)
				RememberTooltipUnitSids(__instance, sids);

			if (sids.Count > 0)
				TryApplyRecruitmentItemList(TryGetMemberValue(__instance, "unitViews"), sids, FormatMethod(__originalMethod) + ".unitViews");
			else
				ClearTooltipUnitViews(__instance, FormatMethod(__originalMethod) + ".unitViews.unresolved");
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentPanelReplace < 10)
			{
				_loggedRecruitmentPanelReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: tooltip units portrait fallback failed: " + ex.Message);
			}
		}
	}

	private static void PostfixBattleResultIconProbe(object __instance, MethodBase __originalMethod)
	{
		if (__instance is not Component component || !component)
			return;
		LogIconImageHierarchy(component, "battle result " + FormatMethod(__originalMethod), 18, ref _loggedBattleResultIconProbe, 120);
	}

	private static void PostfixHeroStatRewardNotification(object __instance, MethodBase __originalMethod)
	{
		TryApplyStrongholdHallRewardNotification(__instance, FormatMethod(__originalMethod));
	}

	private static void PostfixHeroStatRewardNotificationHidden(object __instance, MethodBase __originalMethod)
	{
		TryRestoreCityInputAfterHeroStatReward(__instance, FormatMethod(__originalMethod));
	}

	private static void PostfixBattleAbilityViewBind(BhUnitAbilityView __instance, object __0, bool __1, MethodBase __originalMethod)
	{
		try
		{
			var ability = TryGetReleaseAbility(__0) ?? TryGetReleaseAbility(__instance);
			var abilityViewConfig = TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields);
			var iconKey = ResolveStrongholdAbilityIconKey(abilityViewConfig);
			if (!IsBattleAbilityCustomIconKey(iconKey))
			{
				ClearBattleAbilityIconOverlay(__instance);
				TryApplyBattleAbilityFocusMarkersRelease(__instance, ability);
				return;
			}
			if (!TryResolveSprite(iconKey, out var sprite) || !sprite)
			{
				ClearBattleAbilityIconOverlay(__instance);
				TryApplyBattleAbilityFocusMarkersRelease(__instance, ability);
				return;
			}

			if (TryApplyBattleAbilityIcon(__instance, iconKey, sprite, FormatMethod(__originalMethod)))
				LogBattleAbilityReplace(__instance, iconKey, sprite);
			TryApplyBattleAbilityFocusMarkersRelease(__instance, ability);
		}
		catch (Exception ex)
		{
			if (_loggedBattleAbilityReplace < 8)
			{
				_loggedBattleAbilityReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: battle ability icon fallback failed: " + ex.Message);
			}
		}
	}

	private static void PrefixBattleAbilityViewBindRelease(BhUnitAbilityView __instance)
	{
		if (!HasRememberedBattleAbilityIconReplacement(__instance))
		{
			ClearBattleAbilityIconOverlay(__instance);
			ClearBattleAbilityIconReplacement(__instance);
		}
	}

	private static void PostfixBattleAbilityViewBindRelease(BhUnitAbilityView __instance, object __0, bool __1, MethodBase __originalMethod)
	{
		try
		{
			var ability = TryGetReleaseAbility(__0) ?? TryGetReleaseAbility(__instance);
			Homm3ImportBhSelectedUnitHudFix.RememberReleaseAbilityViewAbility(__instance, ability);
			var source = FormatMethod(__originalMethod);
			RefreshBattleAbilityIconRelease(__instance, ability, source);
		}
		catch (Exception ex)
		{
			if (_loggedBattleAbilityReplace < 8)
			{
				_loggedBattleAbilityReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: release battle ability icon fallback failed: " + ex.Message);
			}
		}
	}

	internal static void RefreshBattleAbilityIconsIn(Component root)
	{
		if (!root)
			return;
		try
		{
			var views = root.GetComponentsInChildren<BhUnitAbilityView>(true);
			for (var i = 0; i < views.Length; i++)
				RefreshBattleAbilityIconRelease(views[i], null, "selected-hud-controls-refresh");
		}
		catch (Exception ex)
		{
			if (_loggedBattleAbilityReplace < 8)
			{
				_loggedBattleAbilityReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: release battle ability icon refresh failed: " + ex.Message);
			}
		}
	}

	internal static void ClearBattleAbilityIconsIn(Component root)
	{
		if (!root)
			return;
		try
		{
			var views = root.GetComponentsInChildren<BhUnitAbilityView>(true);
			for (var i = 0; i < views.Length; i++)
			{
				ClearBattleAbilityIconOverlay(views[i]);
				ClearBattleAbilityIconReplacement(views[i]);
			}
		}
		catch (Exception ex)
		{
			if (_loggedBattleAbilityReplace < 8)
			{
				_loggedBattleAbilityReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: release battle ability icon clear failed: " + ex.Message);
			}
		}
	}

	private static void RefreshBattleAbilityIconRelease(BhUnitAbilityView view, object abilityHint, string source)
	{
		if (!view)
			return;
		var ability = abilityHint ?? TryGetReleaseAbility(view);
		var abilityViewConfig = TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields);
		var iconKey = ResolveStrongholdAbilityIconKey(abilityViewConfig);
		if (!IsBattleAbilityCustomIconKey(iconKey))
		{
			ClearBattleAbilityIconOverlay(view);
			ClearBattleAbilityIconReplacement(view);
			ForgetBattleAbilityIconReplacement(view);
			TryApplyBattleAbilityFocusMarkersRelease(view, ability);
			return;
		}
		LogBattleAbilityBinderHit(view, ability, source + ".refresh");
		if (!TryResolveSprite(iconKey, out var sprite) || !sprite)
		{
			ClearBattleAbilityIconOverlay(view);
			ClearBattleAbilityIconReplacement(view);
			ForgetBattleAbilityIconReplacement(view);
			TryApplyBattleAbilityFocusMarkersRelease(view, ability);
			return;
		}

		if (HasBattleAbilityIconReplacement(view, iconKey, sprite))
		{
			RaiseBattleAbilityOverlayBelowEnergyContainer(view);
			TryApplyBattleAbilityFocusMarkersRelease(view, ability);
			return;
		}

		ClearBattleAbilityIconReplacement(view);
		if (TryApplyBattleAbilityIcon(view, iconKey, sprite, source))
		{
			RememberBattleAbilityIconReplacement(view, iconKey);
			LogBattleAbilityReplace(view, iconKey, sprite);
		}
		TryApplyBattleAbilityFocusMarkersRelease(view, ability);
	}

	private static void TryApplyAllCityUiElements(string source)
	{
		TryApplyAllCityUiElements(source, null, null);
	}

	private static void TryApplyAllCityUiElements(string source, string knownKey, Sprite knownSprite)
	{
		MonoBehaviour[] objects;
		try { objects = Resources.FindObjectsOfTypeAll<MonoBehaviour>(); }
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: city HUD sweep failed: " + ex.Message);
			return;
		}

		for (var i = 0; i < objects.Length; i++)
		{
			var obj = objects[i];
			if (obj && string.Equals(obj.GetType().FullName, "Hex.Session.Hud.BhCityUIElement", StringComparison.Ordinal))
				TryApplyCityUiElement(obj, null, source, knownKey, knownSprite);
		}
	}

	private static void TryApplyAbilityConfigToSurface(object view, object abilityViewConfig, string source)
	{
		var originalAbilityViewConfig = abilityViewConfig;
		var iconKey = ResolveStrongholdAbilityIconKey(abilityViewConfig);
		var configName = TryGetStringMember(abilityViewConfig, "name")
		                 ?? TryGetStringMember(abilityViewConfig, "name_");
		var originalConfigName = ReferenceEquals(originalAbilityViewConfig, abilityViewConfig)
			? null
			: TryGetStringMember(originalAbilityViewConfig, "name") ?? TryGetStringMember(originalAbilityViewConfig, "name_");
		var component = view as Component;
		Homm3UiCardDiagnostics.Log(
			"unit-preview-ability-icons",
			"preview-ability-icon-binder-hit",
			"source='" + (source ?? "?")
			+ "' view='" + (component ? component.name + "/" + (component.GetType().FullName ?? component.GetType().Name) : view?.GetType().FullName ?? "(null)")
			+ "' abilityView='" + (abilityViewConfig?.GetType().FullName ?? "(null)")
			+ "' abilityName='" + (configName ?? "?")
			+ "' originalAbilityName='" + (originalConfigName ?? "?")
			+ "' iconKey='" + (iconKey ?? "?")
			+ "' imageCount=" + CountImages(component),
			limit: 120);
		LogSurfaceDiag(view, iconKey, source, "ability");
		var applied = TryApplyAbilityPreviewIconSurface(view, iconKey, source);
		Homm3UiCardDiagnostics.Log(
			"unit-preview-ability-icons",
			applied ? "preview-ability-icon-applied" : "preview-ability-icon-not-applied",
			"source='" + (source ?? "?")
			+ "' iconKey='" + (iconKey ?? "?")
			+ "' view='" + (component ? component.name : view?.GetType().Name ?? "(null)") + "'",
			limit: 120);
	}
	private static object ResolveAbilityViewConfigArgument(object preferred, object[] args)
	{
		if (LooksLikeAbilityViewConfig(preferred))
			return preferred;
		if (args == null)
			return preferred;
		for (var i = 0; i < args.Length; i++)
		{
			var candidate = args[i];
			if (LooksLikeAbilityViewConfig(candidate))
				return candidate;
		}
		return preferred;
	}

	private static bool LooksLikeAbilityViewConfig(object candidate)
	{
		if (candidate == null)
			return false;
		var configType = ResolveAbilityViewConfigType();
		var type = candidate.GetType();
		if (configType != null && GameInteropTypes.TypesMatch(type, configType))
			return true;
		var typeName = type.FullName ?? type.Name;
		if (string.Equals(typeName, "Hex.Configs.AbilityViewConfig", StringComparison.Ordinal)
		    || typeName.EndsWith(".AbilityViewConfig", StringComparison.Ordinal))
			return true;
		var icon = TryGetStringMember(candidate, "icon");
		if (!string.IsNullOrWhiteSpace(icon))
			return true;
		var name = TryGetStringMember(candidate, "name") ?? TryGetStringMember(candidate, "name_");
		return !string.IsNullOrWhiteSpace(name) && !typeName.StartsWith("ObjectPublic", StringComparison.Ordinal);
	}

	private static bool TryApplyAbilityPreviewIconSurface(object view, string key, string source)
	{
		if (view == null || string.IsNullOrWhiteSpace(key))
			return false;
		if (!TryResolveSprite(key, out var sprite) || !sprite)
			return false;
		var image = FindNativeAbilityPreviewIconImage(view);
		if (!image)
			return false;
		ApplySpriteToImage(image, sprite);
		LogSurfaceReplace(source, key, sprite, image);
		return true;
	}

	private static Image FindNativeAbilityPreviewIconImage(object view)
	{
		var image = TryGetFirstMemberValue(view, GameSymbols.UnitPreviewAbilityIcons.AbilityViewIconFields) as Image;
		if (!image)
			return null;
		var component = view as Component;
		if (component && image.transform && !image.transform.IsChildOf(component.transform) && image.transform != component.transform)
			return null;
		return image;
	}

	private static void TryApplyBuildingTooltip(object tooltip, object buildingView, object building, int level, string source)
	{
		try
		{
			if (tooltip == null)
				return;
			if (!IsCurrentHomm3BuildingIconCity())
				return;

			var effectiveBuilding = buildingView == null ? building : ResolveBuildingFromView(buildingView);
			var key = effectiveBuilding == null ? null : ResolveHomm3BuildingTooltipIconKey(effectiveBuilding, level);
			if (string.IsNullOrWhiteSpace(key))
			{
				LogBuildingIconProbe(tooltip, building, source, "tooltip no-key");
				return;
			}
			var hireSids = effectiveBuilding == null
				? new List<string>()
				: ResolveBuildingHireUnitSids(effectiveBuilding, level, source + ".unitsView");
			if (hireSids.Count > 0)
			{
				var unitsView = TryGetMemberValue(tooltip, "unitsView");
				RememberTooltipUnitSids(unitsView, hireSids);
				TryApplyRecruitmentItemList(TryGetMemberValue(unitsView, "unitViews"), hireSids, source + ".unitsView");
			}
			if (!TryResolveSprite(key, out var sprite) || !sprite)
			{
				LogBuildingTooltip(tooltip, key, null, source, "no-sprite");
				return;
			}

			var image = TryGetMemberValue(tooltip, "buildingBp") as Image;
			if (!image && tooltip is Component component)
				image = FindNamedImage(component, "buildingBp") ?? FindBestImage(component);
			if (!image)
			{
				LogBuildingTooltip(tooltip, key, sprite, source, "no-image");
				if (tooltip is Component componentForProbe)
					LogIconImageHierarchy(componentForProbe, "building tooltip no-image " + source, 8, ref _loggedBuildingIconProbe, 80);
				return;
			}

			ApplySpriteToImage(image, sprite);
			LogBuildingTooltip(tooltip, key, sprite, source, "replaced");
		}
		catch (Exception ex)
		{
			if (_loggedBuildingTooltipReplace < 10)
			{
				_loggedBuildingTooltipReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: building tooltip art fallback failed: " + ex.Message);
			}
		}
	}

	private static object TryGetReleaseAbility(object wrapper)
	{
		if (wrapper == null)
			return null;
		foreach (var methodName in GameSymbols.SelectedUnitHud.AbilityWrapperTryGetAbility.NameHints)
		{
			var ability = TryInvokeReleaseAbilityOut(wrapper, methodName);
			if (ability != null)
				return ability;
		}
		return null;
	}

	private static object TryGetReleaseAbility(BhUnitAbilityView view)
	{
		if (view == null)
			return null;
		return TryGetFirstMemberValue(view, GameSymbols.SelectedUnitHud.AbilityViewAbilityFields)
			?? TryGetReleaseAbility(TryGetFirstMemberValue(view, GameSymbols.SelectedUnitHud.AbilityViewWrapperFields));
	}

	private static object TryInvokeReleaseAbilityOut(object wrapper, string methodName)
	{
		if (wrapper == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		try
		{
			var method = FindMethodByName(wrapper.GetType(), methodName, 1);
			if (method == null)
				return null;
			var args = new object[] { null };
			var result = method.Invoke(wrapper, args);
			if (result is not bool ok || !ok)
				return null;
			var ability = args[0];
			return LooksLikeReleaseAbility(ability) ? ability : null;
		}
		catch
		{
			return null;
		}
	}

	private static bool LooksLikeReleaseAbility(object ability)
	{
		if (ability == null)
			return false;
		var typeName = ability.GetType().Name;
		if (string.Equals(typeName, "dxs", StringComparison.Ordinal))
			return true;
		return TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields) != null
		       || TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityLogicFields) != null;
	}

	private static void TryApplyBuildingView(object view, object building, int level, string source)
	{
		if (view == null)
			return;
		try
		{
			if (!IsCurrentHomm3BuildingIconCity())
			{
				LogBuildingViewEarlyReturn(view, building, level, source, "not-custom-city");
				return;
			}

			var key = building == null ? null : ResolveHomm3BuildingTooltipIconKey(building, level);
			if (string.IsNullOrWhiteSpace(key) && building != null)
			{
				ForgetBuildingViewIconKey(view);
				LogBuildingViewEarlyReturn(view, building, level, source, "no-key");
				return;
			}
			if (string.IsNullOrWhiteSpace(key))
				key = RecallBuildingViewIconKey(view);
			if (string.IsNullOrWhiteSpace(key))
			{
				LogBuildingViewEarlyReturn(view, building, level, source, building == null ? "no-building" : "no-key");
				return;
			}
			if (!Homm3StrongholdBuildingIconSpriteCache.TryGetOrCreateSprite(key, out var sprite) || !sprite)
			{
				LogBuildingViewEarlyReturn(view, building, level, source, "no-sprite:" + key);
				LogBuildingView(view, key, null, source, "no-sprite");
				return;
			}

			var applied = 0;
			var icons = TryGetMemberValue(view, "icon");
			foreach (var item in EnumerateIl2CppList(icons))
			{
				if (item is not Image image || !image)
					continue;
				ApplySpriteToImage(image, sprite);
				applied++;
			}

			var overlayObject = TryGetMemberValue(view, "overlayIcon") as GameObject;
			var overlayImage = overlayObject ? overlayObject.GetComponent<Image>() ?? overlayObject.GetComponentInChildren<Image>(true) : null;
			if (overlayImage)
			{
				ApplySpriteToImage(overlayImage, sprite);
				applied++;
			}

			if (applied == 0 && view is Component component)
			{
				var image = FindNamedImage(component, "PIC") ?? FindNamedImage(component, "icon") ?? FindBestImage(component);
				if (image)
				{
					ApplySpriteToImage(image, sprite);
					applied++;
				}
			}

			RememberBuildingViewIconKey(view, key);
			LogBuildingView(view, key, sprite, source, applied > 0 ? "replaced:" + applied : "no-image");
			if (applied > 0 && view is Component componentForSuccessProbe)
				LogBuildingViewSuccessHierarchy(componentForSuccessProbe, key, source, applied);
			if (applied == 0 && view is Component componentForProbe)
			{
				LogBuildingViewEarlyReturn(view, building, level, source, "no-image:" + key);
				LogIconImageHierarchy(componentForProbe, "building view no-image " + source, 12, ref _loggedBuildingIconProbe, 80);
			}
		}
		catch (Exception ex)
		{
			if (_loggedBuildingViewReplace < 10)
			{
				_loggedBuildingViewReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: building view art fallback failed: " + ex.Message);
			}
		}
	}

	private static void TryApplyCitySpecialRecruitmentPanel(object view, string source)
	{
		if (view == null || !IsCurrentHomm3RecruitmentCity())
			return;
		try
		{
			var applied = 0;
			var baseSids = GetRecruitmentBaseSidsForCurrentFaction();
			var eightUnitStrip = UsesEightUnitCitySpecialRecruitmentStrip(baseSids);
			foreach (var fieldName in GameSymbols.ReleaseTownUi.CitySpecialRecruitmentItemLists)
			{
				var list = TryGetMemberValue(view, fieldName);
				var explicitSids = ResolveCitySpecialRecruitmentListSids(fieldName, baseSids);
				applied += explicitSids != null
					? TryApplyRecruitmentItemList(list, explicitSids, source + "." + fieldName, hideExtraViews: eightUnitStrip)
					: TryApplyRecruitmentItemList(list, source + "." + fieldName);
			}
			if (eightUnitStrip && view is Component layoutRoot)
				TryApplyEightUnitRecruitmentStripLayout(layoutRoot, baseSids);
			if (applied == 0 && view is Component component)
			{
				var itemViews = component.GetComponentsInChildren<MonoBehaviour>(true);
				var index = 0;
				for (var i = 0; i < itemViews.Length; i++)
				{
					var item = itemViews[i];
					if (!item || !ContainsIgnoreCase(item.GetType().FullName, "BhCityHireIncrementItemView"))
						continue;
					if (TryApplyRecruitmentItemView(item, index, source + ".children"))
						applied++;
					index++;
				}
			}
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentPanelReplace < 10)
			{
				_loggedRecruitmentPanelReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: recruitment panel icon fallback failed: " + ex.Message);
			}
		}
	}

	private static bool UsesEightUnitCitySpecialRecruitmentStrip(string[] baseSids)
	{
		return baseSids != null && baseSids.Length > 7;
	}

	private static IReadOnlyList<string> ResolveCitySpecialRecruitmentListSids(string fieldName, string[] baseSids)
	{
		if (baseSids == null || baseSids.Length == 0 || string.IsNullOrWhiteSpace(fieldName))
			return null;
		if (GameSymbols.ReleaseTownUi.IsCitySpecialTopRecruitmentItemList(fieldName))
			return SliceRecruitmentSids(baseSids, 0, Math.Min(4, baseSids.Length));
		if (GameSymbols.ReleaseTownUi.IsCitySpecialLow3RecruitmentItemList(fieldName))
			return ResolveCitySpecialLow3RecruitmentSids(baseSids);
		if (GameSymbols.ReleaseTownUi.IsCitySpecialLow4RecruitmentItemList(fieldName))
			return ResolveCitySpecialLow4RecruitmentSids(baseSids);
		return null;
	}

	/// <summary>
	/// Bottom mini-strip row. Factory's additional Gantry line uses the third low slot;
	/// the primary tier-7 line stays off the mini strip (full hire / dwelling only).
	/// </summary>
	private static IReadOnlyList<string> ResolveCitySpecialLow3RecruitmentSids(string[] baseSids)
	{
		if (baseSids.Length <= 4)
			return Array.Empty<string>();
		if (baseSids.Length > 7)
		{
			return new[]
			{
				baseSids[4],
				baseSids[5],
				baseSids[baseSids.Length - 1],
			};
		}
		return SliceRecruitmentSids(baseSids, 4, Math.Min(3, baseSids.Length - 4));
	}

	private static IReadOnlyList<string> ResolveCitySpecialLow4RecruitmentSids(string[] baseSids)
	{
		if (baseSids.Length > 7)
			return Array.Empty<string>();
		if (baseSids.Length <= 4)
			return Array.Empty<string>();
		return SliceRecruitmentSids(baseSids, 4, baseSids.Length - 4);
	}

	private static IReadOnlyList<string> SliceRecruitmentSids(string[] sids, int start, int count)
	{
		if (sids == null || start < 0 || count <= 0 || start >= sids.Length)
			return Array.Empty<string>();
		var length = Math.Min(count, sids.Length - start);
		var result = new string[length];
		Array.Copy(sids, start, result, 0, length);
		return result;
	}

	internal static void TryApplyHireCityView(object view, string source)
	{
		if (view == null || !IsCurrentHomm3RecruitmentCity())
			return;
		try
		{
			var applied = 0;
			applied += TryApplyRecruitmentItemList(TryGetMemberValue(view, "items"), source + ".items", allowIndexedBaseFallback: true);
			if (view is Component component)
			{
				var itemViews = component.GetComponentsInChildren<MonoBehaviour>(false);
				var index = 0;
				for (var i = 0; i < itemViews.Length; i++)
				{
					var item = itemViews[i];
					if (!item || !ContainsIgnoreCase(item.GetType().FullName, "BhHireUnitItemView"))
						continue;
					if (TryApplyRecruitmentItemView(item, index, source + ".children", allowIndexedBaseFallback: true))
						applied++;
					index++;
				}
			}

			if (applied > 0 && _loggedRecruitmentPanelReplace < 10)
			{
				_loggedRecruitmentPanelReplace++;
				Plugin.LogSource?.LogInfo("Homm3CustomUiIcon: refreshed full recruitment hire view cards=" + applied + " source=" + source + ".");
			}
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentPanelReplace < 10)
			{
				_loggedRecruitmentPanelReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: full recruitment hire view fallback failed: " + ex.Message);
			}
		}
	}

	private static int TryApplyRecruitmentItemList(object list, string source, bool allowIndexedBaseFallback = false)
	{
		var applied = 0;
		var index = 0;
		foreach (var item in EnumerateIl2CppList(list))
		{
			if (TryApplyRecruitmentItemView(item, index, source, allowIndexedBaseFallback: allowIndexedBaseFallback))
				applied++;
			index++;
		}
		return applied;
	}

	private static int TryApplyRecruitmentItemList(object list, IReadOnlyList<string> explicitSids, string source, bool hideExtraViews = false)
	{
		if (explicitSids == null)
			return TryApplyRecruitmentItemList(list, source);
		if (explicitSids.Count == 0)
		{
			if (!hideExtraViews)
				return TryApplyRecruitmentItemList(list, source);
			var hiddenIndex = 0;
			foreach (var item in EnumerateIl2CppList(list))
			{
				TryHideRecruitmentItemView(item, hiddenIndex, source + ".empty", deactivateView: true);
				hiddenIndex++;
			}
			return 0;
		}

		var applied = 0;
		var index = 0;
		foreach (var item in EnumerateIl2CppList(list))
		{
			if (index < explicitSids.Count && !string.IsNullOrWhiteSpace(NormalizeUnitSid(explicitSids[index])))
			{
				if (TryApplyRecruitmentItemView(item, index, source, explicitSids[index]))
					applied++;
			}
			else
			{
				TryHideRecruitmentItemView(item, index, source + ".extra", deactivateView: hideExtraViews);
			}
			index++;
		}
		return applied;
	}

	private static void ClearTooltipUnitViews(object tooltipUnitsView, string source)
	{
		var list = TryGetMemberValue(tooltipUnitsView, "unitViews");
		var index = 0;
		foreach (var item in EnumerateIl2CppList(list))
		{
			TryHideRecruitmentItemView(item, index, source);
			index++;
		}
	}

	private static void TryApplyCityUnitSpecialSelection(object selection, object target, object set, string source)
	{
		try
		{
			var sids = ResolveRecruitmentSelectionSids(target, set);
			var list = TryGetMemberValue(selection, "items");
			var index = 0;
			foreach (var item in EnumerateIl2CppList(list))
			{
				if (sids.Count == 0)
					return;
				if (index >= sids.Count)
					break;
				if (index < sids.Count)
					RememberRecruitmentItemSid(item, sids[index]);
				TryApplyRecruitmentItemView(item, -1, source + ".items");
				index++;
			}
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentPanelReplace < 10)
			{
				_loggedRecruitmentPanelReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: recruitment popover icon fallback failed: " + ex.Message);
			}
		}
	}

	private static List<string> ResolveRecruitmentSelectionSids(object target, object set)
	{
		var result = new List<string>();
		var targetImage = TryGetMemberValue(target, "pic") as Image;
		var targetSid = RecallRecruitmentItemSid(target)
			?? ResolveRecruitmentItemSid(target, null, targetImage ? targetImage.sprite : null, -1);
		var targetGroup = ResolveRecruitmentUpgradeGroup(targetSid);
		if (targetGroup.Count > 0)
		{
			LogRecruitmentPullupDiag("target-upgrade-group", target, -1, "selection", targetSid, targetImage, "group='" + string.Join(",", targetGroup) + "'");
			return targetGroup;
		}

		foreach (var value in EnumerateStringList(TryGetFirstRecruitmentSelectionSidList(set)))
		{
			var sid = NormalizeUnitSid(value);
			if (!string.IsNullOrWhiteSpace(sid))
				result.Add(sid);
		}
		if (result.Count > 0)
		{
			LogRecruitmentPullupDiag("set-list", target, -1, "selection", targetSid, targetImage, "sids='" + string.Join(",", result) + "'");
			return result;
		}

		if (!string.IsNullOrWhiteSpace(targetSid))
			result.Add(targetSid);
		LogRecruitmentPullupDiag(
			result.Count > 0 ? "target-single" : "unresolved",
			target,
			-1,
			"selection",
			targetSid,
			targetImage,
			"set='" + FormatObject(set) + "'");
		return result;
	}

	private static object TryGetFirstRecruitmentSelectionSidList(object set)
	{
		var value = TryGetFirstFieldValue(set, GameSymbols.ReleaseTownUi.RecruitmentSelectionSidListFields);
		if (value != null)
			return value;
		for (var i = 0; i < GameSymbols.ReleaseTownUi.RecruitmentSelectionSidListMethods.Length; i++)
		{
			value = TryInvokeNoArg(set, GameSymbols.ReleaseTownUi.RecruitmentSelectionSidListMethods[i]);
			if (value != null)
				return value;
		}
		if (!GameBuild.IsGolden)
		{
			// Build 25672315: the selection set (native fec) holds no List<String>; the sids sit one hop further,
			// in its Hex.Session.Data.HiredUnitSet member (real-name type, field "sids").
			var hiredUnitSet = TryGetFirstMemberOfTypeName(set, "Hex.Session.Data.HiredUnitSet");
			value = TryGetMemberValue(hiredUnitSet, "sids");
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetFirstMemberOfTypeName(object obj, string typeFullName)
	{
		if (obj == null || string.IsNullOrWhiteSpace(typeFullName))
			return null;
		if (string.Equals(obj.GetType().FullName, typeFullName, StringComparison.Ordinal))
			return obj;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			PropertyInfo[] props;
			try { props = t.GetProperties(flags); }
			catch { continue; }
			foreach (var prop in props)
			{
				// Interop field properties only: prop_ wrappers call native getters.
				if (prop == null || !prop.CanRead || prop.GetIndexParameters().Length != 0
				    || prop.Name.StartsWith("prop_", StringComparison.Ordinal)
				    || !string.Equals(prop.PropertyType.FullName, typeFullName, StringComparison.Ordinal))
					continue;
				try
				{
					var value = prop.GetValue(obj);
					if (value != null)
						return value;
				}
				catch { }
			}
		}
		return null;
	}

	private static List<string> ResolveRecruitmentUpgradeGroup(string sid)
	{
		var result = new List<string>();
		if (string.IsNullOrWhiteSpace(sid))
			return result;
		var key = sid.Trim();
		if (key.EndsWith("_upg_alt", StringComparison.Ordinal))
			key = key.Substring(0, key.Length - "_upg_alt".Length);
		else if (key.EndsWith("_upg", StringComparison.Ordinal))
			key = key.Substring(0, key.Length - "_upg".Length);
		if (!IsHomm3UnitSid(key))
			return result;
		result.Add(key);
		result.Add(key + "_upg");
		result.Add(key + "_upg_alt");
		return result;
	}

	private static IEnumerable<string> EnumerateStringList(object list)
	{
		if (list == null)
			yield break;
		var yielded = false;
		if (list is IEnumerable enumerable)
		{
			foreach (var value in enumerable)
			{
				if (value is string s && !string.IsNullOrWhiteSpace(s))
				{
					yielded = true;
					yield return s;
				}
			}
		}
		if (yielded)
			yield break;
		foreach (var value in EnumerateIl2CppList(list))
		{
			if (value is string s && !string.IsNullOrWhiteSpace(s))
				yield return s;
		}
	}

	private static IEnumerable<object> EnumerateObjects(object value)
	{
		if (value == null)
			yield break;
		var yielded = false;
		if (value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
				{
					yielded = true;
					yield return item;
				}
			}
		}
		if (yielded)
			yield break;

		foreach (var item in EnumerateIl2CppList(value))
		{
			yielded = true;
			yield return item;
		}
		if (yielded)
			yield break;
		foreach (var item in EnumerateIl2CppArray(value))
			yield return item;
	}

	private static bool TryApplyRecruitmentItemView(object item, int index, string source, string explicitSid = null, bool allowIndexedBaseFallback = false)
	{
		if (item == null)
			return false;
		var component = item as Component;
		var image = component ? FindRecruitmentItemPortraitImage(component) : null;
		if (!image)
			image = TryGetMemberValue(item, "pic") as Image;
		if (!image && component)
			image = FindNamedImage(component, "pic") ?? FindBestImage(component);
		if (!image)
		{
			LogRecruitmentPullupDiag("no-image", item, index, source, null, null, "");
			return false;
		}

		var rememberedSid = RecallRecruitmentItemSid(item);
		var sid = NormalizeUnitSid(explicitSid)
			?? rememberedSid
			?? ResolveRecruitmentItemSid(item, null, image.sprite, index)
			?? (allowIndexedBaseFallback ? ResolveRecruitmentIndexedBaseSid(index) : null);
		if (string.IsNullOrWhiteSpace(sid))
		{
			LogRecruitmentPullupDiag("no-sid", item, index, source, null, image, "");
			return false;
		}
		if (Homm3ImportVisuals.IsOwnedSkinnedUnitSid(sid))
		{
			RememberRecruitmentItemSid(item, sid);
			LogRecruitmentPullupDiag("owned-skinned-mesh", item, index, source, sid, image, "skip-png");
			return true;
		}
		if (!TryResolveSprite(sid, out var sprite) || !sprite)
		{
			LogRecruitmentPullupDiag("no-sprite", item, index, source, sid, image, "");
			if (!string.IsNullOrWhiteSpace(explicitSid))
				TryHideRecruitmentItemView(item, index, source + ".no-sprite");
			return false;
		}

		ApplySpriteToImage(image, sprite);
		if (component)
		{
			ClearRecruitmentItemStrayRootPortrait(component, image);
			HideHireUnitNativeDonorVisuals(component, sid, source);
			if (UsesEightUnitCitySpecialRecruitmentStrip(GetRecruitmentBaseSidsForCurrentFaction())
			    && ContainsIgnoreCase(component.GetType().FullName, "BhCityHireIncrementItemView"))
				component.gameObject.SetActive(true);
		}
		RememberRecruitmentItemSid(item, sid);
		LogRecruitmentPanelReplace(item, sid, sprite, source, "postfix");
		LogRecruitmentPullupDiag("applied", item, index, source, sid, image, "sprite='" + sprite.name + "'");
		return true;
	}

	private static bool IsFullRecruitmentHireUnitItemView(Component component)
	{
		if (!component)
			return false;
		return IsComponentRuntimeTypeName(component, "Hex.UI.City.BhHireUnitItemView");
	}


	private static bool IsComponentRuntimeTypeName(Component component, string exactTypeName)
	{
		if (!component || string.IsNullOrWhiteSpace(exactTypeName))
			return false;
		try
		{
			var il2CppType = component.GetIl2CppType();
			var typeName = il2CppType != null ? il2CppType.FullName ?? il2CppType.Name ?? string.Empty : string.Empty;
			if (string.Equals(typeName, exactTypeName, StringComparison.Ordinal))
				return true;
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentRuntimeTypeResolveFailure < 12)
			{
				_loggedRecruitmentRuntimeTypeResolveFailure++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: recruitment runtime type read failed for '" + (component ? component.name : "?") + "': " + ex.GetType().Name + ": " + ex.Message);
			}
		}
		return false;
	}
	private static List<int> BuildSiblingIndexPath(Transform transform, Transform stopAt)
	{
		var result = new List<int>();
		var cursor = transform;
		while (cursor && cursor != stopAt)
		{
			result.Add(cursor.GetSiblingIndex());
			cursor = cursor.parent;
		}
		result.Reverse();
		return result;
	}
	private static Type ResolveHireAbilityWrapperType()
	{
		for (var i = 0; i < GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperTypeNames.Length; i++)
		{
			var type = FindRuntimeType(GameSymbols.UnitPreviewAbilityIcons.HireAbilityWrapperTypeNames[i]);
			if (type != null && typeof(Il2CppObjectBase).IsAssignableFrom(type))
				return type;
		}
		return null;
	}

	private static bool TryNormalizeHireAbilityWrapper(object candidate, out object wrapper)
	{
		wrapper = null;
		if (candidate == null || LooksLikeAbilityViewConfig(candidate))
			return false;
		var wrapperType = ResolveHireAbilityWrapperType();
		if (wrapperType == null)
			return false;
		if (wrapperType.IsInstanceOfType(candidate))
		{
			wrapper = candidate;
			return true;
		}
		if (candidate is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;
		try
		{
			foreach (var method in typeof(Il2CppObjectPool).GetMethods(BindingFlags.Public | BindingFlags.Static))
			{
				if (!string.Equals(method.Name, "Get", StringComparison.Ordinal) || !method.IsGenericMethodDefinition)
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 1 || parameters[0].ParameterType != typeof(IntPtr))
					continue;
				var cast = method.MakeGenericMethod(wrapperType).Invoke(null, new object[] { il2Cpp.Pointer });
				if (cast != null && wrapperType.IsInstanceOfType(cast))
				{
					wrapper = cast;
					return true;
				}
			}
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentWrapperNormalizeFailure < 12)
			{
				_loggedRecruitmentWrapperNormalizeFailure++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: recruitment wrapper normalization failed for type='" + (candidate.GetType().FullName ?? candidate.GetType().Name ?? "?") + "': " + ex.GetType().Name + ": " + ex.Message);
			}
		}
		return false;
	}

	private static bool TryInvokeRecruitmentAbilityRowBind(object view, object ability, AbilityViewConfig config)
	{
		if (view == null || ability == null || config == null)
			return false;
		var method = FindMethodByNames(view.GetType(), GameSymbols.UnitPreviewAbilityIcons.AbilityItemPrimaryBind.NameHints, 2)
			?? FindMethodByNames(view.GetType(), GameSymbols.UnitPreviewAbilityIcons.AbilityItemSecondaryBind.NameHints, 2);
		if (method == null)
			return false;
		method.Invoke(view, new[] { ability, config });
		return true;
	}

	private static void TryHideRecruitmentItemView(object item, int index, string source, bool deactivateView = false)
	{
		if (item == null)
			return;
		var key = GetStableObjectKey(item);
		RecruitmentSidByItem.Remove(key);
		var component = item as Component;
		var image = component ? FindRecruitmentItemPortraitImage(component) : null;
		if (!image)
			image = TryGetMemberValue(item, "pic") as Image;
		if (!image && component)
			image = FindNamedImage(component, "pic") ?? FindBestImage(component);
		if (image)
		{
			image.sprite = null;
			image.overrideSprite = null;
			image.enabled = false;
		}
		if (deactivateView && component && component.gameObject)
			component.gameObject.SetActive(false);
		LogRecruitmentPullupDiag("cleared-extra", item, index, source, null, image, "");
	}

	private static void TryApplyEightUnitRecruitmentStripLayout(Component view, string[] baseSids)
	{
		if (view == null || baseSids == null || baseSids.Length <= 7)
			return;
		var specialView = FindRecruitmentStripChildTransform(view.transform, "SPECIAL VIEW");
		if (!specialView)
			return;
		var gameObjectRow = FindRecruitmentStripChildTransform(specialView, "GameObject");
		var lowRow = FindRecruitmentStripChildTransform(specialView, "LowRow");
		if (!gameObjectRow || !lowRow)
			return;

		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL", true);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (1)", true);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (2)", true);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (3)", true);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (4)", false);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (5)", false);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (6)", false);
		SetRecruitmentStripCardActive(gameObjectRow, "UNIT PREVIEW SMALL (7)", false);

		SetRecruitmentStripCardActive(lowRow, "UNIT PREVIEW SMALL (4)", true);
		SetRecruitmentStripCardActive(lowRow, "UNIT PREVIEW SMALL (5)", true);
		SetRecruitmentStripCardActive(lowRow, "UNIT PREVIEW SMALL (6)", true);
	}

	private static Transform FindRecruitmentStripChildTransform(Transform root, string name)
	{
		if (!root || string.IsNullOrWhiteSpace(name))
			return null;
		var children = root.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < children.Length; i++)
		{
			var child = children[i];
			if (child && string.Equals(child.name, name, StringComparison.Ordinal))
				return child;
		}
		return null;
	}

	private static void SetRecruitmentStripCardActive(Transform row, string cardName, bool active)
	{
		if (!row || string.IsNullOrWhiteSpace(cardName))
			return;
		var children = row.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < children.Length; i++)
		{
			var child = children[i];
			if (!child || !string.Equals(child.name, cardName, StringComparison.Ordinal))
				continue;
			if (child.parent != null && child.parent.name.IndexOf("UNIT SELECTION", StringComparison.OrdinalIgnoreCase) >= 0)
				continue;
			child.gameObject.SetActive(active);
		}
	}

	private static Image FindRecruitmentItemPortraitImage(Component root)
	{
		if (!root)
			return null;
		var images = root.GetComponentsInChildren<Image>(true);
		Image best = null;
		var bestScore = int.MinValue;
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image || !image.gameObject)
				continue;
			var score = ScoreRecruitmentItemPortraitImage(root, image);
			if (score <= bestScore)
				continue;
			best = image;
			bestScore = score;
		}
		return bestScore >= 100 ? best : null;
	}

	private static void ClearRecruitmentItemStrayRootPortrait(Component root, Image target)
	{
		if (!root || !target)
			return;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image || image == target || !image.gameObject)
				continue;
			var isRoot = image.transform == root.transform;
			var name = image.gameObject.name ?? "";
			if (!isRoot && name.IndexOf("UNIT PREVIEW SMALL", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			image.sprite = null;
			image.overrideSprite = null;
			var color = image.color;
			if (color.a > 0f)
			{
				color.a = 0f;
				image.color = color;
			}
		}
	}

	private static int ScoreRecruitmentItemPortraitImage(Component root, Image image)
	{
		var name = image.gameObject.name ?? "";
		if (IsRecruitmentItemChromeImageName(name))
			return int.MinValue;
		var path = GetTransformPath(image.transform, root.transform);
		if (IsRecruitmentItemChromePath(path))
			return int.MinValue;

		var score = 0;
		if (string.Equals(name, "Icon", StringComparison.OrdinalIgnoreCase))
			score += 100;
		else if (name.IndexOf("icon", StringComparison.OrdinalIgnoreCase) >= 0
		         || name.IndexOf("pic", StringComparison.OrdinalIgnoreCase) >= 0
		         || name.IndexOf("portrait", StringComparison.OrdinalIgnoreCase) >= 0)
			score += 45;

		var parentName = image.transform && image.transform.parent ? image.transform.parent.gameObject.name ?? "" : "";
		if (string.Equals(parentName, "Mask", StringComparison.OrdinalIgnoreCase))
			score += 65;
		if (path.IndexOf("UNIT ITEM", StringComparison.OrdinalIgnoreCase) >= 0)
			score += 25;
		if (image.enabled)
			score += 10;
		if (image.gameObject.activeInHierarchy)
			score += 10;
		if (image.transform == root.transform)
			score -= 80;
		return score;
	}

	private static bool IsRecruitmentItemChromeImageName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return false;
		return string.Equals(name, "Back", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "BackSelected", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "Frame", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "FrameHover", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "Selected", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "Amount", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "TxtBack", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "WHITE", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(name, "Mask", StringComparison.OrdinalIgnoreCase)
		       || name.IndexOf("UNIT PREVIEW SMALL", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool IsRecruitmentItemChromePath(string path)
	{
		if (string.IsNullOrWhiteSpace(path))
			return false;
		return path.IndexOf("/Back", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/BackSelected", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/Frame", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/FrameHover", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/Selected", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/Amount", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/TxtBack", StringComparison.OrdinalIgnoreCase) >= 0
		       || path.IndexOf("/WHITE", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static string ResolveRecruitmentIndexedBaseSid(int index)
	{
		var baseSids = GetRecruitmentBaseSidsForCurrentFaction();
		return baseSids != null && index >= 0 && index < baseSids.Length ? baseSids[index] : null;
	}

	private static void RememberRecruitmentItemSid(object item, string sid)
	{
		if (item == null || string.IsNullOrWhiteSpace(sid))
			return;
		RecruitmentSidByItem[GetStableObjectKey(item)] = sid.Trim();
	}

	internal static string TryGetRememberedRecruitmentItemSid(object item)
	{
		return RecallRecruitmentItemSid(item);
	}

	private static string RecallRecruitmentItemSid(object item)
	{
		if (item == null)
			return null;
		return RecruitmentSidByItem.TryGetValue(GetStableObjectKey(item), out var sid) ? sid : null;
	}

	private static bool TryResolveRecruitmentAbilityOwnerSid(object abilities, out string sid)
	{
		sid = null;
		var component = abilities as Component;
		if (!component)
			return false;
		var cursor = component.transform;
		while (cursor)
		{
			var components = cursor.GetComponents<Component>();
			for (var i = 0; i < components.Length; i++)
			{
				var owner = components[i];
				if (!owner || !IsFullRecruitmentHireUnitItemView(owner))
					continue;
				sid = RecallRecruitmentItemSid(owner);
				return !string.IsNullOrWhiteSpace(sid);
			}
			cursor = cursor.parent;
		}
		return false;
	}

	private static string ResolveRecruitmentItemSid(object item, string keyOrLabel, Sprite currentSprite, int index)
	{
		var sid = NormalizeUnitSid(keyOrLabel);
		if (!string.IsNullOrWhiteSpace(sid))
			return sid;

		sid = NormalizeUnitSid(currentSprite ? currentSprite.name : null);
		if (!string.IsNullOrWhiteSpace(sid))
			return sid;

		if (currentSprite && TryGetCustomRecruitmentSidForCurrentFaction(currentSprite.name, out sid))
			return sid;

		var image = TryGetMemberValue(item, "pic") as Image;
		var spriteName = image && image.sprite ? image.sprite.name : null;
		if (TryGetCustomRecruitmentSidForCurrentFaction(spriteName, out sid))
			return sid;

		var label = TryGetMemberValue(item, "label");
		sid = NormalizeUnitSid(TryGetStringMember(label, "text") ?? TryGetStringMember(label, "m_text"));
		if (!string.IsNullOrWhiteSpace(sid))
			return sid;

		var baseSids = GetRecruitmentBaseSidsForCurrentFaction();
		if (baseSids != null && index >= 0 && index < baseSids.Length)
			return baseSids[index];
		return null;
	}

	private static string NormalizeUnitSid(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return null;
		var text = value.Trim();
		if (IsHomm3UnitSid(text))
			return text;
		var embeddedSid = ExtractHomm3UnitSidFromPortraitSpriteName(text);
		if (!string.IsNullOrWhiteSpace(embeddedSid))
			return embeddedSid;
		if (TryGetCustomRecruitmentSidForCurrentFaction(text, out var sid))
			return sid;
		return null;
	}

	private static string ExtractHomm3UnitSidFromPortraitSpriteName(string spriteName)
	{
		if (string.IsNullOrWhiteSpace(spriteName))
			return null;
		var text = spriteName.Trim();
		const string staticPrefix = "homm3_static_portrait_";
		if (text.StartsWith(staticPrefix, StringComparison.OrdinalIgnoreCase))
		{
			var sid = text.Substring(staticPrefix.Length);
			return IsHomm3UnitSid(sid) ? sid : null;
		}

		const string animatedPrefix = "homm3_portrait_anim_";
		if (!text.StartsWith(animatedPrefix, StringComparison.OrdinalIgnoreCase))
			return null;
		var candidate = text.Substring(animatedPrefix.Length);
		var lastUnderscore = candidate.LastIndexOf('_');
		if (lastUnderscore > 0)
		{
			var frame = candidate.Substring(lastUnderscore + 1);
			if (int.TryParse(frame, out _))
				candidate = candidate.Substring(0, lastUnderscore);
		}
		return IsHomm3UnitSid(candidate) ? candidate : null;
	}

	private static bool TryGetCustomRecruitmentSidForCurrentFaction(string donorSid, out string customSid)
	{
		return StrongholdUnitSidMapping.TryGetCustomSidForDonorInFaction(
			donorSid,
			ModActions.GetCurrentCityFraction(),
			out customSid);
	}

	private static bool IsCurrentStrongholdCity()
	{
		return string.Equals(ModActions.GetCurrentCityFraction(), "homm3_stronghold", StringComparison.OrdinalIgnoreCase);
	}

	private static bool IsCurrentHomm3BuildingIconCity()
	{
		return Homm3CustomFactionRegistry.IsCustomFactionSid(ModActions.GetCurrentCityFraction());
	}

	private static bool IsCurrentHomm3RecruitmentCity()
	{
		return GetRecruitmentBaseSidsForCurrentFaction() != null;
	}

	private static string[] GetRecruitmentBaseSidsForCurrentFaction()
	{
		return Homm3CustomFactionRegistry.GetRecruitmentBaseSids(ModActions.GetCurrentCityFraction());
	}

	private static void TryApplyStrongholdHallRewardNotification(object notification, string source)
	{
		if (notification == null || !IsCurrentStrongholdCity() || !IsStrongholdHallHeroStatReward(notification))
			return;
		try
		{
			if (notification is Component component && !component.gameObject.activeInHierarchy)
				return;

			var heroSid = ResolveHeroSidFromRewardNotification(notification);
			if (!string.IsNullOrWhiteSpace(heroSid)
			    && Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(heroSid, out var heroSprite)
			    && heroSprite)
			{
				var heroImage = TryGetMemberValue(notification, "iconHero") as Image
					?? (notification is Component c ? FindNamedImage(c, "iconHero") ?? FindNamedImage(c, "PORTRAIT") : null);
				if (heroImage)
					ApplySpriteToImage(heroImage, heroSprite);
			}

			var statImage = TryGetMemberValue(notification, "iconStat") as Image;
			if (statImage && TryFindLoadedSprite("hero_attack_icon", out var attackSprite) && attackSprite)
				ApplySpriteToImage(statImage, attackSprite);

			SetTextMember(notification, "textStats", "Attack +2");
			SetTextMember(notification, "textLevelUp", "Attack +2");
			SetTextMember(notification, "textDescription", "Hall of Valhalla increases the visiting hero's Attack by 2.");

			if (_loggedHeroStatRewardReplace < 8)
			{
				_loggedHeroStatRewardReplace++;
				Plugin.LogSource?.LogInfo(
					"Homm3CustomUiIcon: corrected Stronghold Hall of Valhalla reward notification"
					+ " source=" + source
					+ " heroSid='" + (heroSid ?? "") + "'.");
			}
		}
		catch (Exception ex)
		{
			if (_loggedHeroStatRewardReplace < 8)
			{
				_loggedHeroStatRewardReplace++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: Stronghold Hall reward notification correction failed: " + ex.Message);
			}
		}
	}

	private static void TryRestoreCityInputAfterHeroStatReward(object notification, string source)
	{
		if (notification == null || !IsCurrentStrongholdCity())
			return;
		try
		{
			var screenCanvas = TryGetMemberValue(notification, "canvas") as Canvas;
			var screenGroup = TryGetMemberValue(notification, "cg") as CanvasGroup;
			if (screenCanvas || screenGroup)
			{
				if (screenGroup != null)
				{
					screenGroup.blocksRaycasts = false;
					screenGroup.interactable = false;
				}
				if (screenCanvas != null)
					screenCanvas.enabled = false;
			}
			else if (notification is Component component)
			{
				var groups = component.GetComponentsInChildren<CanvasGroup>(true);
				for (var i = 0; i < groups.Length; i++)
				{
					var group = groups[i];
					if (!group)
						continue;
					group.blocksRaycasts = false;
					group.interactable = false;
				}
			}

			ModActions.EnsureCityMenuCanvasesVisible();
			if (_loggedHeroStatRewardReplace < 8)
			{
				_loggedHeroStatRewardReplace++;
				Plugin.LogSource?.LogInfo("Homm3CustomUiIcon: restored city input after hero-stat reward source=" + source + ".");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3CustomUiIcon: city input restore after hero-stat reward failed: " + ex.Message);
		}
	}

	private static bool IsStrongholdHallHeroStatReward(object notification)
	{
		var bank = TryGetMemberValue(notification, "byzv") ?? TryGetMemberValue(notification, "bonusHeroBank");
		var bankSid = ResolveBuildingSidFromHeroBonusBank(bank);
		if (string.Equals(bankSid, "Build_Gymnasium", StringComparison.Ordinal))
			return true;

		var bonus = TryGetMemberValue(notification, "byzt") ?? TryGetMemberValue(notification, "bonus");
		return IsOffenceTwoHeroStatBonus(bonus);
	}

	private static string ResolveBuildingSidFromHeroBonusBank(object bank)
	{
		if (bank == null)
			return null;
		var direct = NormalizeBuildingSid(TryGetStringMember(bank, "sid")
			?? TryGetStringMember(bank, "cnou")
			?? TryInvokeNoArg(bank, "zzb") as string);
		if (!string.IsNullOrWhiteSpace(direct))
			return direct;

		var config = TryGetMemberValue(bank, "cdtr")
			?? TryGetMemberValue(bank, "config")
			?? TryGetMemberValue(TryGetMemberValue(bank, "cdtb"), "cnvi")
			?? TryGetMemberValue(TryGetMemberValue(bank, "cdtb"), "chpn");
		return NormalizeBuildingSid(TryGetStringMember(config, "sid"));
	}

	private static bool IsOffenceTwoHeroStatBonus(object bonus)
	{
		var config = TryGetMemberValue(bonus, "cbmw") ?? TryGetMemberValue(bonus, "<cbmw>k__BackingField") ?? bonus;
		var type = TryGetStringMember(config, "type") ?? TryGetMemberValue(bonus, "cbmz")?.ToString();
		if (string.IsNullOrWhiteSpace(type) || type.IndexOf("HeroStat", StringComparison.OrdinalIgnoreCase) < 0)
			return false;
		var parameters = TryGetMemberValue(config, "parameters") as string[];
		if (parameters == null || parameters.Length < 2)
			return false;
		return string.Equals(parameters[0], "offence", StringComparison.OrdinalIgnoreCase)
		       && string.Equals(parameters[1], "2", StringComparison.OrdinalIgnoreCase);
	}

	private static string ResolveHeroSidFromRewardNotification(object notification)
	{
		var sessionHero = TryGetMemberValue(notification, "byzu") ?? TryGetMemberValue(notification, "hero");
		return TryExtractHeroSid(sessionHero)
			?? TryExtractHeroSid(TryGetMemberValue(sessionHero, "chys"))
			?? TryExtractHeroSid(TryGetMemberValue(sessionHero, "<chys>k__BackingField"));
	}

	private static string TryExtractHeroSid(object value)
	{
		if (value == null)
			return null;
		foreach (var name in new[] { "configSid", "configId", "sid", "id", "heroSid", "cmyj", "icon" })
		{
			var s = TryGetStringMember(value, name);
			if (!string.IsNullOrWhiteSpace(s) && s.IndexOf("homm3_stronghold_hero_", StringComparison.OrdinalIgnoreCase) >= 0)
				return s.Trim();
		}
		return null;
	}

	private static void SetTextMember(object obj, string memberName, string text)
	{
		var label = TryGetMemberValue(obj, memberName) as TextMeshProUGUI;
		if (label != null)
			label.text = text;
	}

	private static string ResolveBuildingSid(object building, object data = null, object config = null)
	{
		if (building == null && data == null && config == null)
			return null;
		if (data == null)
			data = ResolveBuildingModelData(building);
		if (config == null)
			config = ResolveBuildingDataConfig(data);
		return NormalizeBuildingSid(TryGetFirstStringFieldMember(building, GameSymbols.ReleaseTownUi.BuildingModelSidMembers)
			?? TryGetFirstStringMethod(building, GameSymbols.ReleaseTownUi.BuildingModelSidMethods)
			?? TryGetFirstStringFieldMember(data, GameSymbols.ReleaseTownUi.BuildingDataSidMembers)
			?? TryGetFirstStringBuildingDataAccessor(data)
			?? TryGetFirstStringFieldMember(config, GameSymbols.ReleaseTownUi.BuildingConfigSidMembers));
	}

	private static string ResolveHomm3BuildingTooltipIconKey(object building, int level)
	{
		if (building is string buildingSid)
		{
			var normalized = NormalizeBuildingSid(buildingSid);
			if (string.IsNullOrWhiteSpace(normalized))
				return null;
			return ResolveHomm3BuildingIconKey(normalized, level > 0 ? level : 1);
		}

		var data = ResolveBuildingModelData(building);
		var config = ResolveBuildingDataConfig(data);
		var sid = ResolveBuildingSid(building, data, config);
		if (string.IsNullOrWhiteSpace(sid))
			return null;

		var resolvedLevel = level > 0 ? level : TryGetFirstIntFieldMember(building, GameSymbols.ReleaseTownUi.BuildingModelLevelMembers);
		if (resolvedLevel <= 0)
			resolvedLevel = TryGetFirstIntMethod(building, GameSymbols.ReleaseTownUi.BuildingModelLevelMethods);
		if (resolvedLevel <= 0)
			resolvedLevel = TryGetFirstIntFieldMember(data, GameSymbols.ReleaseTownUi.BuildingDataLevelMembers);
		if (resolvedLevel <= 0)
			resolvedLevel = TryGetFirstIntBuildingDataAccessor(data);
		if (resolvedLevel <= 0)
			resolvedLevel = 1;

		return ResolveHomm3BuildingIconKey(sid, resolvedLevel);
	}

	private static string ResolveHomm3BuildingIconKey(string sid, int level)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var faction = ModActions.GetCurrentCityFraction();
		var prefix = Homm3CustomFactionRegistry.GetBuildingIconKeyPrefix(faction);
		if (string.IsNullOrEmpty(prefix))
			return null;
		return prefix + sid.Trim() + "_level_" + Math.Max(1, level);
	}

	private static List<string> ResolveBuildingHireUnitSids(object building, int level, string source = null)
	{
		var result = new List<string>();
		if (building == null)
		{
			LogBuildingHireResolveDiag(source, null, null, null, null, null, Math.Max(1, level));
			return result;
		}

		var data = ResolveBuildingModelData(building);
		var config = ResolveBuildingDataConfig(data);
		var requestedLevel = Math.Max(1, level);
		AppendSessionHireUnitSetSids(result, data, requestedLevel);
		if (result.Count > 0)
			return result;

		var unitsHire = TryGetMemberValue(config, "unitsHire") ?? TryGetMemberValue(data, "unitsHire");
		var units = TryGetMemberValue(unitsHire, "units");

		foreach (var unitInfo in EnumerateObjects(units))
		{
			var sids = new List<string>();
			foreach (var value in EnumerateStringList(TryGetMemberValue(unitInfo, "sids")))
			{
				var sid = NormalizeUnitSid(value);
				if (!string.IsNullOrWhiteSpace(sid))
					sids.Add(sid);
			}
			if (sids.Count == 0)
				continue;

			if (requestedLevel <= 1)
			{
				result.Add(sids[0]);
				continue;
			}

			for (var i = 1; i < sids.Count; i++)
				result.Add(sids[i]);
		}
		if (result.Count == 0)
			AppendRegistryBuildingHireSids(result, building, data, requestedLevel);
		if (result.Count == 0)
			LogBuildingHireResolveDiag(source, building, data, config, unitsHire, units, requestedLevel);
		return result;
	}

	private static void AppendSessionHireUnitSetSids(List<string> result, object data, int requestedLevel)
	{
		if (result == null || data == null)
			return;
		var assortment = TryGetMemberValue(data, "assortment");
		var unitSets = TryGetMemberValue(assortment, "unitSets");
		foreach (var unitSet in EnumerateObjects(unitSets))
		{
			var setLevel = TryGetIntMember(unitSet, "level");
			if (setLevel != requestedLevel)
				continue;
			foreach (var value in EnumerateStringList(TryGetMemberValue(unitSet, "sids")))
			{
				var sid = NormalizeUnitSid(value);
				if (!string.IsNullOrWhiteSpace(sid))
					result.Add(sid);
			}
		}
	}

	private static void AppendRegistryBuildingHireSids(List<string> result, object building, object data, int requestedLevel)
	{
		if (result == null)
			return;
		var buildingSid = ResolveBuildingSid(building, data);
		var factionSid = ModActions.GetCurrentCityFraction();
		if (!Homm3CustomFactionRegistry.TryGetRecruitmentSidsForBuilding(factionSid, buildingSid, requestedLevel, out var unitSids) || unitSids == null)
			return;
		foreach (var value in unitSids)
		{
			var sid = NormalizeUnitSid(value);
			if (!string.IsNullOrWhiteSpace(sid))
				result.Add(sid);
		}
	}

	private static void LogBuildingHireResolveDiag(string source, object building, object data, object config, object unitsHire, object units, int requestedLevel)
	{
		if (_loggedBuildingHireResolveDiag >= 80)
			return;
		_loggedBuildingHireResolveDiag++;
		var assortment = TryGetMemberValue(data, "assortment");
		var unitSets = TryGetMemberValue(assortment, "unitSets");
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: building hire resolve unresolved"
			+ " source='" + (source ?? "?") + "'"
			+ " requestedLevel=" + requestedLevel
			+ " buildingType='" + SafeTypeName(building) + "'"
			+ " buildingSid='" + (ResolveBuildingSid(building, data, config) ?? "?") + "'"
			+ " dataType='" + SafeTypeName(data) + "'"
			+ " dataSid='" + (TryGetFirstStringFieldMember(data, GameSymbols.ReleaseTownUi.BuildingDataSidMembers) ?? TryGetFirstStringBuildingDataAccessor(data) ?? "?") + "'"
			+ " dataLevel=" + Math.Max(TryGetIntMember(data, "level"), TryGetFirstIntBuildingDataAccessor(data))
			+ " configType='" + SafeTypeName(config) + "'"
			+ " assortmentType='" + SafeTypeName(assortment) + "'"
			+ " unitSetsType='" + SafeTypeName(unitSets) + "'"
			+ " unitSets=" + DescribeHireUnitSets(unitSets)
			+ " unitsHireType='" + SafeTypeName(unitsHire) + "'"
			+ " unitsType='" + SafeTypeName(units) + "'"
			+ " units=" + DescribeConfigUnitInfos(units));
	}

	private static string DescribeHireUnitSets(object unitSets)
	{
		var parts = new List<string>();
		var index = 0;
		foreach (var unitSet in EnumerateObjects(unitSets))
		{
			if (index >= 8)
				break;
			parts.Add("#" + index + ":level=" + TryGetIntMember(unitSet, "level") + ":sids=[" + string.Join(",", EnumerateStringList(TryGetMemberValue(unitSet, "sids"))) + "]");
			index++;
		}
		return parts.Count > 0 ? string.Join("|", parts) : "(none)";
	}

	private static string DescribeConfigUnitInfos(object units)
	{
		var parts = new List<string>();
		var index = 0;
		foreach (var unitInfo in EnumerateObjects(units))
		{
			if (index >= 8)
				break;
			parts.Add("#" + index + ":sids=[" + string.Join(",", EnumerateStringList(TryGetMemberValue(unitInfo, "sids"))) + "]");
			index++;
		}
		return parts.Count > 0 ? string.Join("|", parts) : "(none)";
	}

	private static string SafeTypeName(object obj)
	{
		return obj?.GetType().FullName ?? "(null)";
	}

	private static string NormalizeBuildingSid(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return null;
		var pieces = raw.Trim().Split(new[] { '|', '/', '\\', ':', ';', ',', ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
		for (var i = 0; i < pieces.Length; i++)
		{
			var piece = pieces[i].Trim();
			if (piece.StartsWith("Build_", StringComparison.OrdinalIgnoreCase))
				return piece;
		}
		return pieces.Length > 0 ? pieces[0].Trim() : null;
	}

	private static object ResolveBuildingFromArgsOrView(object view, object[] args)
	{
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				var candidate = args[i];
				if (IsReleaseTownUiCityWrapperCandidate(candidate))
					continue;
				if (!string.IsNullOrWhiteSpace(ResolveBuildingSid(candidate)))
					return candidate;
			}

			for (var i = 0; i < args.Length; i++)
			{
				var candidate = args[i];
				if (IsReleaseTownUiCityWrapperCandidate(candidate))
					continue;
				if (LooksLikeBuildingModel(candidate))
					return candidate;
			}
		}

		if (view is BhBuildingView)
		{
			return ResolveBuildingFromView(view);
		}

		return null;
	}

	private static object ResolveBuildingFromView(object view)
	{
		if (view == null)
			return null;
		var modelType = ResolveBuildingModelType();
		object model = DeobfInteropCompat.TryReadNativeObjectMember(
			view,
			modelType,
			GameSymbols.ReleaseTownUi.BuildingViewModelFields);
		if (model != null)
			return model;
		model = TryGetFirstFieldValue(view, GameSymbols.ReleaseTownUi.BuildingViewModelFields);
		if (model != null)
			return model;
		var viewSid = NormalizeBuildingSid(
			DeobfInteropCompat.TryReadNativeStringMember(view, GameSymbols.ReleaseTownUi.BuildingViewSidFields)
			?? TryGetFirstStringFieldMember(view, GameSymbols.ReleaseTownUi.BuildingViewSidFields));
		return !string.IsNullOrWhiteSpace(viewSid) ? viewSid : null;
	}

	private static Type ResolveBuildingModelType()
	{
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingModelTypeNames.Length; i++)
		{
			var type = FindRuntimeType(GameSymbols.ReleaseTownUi.BuildingModelTypeNames[i]);
			if (type != null && typeof(Il2CppObjectBase).IsAssignableFrom(type))
				return type;
		}
		return null;
	}

	private static object ResolveBuildingViewFromArgsOrTooltip(object tooltip, object[] args)
	{
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (args[i] is BhBuildingView)
					return args[i];
			}
		}

		var nativeView = DeobfInteropCompat.TryReadNativeObjectMember<BhBuildingView>(
			tooltip,
			GameSymbols.ReleaseTownUi.BuildingTooltipViewFields);
		if (nativeView != null)
			return nativeView;
		return TryGetFirstFieldValue(tooltip, GameSymbols.ReleaseTownUi.BuildingTooltipViewFields) is BhBuildingView fallbackView
			? fallbackView
			: null;
	}

	private static int ResolveBuildingLevelFromArgsOrView(object view, object[] args)
	{
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (args[i] is int level && level > 0)
					return level;
			}
		}
		if (view is BhBuildingView)
			return 0;
		return 0;
	}

	private static bool IsReleaseTownUiCityWrapperCandidate(object candidate)
	{
		if (candidate == null)
			return false;
		var typeName = candidate.GetType().FullName ?? candidate.GetType().Name;
		return MatchesTypeHint(typeName, GameSymbols.ReleaseTownUi.CityWrapperTypeHints)
		       || MatchesTypeHint(typeName, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints);
	}

	private static bool MatchesTypeHint(string typeName, string[] hints)
	{
		if (string.IsNullOrWhiteSpace(typeName) || hints == null)
			return false;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (!string.IsNullOrWhiteSpace(hint)
			    && (string.Equals(typeName, hint, StringComparison.Ordinal)
			        || typeName.EndsWith("." + hint, StringComparison.Ordinal)))
				return true;
		}
		return false;
	}

	private static bool LooksLikeBuildingModel(object candidate)
	{
		if (candidate == null || candidate is string || candidate is int || candidate is bool || candidate is float)
			return false;
		var typeName = candidate.GetType().FullName ?? candidate.GetType().Name;
		foreach (var name in GameSymbols.ReleaseTownUi.BuildingModelTypeNames)
		{
			if (string.Equals(typeName, name, StringComparison.Ordinal) || typeName.EndsWith("." + name, StringComparison.Ordinal))
				return true;
		}
		if (ResolveBuildingModelData(candidate) != null)
			return true;
		if (typeName.EndsWith(".BhBuildingView", StringComparison.Ordinal)
		    || typeName.StartsWith("UnityEngine.", StringComparison.Ordinal)
		    || typeName.StartsWith("Il2CppTMPro.", StringComparison.Ordinal))
			return false;
		return false;
	}

	private static object ResolveBuildingModelData(object building)
	{
		if (building == null)
			return null;
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingModelDataMembers.Length; i++)
		{
			var name = GameSymbols.ReleaseTownUi.BuildingModelDataMembers[i];
			var value = TryGetFieldValue(building, name);
			if (value != null)
				return value;
		}
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingModelDataMethods.Length; i++)
		{
			var value = TryInvokeNoArg(building, GameSymbols.ReleaseTownUi.BuildingModelDataMethods[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object ResolveBuildingDataConfig(object data)
	{
		var config = TryGetFirstFieldValue(data, GameSymbols.ReleaseTownUi.DataObjectConfigFields);
		if (config != null)
			return config;
		for (var i = 0; i < GameSymbols.ReleaseTownUi.DataObjectConfigMethods.Length; i++)
		{
			config = TryInvokeNoArg(data, GameSymbols.ReleaseTownUi.DataObjectConfigMethods[i]);
			if (config != null)
				return config;
		}
		return null;
	}

	private static void RememberBuildingViewIconKey(object view, string key)
	{
		if (view == null || string.IsNullOrWhiteSpace(key))
			return;
		BuildingIconKeyByView[GetStableObjectKey(view)] = key.Trim();
	}

	private static void ForgetBuildingViewIconKey(object view)
	{
		if (view == null)
			return;
		BuildingIconKeyByView.Remove(GetStableObjectKey(view));
	}

	private static string RecallBuildingViewIconKey(object view)
	{
		if (view == null)
			return null;
		return BuildingIconKeyByView.TryGetValue(GetStableObjectKey(view), out var key) ? key : null;
	}

	private static void RememberTooltipUnitSids(object view, List<string> sids)
	{
		if (view == null || sids == null || sids.Count == 0)
			return;
		TooltipUnitSidsByView[GetStableObjectKey(view)] = new List<string>(sids);
	}

	private static List<string> RecallTooltipUnitSids(object view)
	{
		if (view == null)
			return new List<string>();
		return TooltipUnitSidsByView.TryGetValue(GetStableObjectKey(view), out var sids)
			? new List<string>(sids)
			: new List<string>();
	}

	private static string ResolveStrongholdAbilityIconKey(object abilityViewConfig)
	{
		var name = TryGetStringMember(abilityViewConfig, "name")
			?? TryGetStringMember(abilityViewConfig, "name_");
		var semanticKey = ResolveStrongholdAbilitySemanticIconKey(name);
		var iconKey = TryGetStringMember(abilityViewConfig, "icon");
		if (!string.IsNullOrWhiteSpace(semanticKey))
			return semanticKey;
		if (!string.IsNullOrWhiteSpace(iconKey))
			return iconKey;
		return semanticKey;
	}

	private static string ResolveStrongholdAbilitySemanticIconKey(string name)
	{
		return name switch
		{
			"base_class_magic_creature" => "neutral_magic_second_sight",
			"base_class_melee_attack" => "sub_skill_assault_1_icon",
			"base_class_ice_immunity" => "magic_healing_water_effect_icon",
			"h3_common_melee_attack_name" => "sub_skill_assault_1_icon",
			"h3_common_passive_ice_damage_immunity_name" => "sub_skill_resistance_1_icon",
			"h3_nymph_passives_1_name" => "space_6_magic_blink",
			"base_passive_blink_name" => "space_6_magic_blink",
			"h3_wolf_rider_upg_passive_1_name" => "pet_blood_icon",
			"h3_wolf_rider_upg_alt_ability_1_name" => "minos_buff_icon",
			"h3_goblin_ability_2_name" => "wasp_debuff_icon",
			"h3_ogre_upg_ability_1_name" => "magic_sharp_edge_effect_icon",
			"h3_ogre_upg_alt_ability_1_name" => "minos_buff_icon",
			"h3_orc_hamstring_name" => "wasp_debuff_icon",
			"h3_orc_upg_hamstring_name" => "wasp_debuff_icon",
			"h3_orc_upg_alt_ability_1_name" => "assassin_buff_icon",
			"h3_roc_upg_ability_1_name" => "primal_1_magic_thunderbolt",
			"h3_roc_upg_alt_passive_1_name" => "dragon_hunter_blood_icon",
			"h3_cyclops_upg_alt_passive_1_name" => "crossbowman_buff_icon",
			"h3_behemoth_passive_1_name" => "sub_skill_units_attackPen_icon",
			"h3_behemoth_upg_passive_1_name" => "sub_skill_units_attackPen_icon",
			"h3_behemoth_upg_alt_passive_1_name" => "sub_skill_units_attackPen_icon",
			_ => null,
		};
	}

	private static bool IsKnownStrongholdCustomAbilityView(object abilityViewConfig)
	{
		var name = TryGetStringMember(abilityViewConfig, "name")
			?? TryGetStringMember(abilityViewConfig, "name_");
		if (IsHomm3AbilityViewConfigName(name))
			return true;
		return name is "h3_goblin_ability_2_name"
			or "h3_wolf_rider_upg_alt_ability_1_name"
			or "h3_ogre_upg_ability_1_name"
			or "h3_ogre_upg_alt_ability_1_name"
			or "h3_orc_hamstring_name"
			or "h3_orc_upg_hamstring_name"
			or "h3_orc_upg_alt_ability_1_name"
			or "h3_roc_upg_ability_1_name";
	}

	private static bool IsGeneratedHomm3AbilityOverrideName(string name)
	{
		if (string.IsNullOrWhiteSpace(name) || !name.StartsWith("h3_", StringComparison.Ordinal))
			return false;
		return name.IndexOf("_abilities_", StringComparison.Ordinal) >= 0
			|| name.IndexOf("_alternativeAttacks_", StringComparison.Ordinal) >= 0;
	}

	private static bool IsHomm3AbilityViewConfig(object abilityViewConfig)
	{
		var name = TryGetStringMember(abilityViewConfig, "name")
			?? TryGetStringMember(abilityViewConfig, "name_");
		return IsHomm3AbilityViewConfigName(name);
	}

	private static bool IsHomm3AbilityViewConfigName(string name)
	{
		if (IsGeneratedHomm3AbilityOverrideName(name))
			return true;
		return !string.IsNullOrWhiteSpace(name)
		       && name.StartsWith("h3_", StringComparison.Ordinal)
		       && (name.IndexOf("_ability", StringComparison.Ordinal) >= 0
		           || name.IndexOf("_passive", StringComparison.Ordinal) >= 0);
	}

	private static void TryApplyCityUiElement(object view, object city, string source)
	{
		if (view == null)
			return;

		TryApplyCityUiElement(view, city, source, null, null);
	}

	private static void TryApplyCityUiElement(object view, object city, string source, string knownKey, Sprite knownSprite)
	{
		if (view == null)
			return;

		var key = ResolveCityIconKey(city)
			?? ResolveCityIconKey(TryGetFirstMemberValue(view, GameSymbols.ReleaseTownUi.CityHudCityFields));
		Homm3UiCardDiagnostics.Log(
			"adventure-map-hud-town-portrait",
			"city-hud-binder-hit",
			"source='" + (source ?? "?") + "' key='" + (key ?? "?")
			+ "' view='" + (view?.GetType().FullName ?? "(null)")
			+ "' city='" + (city?.GetType().FullName ?? "(null)") + "'",
			limit: 120);
		if (!Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(key))
		{
			LogCityHudDiag(view, key, source, "not-custom-city");
			return;
		}
		ModActions.RememberReleaseTownUiCityIconKey(key, source);
		var sprite = IsSameCityIconFaction(knownKey, key) ? knownSprite : null;
		if (!sprite && !TryResolveSprite(key, out sprite))
			return;

		var image = view is Component component
			? FindNamedImage(component, "Pic") ?? TryGetMemberValue(view, "cityIcon") as Image ?? FindNamedImage(component, "cityIcon")
			: TryGetMemberValue(view, "cityIcon") as Image;
		if (!image)
		{
			LogSurfaceDiag(view, key, source, "city hud no-image");
			return;
		}

		ApplySpriteToCityHudImage(image, sprite, keepRaycastTarget: true);
		ApplySpriteToPlaceholderChildren(view, sprite, image);
		Homm3UiCardDiagnostics.Log(
			"adventure-map-hud-town-portrait",
			"city-hud-icon-applied",
			"source='" + (source ?? "?") + "' key='" + key + "' sprite='" + (sprite ? sprite.name : "?")
			+ "' image='" + (image ? image.name : "?") + "'",
			limit: 120);
		LogSurfaceReplace(source, key, sprite, image);
	}

	private static bool IsSameCityIconFaction(string leftKey, string rightKey)
	{
		return Homm3CustomFactionRegistry.TryGetFactionSidForCityIconKey(leftKey, out var leftFaction)
			&& Homm3CustomFactionRegistry.TryGetFactionSidForCityIconKey(rightKey, out var rightFaction)
			&& string.Equals(leftFaction, rightFaction, StringComparison.Ordinal);
	}

	private static bool HasWipCityPic(object view)
	{
		if (!(view is Component component))
			return false;
		var pic = FindNamedImage(component, "Pic");
		if (!pic)
			return false;
		var spriteName = pic.sprite ? pic.sprite.name : string.Empty;
		return string.Equals(spriteName, "WIP", StringComparison.Ordinal)
			|| LooksLikePlaceholder(spriteName);
	}

	private static void ApplySpriteToPlaceholderChildren(object view, Sprite sprite, Image hitImage)
	{
		if (!(view is Component component) || !sprite)
			return;
		var images = component.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image || image == TryGetMemberValue(view, "cityIcon") as Image)
				continue;
			var spriteName = image.sprite ? image.sprite.name : string.Empty;
			var objectName = image.gameObject ? image.gameObject.name : string.Empty;
			if (LooksLikePlaceholder(spriteName) || LooksLikeCityIconImageName(objectName))
				ApplySpriteToCityHudImage(image, sprite, keepRaycastTarget: image == hitImage);
		}
		LogCityImageHierarchy(component);
	}

	private static void ApplySpriteToCityHudImage(Image image, Sprite sprite, bool keepRaycastTarget)
	{
		ApplySpriteToImage(image, sprite);
		if (!image)
			return;
		// BhCityUIElement uses Pic as the button's hit graphic; disabling raycasts removes the clickable area.
		image.raycastTarget = keepRaycastTarget;

		var rect = image.rectTransform;
		if (!rect)
			return;
		var instanceId = image.GetInstanceID();
		if (AdjustedCityHudImages.Add(instanceId))
			rect.anchoredPosition += new Vector2(-3f, 3f);
	}

	private static bool LooksLikePlaceholder(string spriteName)
	{
		if (string.IsNullOrWhiteSpace(spriteName))
			return true;
		return spriteName.IndexOf("placeholder", StringComparison.OrdinalIgnoreCase) >= 0
			|| spriteName.IndexOf("plug", StringComparison.OrdinalIgnoreCase) >= 0
			|| spriteName.IndexOf("default", StringComparison.OrdinalIgnoreCase) >= 0
			|| spriteName.IndexOf("missing", StringComparison.OrdinalIgnoreCase) >= 0
			|| spriteName.IndexOf("unknown", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool ContainsIgnoreCase(string value, string needle)
	{
		return !string.IsNullOrWhiteSpace(value)
			&& !string.IsNullOrWhiteSpace(needle)
			&& value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool LooksLikeCityIconImageName(string objectName)
	{
		if (string.IsNullOrWhiteSpace(objectName))
			return false;
		return objectName.IndexOf("city", StringComparison.OrdinalIgnoreCase) >= 0
			&& objectName.IndexOf("icon", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static string ResolveCityIconKey(object city)
	{
		if (city == null)
			return null;

		var dataObject = TryGetFirstMemberValue(city, GameSymbols.ReleaseTownUi.SessionCityDataFields);
		var sid = TryGetStringMember(dataObject, "sidConfig")
			?? TryGetStringMember(city, "sidConfig")
			?? TryGetStringMember(city, "id");
		var resolved = NormalizeCityIconKey(sid);
		if (resolved != null)
			return resolved;

		var config = TryGetFirstMemberValue(city, GameSymbols.ReleaseTownUi.SessionCityConfigFields)
			?? TryGetFirstMemberValue(dataObject, GameSymbols.ReleaseTownUi.DataObjectConfigFields);
		sid = TryGetStringMember(config, "id");
		resolved = NormalizeCityIconKey(sid);
		if (resolved != null)
			return resolved;

		var fraction = TryGetStringMember(config, "fraction")
			?? TryGetStringMember(dataObject, "fraction")
			?? TryGetStringMember(city, "fraction");
		var citySid = Homm3CustomFactionRegistry.GetCitySidForFaction(fraction);
		if (!string.IsNullOrWhiteSpace(citySid))
			return citySid;

		return null;
	}

	private static string NormalizeCityIconKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		if (Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(sid))
			return sid;
		var citySid = Homm3CustomFactionRegistry.GetCitySidForFaction(sid);
		return string.IsNullOrWhiteSpace(citySid) ? null : citySid;
	}

	private static bool TryApplyToSurface(object view, string key, string source)
	{
		if (view == null || string.IsNullOrWhiteSpace(key))
			return false;
		LogSurfaceDiag(view, key, source, "string");
		if (!TryResolveSprite(key, out var sprite) || !sprite)
			return false;

		// Asset-only compatibility surface: this helper paints sprites and must not construct native identity payloads.
		if (IsHireUnitItemSurface(view, source))
		{
			if (Homm3ImportVisuals.IsOwnedSkinnedUnitSid(key))
				return true;
			if (TryApplyHireUnitPortraitOverlay(view, key, sprite, source))
				return true;
			LogHireOverlay(source, key, sprite, view as Component, null, "failed-no-ya-root");
			return false;
		}

		var image = FindBestImage(view);
		if (image == null)
			return false;
		ApplySpriteToImage(image, sprite);
		LogSurfaceReplace(source, key, sprite, image);
		return true;
	}

	private static bool TryApplyMagicItemViewIconSurface(object view, string key, string source)
	{
		if (view == null || string.IsNullOrWhiteSpace(key))
			return false;
		if (!TryResolveSprite(key, out var sprite) || !sprite)
			return false;
		var image = TryGetMemberValue(view, "pic") as Image;
		if (!image && view is Component component)
			image = FindNamedImage(component, "pic") ?? FindBestImage(component);
		if (!image)
			return false;
		ApplySpriteToImage(image, sprite);
		if (_loggedSpellbookMagicIconReplace++ < 24)
			Plugin.LogSource?.LogInfo("Homm3CustomUiIcon: spellbook magic icon replaced key=" + key + " source=" + source + " image=" + image.name + " sprite=" + sprite.name + ".");
		return true;
	}

	private static string ResolveMagicItemIconKey(object magic)
	{
		var config = TryInvokeNoArg(magic, "yoa") ?? TryGetMemberValue(magic, "cnsl") ?? TryGetMemberValue(magic, "config") ?? magic;
		return TryGetFirstStringMember(config, new[] { "icon", "cmyj" });
	}

	private static bool TryApplyHeroProfileIconSurface(object view, string key, string source, string surface)
	{
		if (view == null)
			return false;
		if (string.IsNullOrWhiteSpace(key))
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"icon-binder-miss",
				"reason='no-key' source='" + (source ?? "?") + "' view='" + DescribeIconSurface(view) + "'");
			return false;
		}
		Homm3UiCardDiagnostics.Log(
			surface,
			"icon-binder-hit",
			"source='" + (source ?? "?") + "' key='" + key + "' view='" + DescribeIconSurface(view) + "'");
		LogSurfaceDiag(view, key, source, surface);
		if (!TryResolveSprite(key, out var sprite) || !sprite)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"icon-binder-miss",
				"reason='no-sprite' source='" + (source ?? "?") + "' key='" + key + "' view='" + DescribeIconSurface(view) + "'");
			return false;
		}

		var image = FindHeroProfileIconImage(view);
		if (image == null)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"icon-binder-miss",
				"reason='no-image' source='" + (source ?? "?") + "' key='" + key + "' view='" + DescribeIconSurface(view) + "'");
			return false;
		}
		ApplySpriteToImage(image, sprite);
		Homm3UiCardDiagnostics.Log(
			surface,
			"icon-applied",
			"source='" + (source ?? "?") + "' key='" + key + "' sprite='" + (sprite ? sprite.name : "?")
			+ "' image='" + (image ? image.name : "?") + "'");
		LogSurfaceReplace(source, key, sprite, image);
		return true;
	}


	private static string ResolveHeroProfileSkillIconKey(object view)
	{
		var runtime = TryGetFirstMemberValue(view, GameSymbols.HeroProfile.SkillRuntimeFields);
		if (runtime == null)
		{
			var payload = TryGetFirstMemberValue(view, GameSymbols.HeroProfile.SkillPayloadFields);
			runtime = TryGetFirstMemberValue(payload, GameSymbols.HeroProfile.SkillRuntimeFields);
		}
		return ResolveSkillRuntimeIconKey(runtime);
	}

	private static string ResolveSkillRuntimeIconKey(object runtime)
	{
		var config = TryGetFirstMemberValue(runtime, GameSymbols.HeroProfile.SkillConfigFields) ?? runtime;
		var key = ResolveHeroProfileSkillLevelIconKey(runtime, config);
		if (!string.IsNullOrWhiteSpace(key))
			return key;
		key = TryGetFirstStringMember(config, new[] { "icon", "cmyj" });
		if (!string.IsNullOrWhiteSpace(key))
			return key;
		foreach (var getter in GameSymbols.HeroProfile.SkillConfigGetters)
		{
			var resolved = TryInvokeNoArg(config, getter) ?? TryInvokeNoArg(runtime, getter);
			key = resolved as string
				?? ResolveHeroProfileSkillLevelIconKey(runtime, resolved)
				?? TryGetFirstStringMember(resolved, new[] { "icon", "cmyj" });
			if (!string.IsNullOrWhiteSpace(key))
				return key;
		}
		return null;
	}

	private static string ResolveHeroProfileSubSkillIconKey(object view)
	{
		var runtime = TryGetFirstMemberValue(view, GameSymbols.HeroProfile.SubSkillRuntimeFields);
		if (runtime == null)
		{
			var payload = TryGetFirstMemberValue(view, GameSymbols.HeroProfile.SubSkillPayloadFields);
			runtime = TryGetFirstMemberValue(payload, GameSymbols.HeroProfile.SubSkillRuntimeFields);
		}
		var config = TryGetFirstMemberValue(runtime, GameSymbols.HeroProfile.SubSkillConfigFields) ?? runtime;
		var key = TryGetFirstStringMember(config, new[] { "icon", "cmyj" });
		if (!string.IsNullOrWhiteSpace(key))
			return key;
		foreach (var getter in GameSymbols.HeroProfile.SubSkillConfigGetters)
		{
			var resolved = TryInvokeNoArg(config, getter) ?? TryInvokeNoArg(runtime, getter);
			key = resolved as string ?? TryGetFirstStringMember(resolved, new[] { "icon", "cmyj" });
			if (!string.IsNullOrWhiteSpace(key))
				return key;
		}
		return null;
	}

	private static string ResolveHeroProfileSkillLevelIconKey(object runtime, object config)
	{
		if (config == null)
			return null;
		var parameters = TryGetMemberValue(config, "parametersPerLevel") as IEnumerable;
		if (parameters == null)
			return null;
		var level = TryGetFirstIntMember(runtime, GameSymbols.HeroProfile.SkillLevelFields);
		if (level <= 0)
		{
			var data = TryGetFirstMemberValue(runtime, GameSymbols.HeroProfile.SkillDataFields);
			level = TryGetFirstIntMember(data, GameSymbols.HeroProfile.SkillLevelFields);
		}
		if (level <= 0)
			return null;
		var targetIndex = Math.Max(0, level - 1);
		var index = 0;
		foreach (var parameter in parameters)
		{
			if (index == targetIndex)
				return TryGetFirstStringMember(parameter, new[] { "icon", "cmyj" });
			index++;
		}
		return null;
	}

	private static Image FindHeroProfileIconImage(object view)
	{
		var image = TryGetMemberValue(view, "icon") as Image
			?? TryGetMemberValue(view, "skillIcon") as Image
			?? TryGetMemberValue(view, "specializationIcon") as Image;
		if (image)
			return image;
		return FindNamedImage(view as Component, "icon") ?? FindNamedImage(view as Component, "skillIcon") ?? FindBestImage(view);
	}

	private static bool TryApplyLevelUpIconSurface(object view, string key, string source, string surface)
	{
		if (view == null)
			return false;
		if (string.IsNullOrWhiteSpace(key))
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"icon-binder-miss",
				"reason='no-key' source='" + (source ?? "?") + "' view='" + DescribeIconSurface(view) + "'");
			return false;
		}
		if (!Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(key))
			return false;
		Homm3UiCardDiagnostics.Log(
			surface,
			"icon-binder-hit",
			"source='" + (source ?? "?") + "' key='" + key + "' view='" + DescribeIconSurface(view) + "'");
		LogSurfaceDiag(view, key, source, surface);
		if (!Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(key, out var sprite) || !sprite)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"icon-binder-miss",
				"reason='no-sprite' source='" + (source ?? "?") + "' key='" + key + "' view='" + DescribeIconSurface(view) + "'");
			return false;
		}

		var image = FindLevelUpSkillIconImage(view);
		if (image == null)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"icon-binder-miss",
				"reason='no-image' source='" + (source ?? "?") + "' key='" + key + "' view='" + DescribeIconSurface(view) + "'");
			return false;
		}
		ApplySpriteToImage(image, sprite);
		Homm3UiCardDiagnostics.Log(
			surface,
			"icon-applied",
			"source='" + (source ?? "?") + "' key='" + key + "' sprite='" + (sprite ? sprite.name : "?")
			+ "' image='" + (image ? image.name : "?") + "'");
		LogSurfaceReplace(source, key, sprite, image);
		return true;
	}

	private static string DescribeIconSurface(object view)
	{
		if (view == null)
			return "(null)";
		var component = view as Component;
		return component && component.gameObject
			? component.gameObject.name + "/" + (view.GetType().FullName ?? view.GetType().Name)
			: view.GetType().FullName ?? view.GetType().Name;
	}

	private static bool TryApplyBattleAbilityIcon(BhUnitAbilityView view, string key, Sprite sprite, string source)
	{
		if (!view || !sprite)
			return false;

		if (TryApplyNativeBattleAbilityIcon(view, sprite))
		{
			ClearBattleAbilityIconOverlay(view);
			return true;
		}

		var images = view.GetComponentsInChildren<Image>(true);
		Image best = null;
		var bestScore = int.MinValue;
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image)
				continue;

			var objectName = image.gameObject ? image.gameObject.name : string.Empty;
			var spriteName = image.sprite ? image.sprite.name : string.Empty;
			var score = ScoreBattleAbilityIconImage(objectName, spriteName);
			if (score > bestScore)
			{
				bestScore = score;
				best = image;
			}
		}

		if (!best || bestScore <= 0)
		{
			Homm3UiCardDiagnostics.Log(
				"unit-preview-ability-icons",
				"ability-icon-no-target-image",
				"source='" + (source ?? "?") + "' key='" + key + "' view='" + (view ? view.name : "?") + "'");
			LogSurfaceDiag(view, key, source, "battle ability no-icon-image");
			return false;
		}

		ApplySpriteToImage(best, sprite);
		TryApplyBattleAbilityIconOverlay(view, best, sprite);
		Homm3UiCardDiagnostics.Log(
			"unit-preview-ability-icons",
			"ability-icon-applied",
			"source='" + (source ?? "?") + "' key='" + key + "' sprite='" + (sprite ? sprite.name : "?")
			+ "' view='" + (view ? view.name : "?") + "' target='" + (best ? best.name : "?") + "'");
		return true;
	}

	private static bool TryApplyBattleAbilityIconOverlayOnly(BhUnitAbilityView view, string key, Sprite sprite, string source)
	{
		if (!view || !sprite)
			return false;

		var images = view.GetComponentsInChildren<Image>(true);
		Image best = null;
		var bestScore = int.MinValue;
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!image || string.Equals(image.name, BattleAbilityIconOverlayName, StringComparison.Ordinal))
				continue;
			var objectName = image.gameObject ? image.gameObject.name : string.Empty;
			var spriteName = image.sprite ? image.sprite.name : string.Empty;
			var score = ScoreBattleAbilityIconImage(objectName, spriteName);
			if (score > bestScore)
			{
				bestScore = score;
				best = image;
			}
		}

		if (!best || bestScore <= 0)
		{
			Homm3UiCardDiagnostics.Log(
				"unit-preview-ability-icons",
				"ability-icon-overlay-no-target-image",
				"source='" + (source ?? "?") + "' key='" + key + "' view='" + (view ? view.name : "?") + "'");
			return false;
		}

		LogBattleAbilityIconDiag(view, key, sprite, source, best, bestScore, "before-overlay");
		ApplySpriteToImage(best, sprite);
		var overlayApplied = TryApplyBattleAbilityIconOverlay(view, best, sprite);
		var overlay = TryFindBattleAbilityIconOverlay(best);
		LogBattleAbilityIconDiag(view, key, sprite, source, overlay ? overlay : best, bestScore, overlayApplied ? "after-overlay" : "overlay-failed");
		Homm3UiCardDiagnostics.Log(
			"unit-preview-ability-icons",
			overlayApplied ? "ability-icon-overlay-applied" : "ability-icon-overlay-failed",
			"source='" + (source ?? "?") + "' key='" + key + "' sprite='" + (sprite ? sprite.name : "?")
			+ "' view='" + (view ? view.name : "?") + "' target='" + (overlay ? overlay.name : best ? best.name : "?") + "'");
		return overlayApplied;
	}

	private static bool TryApplyNativeBattleAbilityIcon(BhUnitAbilityView view, Sprite sprite)
	{
		if (!view || !sprite)
			return false;

		var applied = 0;
		try
		{
			var viewBase = TryGetMemberValue(view, "viewBase");
			var pics = TryGetMemberValue(viewBase, "pics");
			foreach (var item in EnumerateIl2CppList(pics))
			{
				if (item is not Image image || !ShouldReplaceNativeBattleAbilityIconImage(image))
					continue;
				ApplySpriteToImage(image, sprite);
				applied++;
			}

			if (applied > 0)
				return true;

			if (viewBase is Component component)
			{
				var images = component.GetComponentsInChildren<Image>(true);
				for (var i = 0; i < images.Length; i++)
				{
					var image = images[i];
					if (!ShouldReplaceNativeBattleAbilityIconImage(image))
						continue;
					ApplySpriteToImage(image, sprite);
					applied++;
				}
			}
		}
		catch { }

		return applied > 0;
	}

	private static bool ShouldReplaceNativeBattleAbilityIconImage(Image image)
	{
		if (!image)
			return false;
		var objectName = image.gameObject ? image.gameObject.name : string.Empty;
		var spriteName = image.sprite ? image.sprite.name : string.Empty;
		if (ContainsIgnoreCase(objectName, "frame")
		    || ContainsIgnoreCase(objectName, "back")
		    || ContainsIgnoreCase(objectName, "cooldown")
		    || ContainsIgnoreCase(objectName, "energy")
		    || ContainsIgnoreCase(objectName, "focus"))
			return false;
		if (ContainsIgnoreCase(objectName, "icon") || ContainsIgnoreCase(objectName, "pic"))
			return true;
		if (LooksLikePlaceholder(spriteName))
			return true;
		return string.Equals(spriteName, "WIP", StringComparison.Ordinal)
			|| ContainsIgnoreCase(spriteName, "WIP");
	}

	private static IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;
		var type = list.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Public | BindingFlags.Instance);
		var itemProperty = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance);
		var getItem = itemProperty != null ? null : type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance);
		if (countProperty == null || (itemProperty == null && getItem == null))
			yield break;

		int count;
		try { count = Convert.ToInt32(countProperty.GetValue(list, null)); }
		catch { yield break; }
		for (var i = 0; i < count; i++)
		{
			object item = null;
			try
			{
				item = itemProperty != null
					? itemProperty.GetValue(list, new object[] { i })
					: getItem.Invoke(list, new object[] { i });
			}
			catch { }
			if (item != null)
				yield return item;
		}
	}

	private static IEnumerable<object> EnumerateIl2CppArray(object array)
	{
		if (array == null)
			yield break;
		var type = array.GetType();
		var lengthProperty = type.GetProperty("Length", BindingFlags.Public | BindingFlags.Instance);
		var itemProperty = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance);
		var getItem = itemProperty != null ? null : type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance);
		if (lengthProperty == null || (itemProperty == null && getItem == null))
			yield break;

		int length;
		try { length = Convert.ToInt32(lengthProperty.GetValue(array, null)); }
		catch { yield break; }
		for (var i = 0; i < length; i++)
		{
			object item = null;
			try
			{
				item = itemProperty != null
					? itemProperty.GetValue(array, new object[] { i })
					: getItem.Invoke(array, new object[] { i });
			}
			catch { }
			if (item != null)
				yield return item;
		}
	}

	private static void TryApplyBattleAbilityFocusMarkersRelease(BhUnitAbilityView view, object ability)
	{
		if (!view || ability == null)
			return;

		var logic = TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityLogicFields);
		var abilityView = TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields);
		var energyLevel = TryGetIntMember(logic, "energyLevel");
		if (logic == null || energyLevel <= 0 || TryGetBoolMember(logic, "dontUseEnergy"))
			return;
		if (!IsKnownStrongholdCustomAbilityView(abilityView))
			return;

		var viewBase = TryGetMemberValue(view, "viewBase");
		if (viewBase == null)
			return;

		try
		{
			var method = GameMember.FindFirstMethodByNames(
				viewBase.GetType(),
				new[] { typeof(int), typeof(int) },
				GameSymbols.SelectedUnitHud.AbilityViewBaseFocusMarkers);
			if (method == null)
				return;

			var cost = Mathf.Clamp(energyLevel, 1, 4);
			method.Invoke(viewBase, new object[] { cost, cost });
			RaiseBattleAbilityOverlayBelowEnergyContainer(view);
			LogBattleAbilityFocusMarkers(view, TryGetStringMember(abilityView, "name"), cost);
		}
		catch (Exception ex)
		{
			if (_loggedBattleAbilityFocusMarkers < 8)
			{
				_loggedBattleAbilityFocusMarkers++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: release focus marker update failed: " + ex.Message);
			}
		}
	}

	private static bool TryApplyBattleAbilityIconOverlay(BhUnitAbilityView view, Image anchor, Sprite sprite)
	{
		if (!view || !anchor || !sprite)
			return false;

		var anchorRect = anchor.rectTransform;
		if (!anchorRect)
			return false;

		var overlayRect = FindDirectChildRect(anchorRect.parent, BattleAbilityIconOverlayName);
		Image overlay;
		if (overlayRect)
		{
			overlayRect.gameObject.SetActive(true);
			overlay = overlayRect.GetComponent<Image>() ?? overlayRect.gameObject.AddComponent<Image>();
		}
		else
		{
			var go = new GameObject(BattleAbilityIconOverlayName);
			go.transform.SetParent(anchorRect.parent ? anchorRect.parent : view.transform, false);
			overlayRect = go.AddComponent<RectTransform>();
			overlay = go.AddComponent<Image>();
		}

		CopyRectTransform(anchorRect, overlayRect);
		overlayRect.SetAsLastSibling();
		PlaceBattleAbilityOverlayBelowEnergyContainer(view, overlayRect);
		overlay.raycastTarget = false;
		ApplySpriteToImage(overlay, sprite);
		return true;
	}

	private static void RaiseBattleAbilityOverlayBelowEnergyContainer(BhUnitAbilityView view)
	{
		if (!view)
			return;

		var overlays = view.GetComponentsInChildren<RectTransform>(true);
		for (var i = 0; i < overlays.Length; i++)
		{
			var overlay = overlays[i];
			if (overlay && string.Equals(overlay.name, BattleAbilityIconOverlayName, StringComparison.Ordinal))
				PlaceBattleAbilityOverlayBelowEnergyContainer(view, overlay);
		}
	}

	private static void PlaceBattleAbilityOverlayBelowEnergyContainer(BhUnitAbilityView view, RectTransform overlayRect)
	{
		if (!view || !overlayRect || !overlayRect.parent)
			return;

		var energy = FindEnergyContainerRect(view, overlayRect.parent);
		if (energy && energy.parent == overlayRect.parent)
			overlayRect.SetSiblingIndex(Mathf.Max(0, energy.GetSiblingIndex()));
	}

	private static RectTransform FindEnergyContainerRect(BhUnitAbilityView view, Transform requiredParent)
	{
		if (!view || !requiredParent)
			return null;

		var viewBase = TryGetMemberValue(view, "viewBase");
		var energyContainer = TryGetMemberValue(viewBase, "energyContainer") as Component;
		if (energyContainer && energyContainer.transform)
		{
			for (var t = energyContainer.transform; t != null && t != view.transform; t = t.parent)
			{
				if (t.parent == requiredParent)
					return t as RectTransform;
			}
		}

		var rects = view.GetComponentsInChildren<RectTransform>(true);
		for (var i = 0; i < rects.Length; i++)
		{
			var rect = rects[i];
			if (!rect || rect.parent != requiredParent)
				continue;
			var name = rect.name ?? string.Empty;
			if (name.IndexOf("energy", StringComparison.OrdinalIgnoreCase) >= 0
				|| name.IndexOf("focus", StringComparison.OrdinalIgnoreCase) >= 0)
				return rect;
		}
		return null;
	}

	private static void ClearBattleAbilityIconOverlay(BhUnitAbilityView view)
	{
		if (!view)
			return;
		try
		{
			var overlays = view.GetComponentsInChildren<RectTransform>(true);
			for (var i = 0; i < overlays.Length; i++)
			{
				var overlay = overlays[i];
				if (overlay && string.Equals(overlay.name, BattleAbilityIconOverlayName, StringComparison.Ordinal))
					overlay.gameObject.SetActive(false);
			}
		}
		catch { }
	}

	private static void ClearBattleAbilityIconReplacement(BhUnitAbilityView view)
	{
		if (!view)
			return;
		ForgetBattleAbilityIconReplacement(view);
		try
		{
			var viewBase = TryGetMemberValue(view, "viewBase");
			var pics = TryGetMemberValue(viewBase, "pics");
			foreach (var item in EnumerateIl2CppList(pics))
				if (item is Image image)
					ClearBattleAbilityIconReplacement(image);
			if (viewBase is Component component)
				ClearBattleAbilityIconReplacements(component.GetComponentsInChildren<Image>(true));
			ClearBattleAbilityIconReplacements(view.GetComponentsInChildren<Image>(true));
		}
		catch { }
	}

	private static void ClearBattleAbilityIconReplacements(Image[] images)
	{
		if (images == null)
			return;
		for (var i = 0; i < images.Length; i++)
			ClearBattleAbilityIconReplacement(images[i]);
	}

	private static void ClearBattleAbilityIconReplacement(Image image)
	{
		if (!ShouldReplaceNativeBattleAbilityIconImage(image))
			return;
		if (IsStrongholdAbilityDonorSprite(image.overrideSprite))
			image.overrideSprite = null;
		if (IsStrongholdAbilityDonorSprite(image.sprite))
		{
			image.sprite = null;
			image.overrideSprite = null;
		}
	}

	private static bool HasRememberedBattleAbilityIconReplacement(BhUnitAbilityView view)
	{
		return view && BattleAbilityIconKeyByView.ContainsKey(GetStableObjectKey(view));
	}

	private static bool HasRememberedBattleAbilityIconReplacementKey(BhUnitAbilityView view, string key)
	{
		return view
		       && !string.IsNullOrWhiteSpace(key)
		       && BattleAbilityIconKeyByView.TryGetValue(GetStableObjectKey(view), out var remembered)
		       && string.Equals(remembered, key.Trim(), StringComparison.Ordinal);
	}

	private static bool HasBattleAbilityIconReplacement(BhUnitAbilityView view, string key, Sprite sprite)
	{
		if (!view || string.IsNullOrWhiteSpace(key) || !sprite)
			return false;
		if (!BattleAbilityIconKeyByView.TryGetValue(GetStableObjectKey(view), out var remembered)
		    || !string.Equals(remembered, key.Trim(), StringComparison.Ordinal))
			return false;
		var overlay = TryFindBattleAbilityIconOverlay(view);
		return overlay
		       && overlay.gameObject.activeInHierarchy
		       && (string.Equals(overlay.sprite ? overlay.sprite.name : null, sprite.name, StringComparison.Ordinal)
		           || string.Equals(overlay.overrideSprite ? overlay.overrideSprite.name : null, sprite.name, StringComparison.Ordinal));
	}

	private static void RememberBattleAbilityIconReplacement(BhUnitAbilityView view, string key)
	{
		if (!view || string.IsNullOrWhiteSpace(key))
			return;
		BattleAbilityIconKeyByView[GetStableObjectKey(view)] = key.Trim();
	}

	private static void ForgetBattleAbilityIconReplacement(BhUnitAbilityView view)
	{
		if (!view)
			return;
		BattleAbilityIconKeyByView.Remove(GetStableObjectKey(view));
	}

	private static bool IsStrongholdAbilityDonorSprite(Sprite sprite)
	{
		return sprite && IsStrongholdAbilityDonorIconKey(sprite.name);
	}

	private static bool IsBattleAbilityCustomIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var sid = key.Trim();
		return IsStrongholdAbilityDonorIconKey(sid)
		       || IsHomm3UnitSid(sid)
		       || Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(sid);
	}

	private static Image TryFindBattleAbilityIconOverlay(Image anchor)
	{
		if (!anchor || !anchor.rectTransform || !anchor.rectTransform.parent)
			return null;
		var overlayRect = FindDirectChildRect(anchor.rectTransform.parent, BattleAbilityIconOverlayName);
		return overlayRect ? overlayRect.GetComponent<Image>() : null;
	}

	private static Image TryFindBattleAbilityIconOverlay(BhUnitAbilityView view)
	{
		if (!view)
			return null;
		var images = view.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image && string.Equals(image.name, BattleAbilityIconOverlayName, StringComparison.Ordinal))
				return image;
		}
		return null;
	}

	private static RectTransform FindDirectChildRect(Transform parent, string name)
	{
		if (!parent || string.IsNullOrWhiteSpace(name))
			return null;
		for (var i = 0; i < parent.childCount; i++)
		{
			var child = parent.GetChild(i);
			if (child && string.Equals(child.name, name, StringComparison.Ordinal))
				return child as RectTransform;
		}
		return null;
	}

	private static void CopyRectTransform(RectTransform source, RectTransform target)
	{
		if (!source || !target)
			return;
		target.anchorMin = source.anchorMin;
		target.anchorMax = source.anchorMax;
		target.pivot = source.pivot;
		target.anchoredPosition = source.anchoredPosition;
		target.sizeDelta = source.sizeDelta;
		target.localRotation = source.localRotation;
		target.localScale = source.localScale;
	}

	private static int ScoreBattleAbilityIconImage(string objectName, string spriteName)
	{
		var score = 0;
		if (LooksLikePlaceholder(spriteName))
			score += 20;
		if (ContainsIgnoreCase(objectName, "icon"))
			score += 15;
		if (ContainsIgnoreCase(objectName, "pic"))
			score += 12;
		if (ContainsIgnoreCase(objectName, "ability"))
			score += 6;
		if (ContainsIgnoreCase(spriteName, "icon"))
			score += 5;
		if (ContainsIgnoreCase(objectName, "frame") || ContainsIgnoreCase(objectName, "back") || ContainsIgnoreCase(objectName, "cooldown"))
			score -= 12;
		if (ContainsIgnoreCase(objectName, "glow") || ContainsIgnoreCase(objectName, "edge") || ContainsIgnoreCase(objectName, "highlight"))
			score -= 25;
		return score;
	}

	private static bool IsHireUnitItemSurface(object view, string source)
	{
		if (!string.IsNullOrWhiteSpace(source)
		    && source.IndexOf("BhHireUnitItemView", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		return view != null
		       && (view.GetType().FullName ?? string.Empty).IndexOf("BhHireUnitItemView", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool TryApplyHireUnitPortraitOverlay(object view, string key, Sprite sprite, string source)
	{
		if (!(view is Component component) || !sprite)
			return false;

		var root = component.transform as RectTransform;
		var frame = FindBestImage(view);
		if (!root && frame)
			root = frame.rectTransform;
		if (!root)
			return false;

		var image = GetOrCreateHireOverlayImage(component, root, out var rect);
		if (!image || !rect)
			return false;

		rect.anchorMin = new Vector2(0.5f, 0.5f);
		rect.anchorMax = new Vector2(0.5f, 0.5f);
		rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition = Vector2.zero;
		rect.sizeDelta = ResolveHireOverlaySize(root);
		rect.SetAsLastSibling();

		image.raycastTarget = false;
		Homm3HireUnitPortraitAnimator.Apply(image, key, sprite);
		RememberRecruitmentItemSid(component, key);
		HideHireUnitNativeDonorVisuals(component, key, source);
		LogHireOverlay(source, key, sprite, component, image, "ok");
		return true;
	}

	private static void HideHireUnitNativeDonorVisuals(Component component, string key, string source)
	{
		if (!component || !IsHomm3UnitSid(key) || Homm3ImportVisuals.IsOwnedSkinnedUnitSid(key))
			return;
		try
		{
			var hidden = 0;
			if (TryGetFirstMemberOrNoArgValue(component, GameSymbols.UnitPreviewAbilityIcons.HireUnitItemNativePreviewRawImageFields) is RawImage nativeRaw && nativeRaw)
			{
				nativeRaw.enabled = false;
				hidden++;
			}
			if (TryGetFirstMemberOrNoArgValue(component, GameSymbols.UnitPreviewAbilityIcons.HireUnitItemPreviewFields) is { } preview
			    && TryGetFirstMemberOrNoArgValue(preview, GameSymbols.UnitPreviewAbilityIcons.HireUnitPreviewRootFields) is GameObject previewRoot
			    && previewRoot)
			{
				if (previewRoot.activeSelf)
				{
					previewRoot.SetActive(false);
					hidden++;
				}
			}
			foreach (var childRaw in component.GetComponentsInChildren<RawImage>(true))
			{
				if (!childRaw || !childRaw.enabled)
					continue;
				if (!IsLikelyHireNativeDonorRawImage(component, childRaw))
					continue;
				childRaw.enabled = false;
				hidden++;
			}
			foreach (var renderer in component.GetComponentsInChildren<Renderer>(true))
			{
				if (!renderer || !renderer.enabled)
					continue;
				if (!IsLikelyHireNativeDonorRenderer(component, renderer))
					continue;
				renderer.enabled = false;
				hidden++;
			}
			if (hidden > 0 && _loggedHireNativeVisualHidden < 16)
			{
				_loggedHireNativeVisualHidden++;
				Plugin.LogSource?.LogInfo(
					"Homm3CustomUiIcon: hid native donor hire visual key='"
					+ key
					+ "' count="
					+ hidden
					+ " source="
					+ (source ?? "?")
					+ ".");
			}
		}
		catch (Exception ex)
		{
			if (_loggedHireNativeVisualHidden < 16)
			{
				_loggedHireNativeVisualHidden++;
				Plugin.LogSource?.LogWarning("Homm3CustomUiIcon: hide native donor hire visual failed: " + ex.Message);
			}
		}
	}

	private static bool IsLikelyHireNativeDonorRawImage(Component root, RawImage raw)
	{
		if (!root || !raw)
			return false;
		var path = GetTransformPath(raw.transform, root.transform);
		var objectText = (raw.name + "/" + (raw.texture ? raw.texture.name : "")).ToLowerInvariant();
		var pathText = path.ToLowerInvariant();
		if (objectText.Contains("homm3_")
		    || objectText.Contains("frame")
		    || objectText.Contains("back")
		    || objectText.Contains("mask")
		    || objectText.Contains("bg")
		    || pathText.Contains("/back/")
		    || pathText.Contains("/mask/"))
			return false;
		return objectText.Contains("raw")
		       || objectText.Contains("render")
		       || objectText.Contains("model")
		       || objectText.Contains("unit")
		       || objectText.Contains("creature")
		       || objectText.Contains("preview")
		       || objectText.Contains("body")
		       || pathText.Contains("/raw")
		       || pathText.Contains("/render")
		       || pathText.Contains("/model")
		       || pathText.Contains("/preview");
	}

	private static bool IsLikelyHireNativeDonorRenderer(Component root, Renderer renderer)
	{
		if (!root || !renderer)
			return false;
		var path = GetTransformPath(renderer.transform, root.transform);
		var text = (renderer.name + "/" + path).ToLowerInvariant();
		if (text.Contains("homm3_") || text.Contains("overlay") || text.Contains("portrait"))
			return false;
		return true;
	}

	private static Image GetOrCreateHireOverlayImage(Component component, RectTransform root, out RectTransform rect)
	{
		rect = null;
		if (!component || !root)
			return null;

		var overlays = component.GetComponentsInChildren<RectTransform>(true);
		foreach (var overlay in overlays)
		{
			if (!overlay || !string.Equals(overlay.name, HirePortraitOverlayName, StringComparison.Ordinal))
				continue;

			if (!rect)
			{
				rect = overlay;
				continue;
			}

			overlay.gameObject.SetActive(false);
			UnityEngine.Object.Destroy(overlay.gameObject);
		}

		Image image = null;
		if (rect)
		{
			if (rect.parent != root)
				rect.SetParent(root, false);
			rect.gameObject.SetActive(true);
			image = rect.GetComponent<Image>() ?? rect.gameObject.AddComponent<Image>();
		}
		else
		{
			var go = new GameObject(HirePortraitOverlayName);
			go.transform.SetParent(root, false);
			rect = go.AddComponent<RectTransform>();
			image = go.AddComponent<Image>();
		}
		return image;
	}

	private static Vector2 ResolveHireOverlaySize(RectTransform root)
	{
		var rect = root.rect;
		var w = rect.width;
		var h = rect.height;
		if (w > 8f && h > 8f)
		{
			var size = Mathf.Clamp(Mathf.Min(w, h) * 1.44f, 96f, 280f);
			return new Vector2(size, size);
		}
		return new Vector2(184f, 184f);
	}

	private static Image FindBestImage(object view)
	{
		foreach (var name in new[] { "pic", "icon", "cityIcon", "portrait", "skillIconImage", "heroFace" })
		{
			var image = TryGetMemberValue(view, name) as Image;
			if (image)
				return image;
		}
		return view is Component c ? c.GetComponentInChildren<Image>(true) : null;
	}

	private static Image FindLevelUpSkillIconImage(object view)
	{
		var image = TryGetMemberValue(view, "pic") as Image;
		if (image)
			return image;
		if (view is not Component component || !component)
			return null;

		// Runtime-proven on Golden Era 2026-06-17: active CanvasLevelUp skill tiles store
		// their visible icon as an unbound child image at LEVEL UP SKILL/Root/Pic.
		var root = FindDirectChild(component.transform, "Root");
		var pic = FindDirectChild(root, "Pic");
		return pic ? pic.GetComponent<Image>() : null;
	}

	private static Transform FindDirectChild(Transform parent, string name)
	{
		if (!parent || string.IsNullOrWhiteSpace(name))
			return null;
		for (var i = 0; i < parent.childCount; i++)
		{
			var child = parent.GetChild(i);
			if (child && string.Equals(child.name, name, StringComparison.Ordinal))
				return child;
		}
		return null;
	}

	private static Image FindNamedImage(Component root, string name)
	{
		if (!root || string.IsNullOrWhiteSpace(name))
			return null;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image && image.gameObject && string.Equals(image.gameObject.name, name, StringComparison.OrdinalIgnoreCase))
				return image;
		}
		return null;
	}

	private static void ApplySpriteToImage(Image image, Sprite sprite)
	{
		if (!image || !sprite)
			return;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = Color.white;
		image.gameObject.SetActive(true);
	}

	private static object TryGetMemberValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (obj is BhBuildingView && GameSymbols.ReleaseTownUi.IsBuildingViewFieldOnlyMember(name))
		{
			return null;
		}
		var type = obj.GetType();
		for (var t = type; t != null; t = t.BaseType)
		{
			var field = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (field != null)
			{
				try { return field.GetValue(obj); } catch { }
			}
			var prop = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (prop != null && prop.GetIndexParameters().Length == 0)
			{
				try { return prop.GetValue(obj); } catch { }
			}
		}
		return null;
	}

	private static object TryGetFieldValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = obj.GetType();
		for (var t = type; t != null; t = t.BaseType)
		{
			var field = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (field != null)
			{
				try { return field.GetValue(obj); } catch { }
			}
		}
		return null;
	}

	private static object TryGetFirstMemberValue(object obj, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetMemberValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetFirstMemberOrNoArgValue(object obj, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetMemberValue(obj, names[i]) ?? TryInvokeNoArg(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetStaticMemberValue(Type type, string name)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var t = type; t != null; t = t.BaseType)
		{
			var field = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
			if (field != null)
			{
				try { return field.GetValue(null); } catch { }
			}
			var prop = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
			if (prop != null && prop.GetIndexParameters().Length == 0)
			{
				try { return prop.GetValue(null); } catch { }
			}
		}
		return null;
	}

	private static object TryGetFirstStaticMemberValue(Type type, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetStaticMemberValue(type, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static bool TrySetFirstMemberValue(object obj, string[] names, object value)
	{
		if (names == null)
			return false;
		for (var i = 0; i < names.Length; i++)
			if (TrySetMemberValue(obj, names[i], value))
				return true;
		return false;
	}

	private static bool TrySetMemberValue(object obj, string name, object value)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return false;
		var type = obj.GetType();
		for (var t = type; t != null; t = t.BaseType)
		{
			var field = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (field != null && CanAssignMemberValue(field.FieldType, value))
			{
				try
				{
					field.SetValue(obj, value);
					return true;
				}
				catch { }
			}
			var prop = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (prop != null && prop.CanWrite && prop.GetIndexParameters().Length == 0 && CanAssignMemberValue(prop.PropertyType, value))
			{
				try
				{
					prop.SetValue(obj, value);
					return true;
				}
				catch { }
			}
		}
		return false;
	}

	private static bool CanAssignMemberValue(Type targetType, object value)
	{
		if (targetType == null)
			return false;
		if (value == null)
			return !targetType.IsValueType || Nullable.GetUnderlyingType(targetType) != null;
		var sourceType = value.GetType();
		return targetType.IsAssignableFrom(sourceType) || sourceType.IsAssignableFrom(targetType);
	}

	private static object TryInvokeNoArg(object obj, string name)
	{
		if (obj == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var method = FindMethodByName(obj.GetType(), name, 0);
			return method != null ? method.Invoke(obj, Array.Empty<object>()) : null;
		}
		catch { return null; }
	}

	private static MethodInfo FindMethodByName(Type type, string name, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			MethodInfo[] methods;
			try
			{
				methods = current.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
			}
			catch
			{
				continue;
			}
			for (var i = 0; i < methods.Length; i++)
			{
				var method = methods[i];
				if (method != null && method.Name == name && method.GetParameters().Length == parameterCount)
					return method;
			}
		}
		return null;
	}

	private static string TryGetStringMember(object obj, string name)
	{
		return TryGetMemberValue(obj, name) as string;
	}

	private static string TryGetFirstStringMember(object obj, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetMemberValue(obj, names[i]) ?? TryInvokeNoArg(obj, names[i]);
			if (value is string s && !string.IsNullOrWhiteSpace(s))
				return s;
		}
		return null;
	}

	private static object TryGetFirstFieldValue(object obj, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetFieldValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static string TryGetFirstStringFieldMember(object obj, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetFieldValue(obj, names[i]);
			if (value is string s && !string.IsNullOrWhiteSpace(s))
				return s;
		}
		return null;
	}

	private static string TryGetFirstStringMethod(object obj, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryInvokeNoArg(obj, names[i]);
			if (value is string s && !string.IsNullOrWhiteSpace(s))
				return s;
		}
		return null;
	}

	private static string TryGetFirstStringBuildingDataAccessor(object data)
	{
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods.Length; i++)
		{
			var value = TryInvokeExactBuildingDataAccessor(data, GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods[i]);
			if (value is string s && !string.IsNullOrWhiteSpace(s))
				return s;
		}
		return null;
	}

	private static int TryGetFirstIntBuildingDataAccessor(object data)
	{
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods.Length; i++)
		{
			var value = TryInvokeExactBuildingDataAccessor(data, GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods[i]);
			if (value is int direct && direct > 0)
				return direct;
			if (value != null && int.TryParse(value.ToString(), out var parsed) && parsed > 0)
				return parsed;
		}
		return 0;
	}

	private static object TryInvokeExactBuildingDataAccessor(object data, string methodName)
	{
		if (data == null || string.IsNullOrEmpty(methodName))
			return null;
		if (!ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods, methodName)
		    && !ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods, methodName))
			return null;
		try
		{
			var method = FindMethodByName(data.GetType(), methodName, 0);
			if (method == null || !IsExpectedBuildingDataAccessorReturnType(methodName, method.ReturnType))
				return null;
			return method.Invoke(data, Array.Empty<object>());
		}
		catch
		{
			return null;
		}
	}

	private static bool IsExpectedBuildingDataAccessorReturnType(string methodName, Type returnType)
	{
		if (returnType == null)
			return false;
		if (ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods, methodName))
			return returnType == typeof(string);
		if (ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods, methodName))
			return returnType == typeof(int);
		return false;
	}

	private static bool ContainsExact(string[] values, string value)
	{
		if (values == null || value == null)
			return false;
		for (var i = 0; i < values.Length; i++)
		{
			if (string.Equals(values[i], value, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static MethodInfo FindMethodByNames(Type type, IEnumerable<string> names, int parameterCount)
	{
		if (type == null || names == null)
			return null;
		foreach (var name in names)
		{
			var method = FindMethodByName(type, name, parameterCount);
			if (method != null)
				return method;
		}
		return null;
	}

	private static int TryGetIntMember(object obj, string name)
	{
		var value = TryGetMemberValue(obj, name);
		if (value is int i)
			return i;
		if (value != null && int.TryParse(value.ToString(), out i))
			return i;
		return 0;
	}

	private static int TryGetFirstIntMember(object obj, string[] names)
	{
		if (names == null)
			return 0;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetMemberValue(obj, names[i]) ?? TryInvokeNoArg(obj, names[i]);
			if (value is int direct && direct > 0)
				return direct;
			if (value != null && int.TryParse(value.ToString(), out var parsed) && parsed > 0)
				return parsed;
		}
		return 0;
	}

	private static int TryGetFirstIntFieldMember(object obj, string[] names)
	{
		if (names == null)
			return 0;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetFieldValue(obj, names[i]);
			if (value is int direct && direct > 0)
				return direct;
			if (value != null && int.TryParse(value.ToString(), out var parsed) && parsed > 0)
				return parsed;
		}
		return 0;
	}

	private static int TryGetFirstIntMethod(object obj, string[] names)
	{
		if (names == null)
			return 0;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryInvokeNoArg(obj, names[i]);
			if (value is int direct && direct > 0)
				return direct;
			if (value != null && int.TryParse(value.ToString(), out var parsed) && parsed > 0)
				return parsed;
		}
		return 0;
	}

	private static bool TryGetBoolMember(object obj, string name)
	{
		var value = TryGetMemberValue(obj, name);
		if (value is bool b)
			return b;
		return value != null && bool.TryParse(value.ToString(), out b) && b;
	}

	// Stable view identity: native pointer for IL2CPP views (survives re-wrap), never a managed hash.
	private static long GetStableObjectKey(object obj)
	{
		return Homm3DirectStateIdentity.ResolveKeyOrZero(obj);
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

	private static void LogResolverPatch(ManualLogSource log, MethodBase method)
	{
		if (_loggedResolverPatch >= 40)
			return;
		_loggedResolverPatch++;
		log?.LogInfo("Homm3CustomUiIcon: resolver prefix registered on " + FormatMethod(method) + ".");
	}

	private static void LogResolverReplace(string kind, string key, string resultName, MethodBase method)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedResolverReplace >= 80)
			return;
		_loggedResolverReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: supplied " + kind + " for key='" + key + "' result='" + resultName + "' via " + FormatMethod(method) + ".");
	}

	private static void LogSurfacePatch(ManualLogSource log, MethodBase method)
	{
		if (_loggedSurfacePatch >= 40)
			return;
		_loggedSurfacePatch++;
		log?.LogInfo("Homm3CustomUiIcon: surface postfix registered on " + FormatMethod(method) + ".");
	}

	private static void LogSurfaceReplace(string source, string key, Sprite sprite, Image image)
	{
		if (Homm3StrongholdCityIconSpriteCache.IsStrongholdCityIconKey(key))
			ModActions.RememberReleaseTownUiCityIconKey(key, source);
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedSurfaceReplace >= 80)
			return;
		_loggedSurfaceReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: surface replaced [" + source + "] key='" + key + "' sprite='"
			+ (sprite ? sprite.name : "?") + "' image='" + (image ? image.name : "?") + "'.");
	}

	private static void LogBattleAbilityReplace(BhUnitAbilityView view, string key, Sprite sprite)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		Homm3UiCardDiagnostics.Log(
			"unit-preview-ability-icons",
			"battle-ability-icon-replaced",
			"key='" + key + "' sprite='" + (sprite ? sprite.name : "?") + "' view='" + (view ? view.name : "?") + "'");
		if (_loggedBattleAbilityReplace >= 30)
			return;
		_loggedBattleAbilityReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: battle ability icon fallback key='" + key + "' sprite='"
			+ (sprite ? sprite.name : "?") + "' view='" + (view ? view.name : "?") + "'.");
	}

	private static void LogBattleAbilityIconDiag(BhUnitAbilityView view, string key, Sprite sprite, string source, Image image, int score, string phase)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedBattleAbilityIconDiag >= 120)
			return;
		_loggedBattleAbilityIconDiag++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon battle icon diag: " + phase + " [" + source + "] key='" + key
			+ "' sprite='" + (sprite ? sprite.name : "?")
			+ "' view='" + (view ? view.name : "?")
			+ "' target=" + DescribeImageForDiag(image, view ? view.transform : null)
			+ " score=" + score + ".");
		if (view)
			LogIconImageHierarchy(view, "battle ability " + phase + " " + source + " key=" + key, 16, ref _loggedBattleAbilityIconDiag, 120);
	}

	private static string DescribeImageForDiag(Image image, Transform root)
	{
		if (!image)
			return "(null)";
		var rect = image.rectTransform;
		var size = rect ? rect.rect.size : Vector2.zero;
		var sibling = rect && rect.parent ? rect.GetSiblingIndex().ToString() + "/" + rect.parent.childCount.ToString() : "?";
		return "'" + GetTransformPath(image.transform, root)
			+ "' image='" + image.name
			+ "' sprite='" + (image.sprite ? image.sprite.name : "(null)")
			+ "' override='" + (image.overrideSprite ? image.overrideSprite.name : "(null)")
			+ "' active=" + (image.gameObject && image.gameObject.activeInHierarchy)
			+ " enabled=" + image.enabled
			+ " sibling=" + sibling
			+ " size=" + size.x.ToString("0.##") + "x" + size.y.ToString("0.##");
	}

	private static void LogBattleAbilityFocusMarkers(BhUnitAbilityView view, string name, int cost)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedBattleAbilityFocusMarkers >= 30)
			return;
		_loggedBattleAbilityFocusMarkers++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: focus markers applied cost=" + cost
			+ " ability='" + (name ?? "?") + "' view='" + (view ? view.name : "?") + "'.");
	}

	private static void LogHireOverlay(string source, string key, Sprite sprite, Component root, Image image, string result)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedHireOverlay >= 80)
			return;
		_loggedHireOverlay++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: hire portrait overlay " + result + " [" + source + "] key='" + key + "' sprite='"
			+ (sprite ? sprite.name : "?") + "' root='" + (root ? root.name : "?")
			+ "' image='" + (image ? image.name : "?") + "' size="
			+ (image && image.rectTransform ? image.rectTransform.sizeDelta.ToString("F1") : "?") + ".");
	}

	private static void LogLoadedSpriteFallback(string key, Sprite sprite)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedLoadedSpriteFallback >= 12)
			return;
		_loggedLoadedSpriteFallback++;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: loaded vanilla sprite fallback key='" + key + "' sprite='"
			+ (sprite ? sprite.name : "?") + "'.");
	}

	private static void LogBuildingTooltip(object tooltip, string key, Sprite sprite, string source, string reason)
	{
		if (_loggedBuildingTooltipReplace >= 20)
			return;
		_loggedBuildingTooltipReplace++;
		var component = tooltip as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: building tooltip " + reason
			+ " source=" + source
			+ " key='" + (key ?? "") + "'"
			+ " sprite='" + (sprite ? sprite.name : "") + "'"
			+ " tooltip='" + (component ? component.name : tooltip.GetType().Name) + "'.");
	}

	private static void LogBuildingView(object view, string key, Sprite sprite, string source, string reason)
	{
		if (_loggedBuildingViewReplace >= 40)
			return;
		_loggedBuildingViewReplace++;
		var component = view as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: building view " + reason
			+ " source=" + source
			+ " key='" + (key ?? "") + "'"
			+ " sprite='" + (sprite ? sprite.name : "") + "'"
			+ " view='" + (component ? component.name : view?.GetType().Name ?? "") + "'.");
	}

	private static void LogBuildingViewSuccessHierarchy(Component root, string key, string source, int applied)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (!root || _loggedBuildingViewSuccessHierarchy >= 96)
			return;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length && _loggedBuildingViewSuccessHierarchy < 96; i++)
		{
			var image = images[i];
			if (!image || !image.gameObject || !image.gameObject.activeInHierarchy || !image.enabled)
				continue;
			_loggedBuildingViewSuccessHierarchy++;
			var rect = image.rectTransform;
			var size = rect ? rect.rect.size : Vector2.zero;
			var sibling = rect && rect.parent ? rect.GetSiblingIndex().ToString() + "/" + rect.parent.childCount.ToString() : "?";
			var color = image.color;
			Plugin.LogSource?.LogInfo(
				"Homm3CustomUiIcon probe: building view success image"
				+ " source=" + source
				+ " key='" + (key ?? "") + "'"
				+ " applied=" + applied
				+ " path='" + GetTransformPath(image.transform, root.transform) + "'"
				+ " image='" + image.name + "'"
				+ " sprite='" + (image.sprite ? image.sprite.name : "(null)") + "'"
				+ " override='" + (image.overrideSprite ? image.overrideSprite.name : "(null)") + "'"
				+ " color=" + color.r.ToString("0.###") + "," + color.g.ToString("0.###") + "," + color.b.ToString("0.###") + "," + color.a.ToString("0.###")
				+ " sibling=" + sibling
				+ " size=" + size.x.ToString("0.##") + "x" + size.y.ToString("0.##")
				+ " placeholder=" + LooksLikePlaceholder(image.sprite ? image.sprite.name : null) + ".");
		}
	}

	private static void LogBuildingViewBindProbe(object view, object building, int level, string source)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedBuildingIconProbe >= 80)
			return;
		_loggedBuildingIconProbe++;
		string fraction = null;
		string key = null;
		try
		{
			fraction = ModActions.GetCurrentCityFraction();
			key = building == null ? RecallBuildingViewIconKey(view) : ResolveHomm3BuildingTooltipIconKey(building, level);
		}
		catch (Exception ex)
		{
			key = "diag-error:" + ex.GetType().Name;
		}

		var component = view as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon probe: building view bind"
			+ " source=" + source
			+ " fraction='" + (fraction ?? "") + "'"
			+ " level=" + level
			+ " key='" + (key ?? "") + "'"
			+ " view='" + (component ? component.name : view?.GetType().Name ?? "") + "'"
			+ " buildingType='" + (building?.GetType().FullName ?? "(null)") + "'.");
	}

	private static void LogBuildingViewEarlyReturn(object view, object building, int level, string source, string reason)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedBuildingIconProbe >= 80)
			return;
		_loggedBuildingIconProbe++;
		var component = view as Component;
		string fraction = null;
		string resolvedSid = null;
		try
		{
			fraction = ModActions.GetCurrentCityFraction();
			if (building != null)
			{
				var data = ResolveBuildingModelData(building);
				var config = ResolveBuildingDataConfig(data);
				resolvedSid = ResolveBuildingSid(building, data, config);
			}
		}
		catch (Exception ex)
		{
			resolvedSid = "diag-error:" + ex.GetType().Name;
		}
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon probe: building view skip"
			+ " reason='" + reason + "'"
			+ " source=" + source
			+ " fraction='" + (fraction ?? "") + "'"
			+ " level=" + level
			+ " resolvedSid='" + (resolvedSid ?? "") + "'"
			+ " view='" + (component ? component.name : view?.GetType().Name ?? "") + "'"
			+ " buildingType='" + (building?.GetType().FullName ?? "(null)") + "'.");
	}

	private static void LogBuildingIconProbe(object view, object building, string source, string reason)
	{
		if (_loggedBuildingIconProbe >= 80)
			return;
		_loggedBuildingIconProbe++;
		var component = view as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon probe: building icon " + reason
			+ " source=" + source
			+ " view='" + (component ? component.name : view?.GetType().Name ?? "") + "'"
			+ " buildingType='" + (building?.GetType().FullName ?? "(null)") + "'"
			+ " members=" + DescribeBuildingProbeMembers(building) + ".");
		if (component)
			LogIconImageHierarchy(component, "building icon " + reason + " " + source, 8, ref _loggedBuildingIconProbe, 80);
	}

	private static string DescribeBuildingProbeMembers(object building)
	{
		if (building == null)
			return "(null)";
		var data = ResolveBuildingModelData(building);
		var config = ResolveBuildingDataConfig(data);
		return "modelSid='" + (TryGetFirstStringFieldMember(building, GameSymbols.ReleaseTownUi.BuildingModelSidMembers)
				?? TryGetFirstStringMethod(building, GameSymbols.ReleaseTownUi.BuildingModelSidMethods)
				?? "")
			+ "',dataSid='" + (TryGetFirstStringFieldMember(data, GameSymbols.ReleaseTownUi.BuildingDataSidMembers) ?? "")
			+ "',configSid='" + (TryGetFirstStringFieldMember(config, GameSymbols.ReleaseTownUi.BuildingConfigSidMembers) ?? "")
			+ "',resolvedSid='" + (ResolveBuildingSid(building, data, config) ?? "")
			+ "',modelLevel=" + (TryGetFirstIntFieldMember(building, GameSymbols.ReleaseTownUi.BuildingModelLevelMembers) > 0
				? TryGetFirstIntFieldMember(building, GameSymbols.ReleaseTownUi.BuildingModelLevelMembers)
				: TryGetFirstIntMethod(building, GameSymbols.ReleaseTownUi.BuildingModelLevelMethods))
			+ ",dataLevel=" + TryGetFirstIntFieldMember(data, GameSymbols.ReleaseTownUi.BuildingDataLevelMembers)
			+ ",dataType='" + SafeTypeName(data)
			+ "',configType='" + SafeTypeName(config) + "'";
	}

	private static void LogIconImageHierarchy(Component root, string source, int maxImages, ref int counter, int limit)
	{
		if (!root || counter >= limit)
			return;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length && i < maxImages && counter < limit; i++)
		{
			var image = images[i];
			if (!image)
				continue;
			counter++;
			var spriteName = image.sprite ? image.sprite.name : "(null)";
			var overrideName = image.overrideSprite ? image.overrideSprite.name : "(null)";
			var size = image.rectTransform ? image.rectTransform.rect.size : Vector2.zero;
			Plugin.LogSource?.LogInfo(
				"Homm3CustomUiIcon probe image: source='" + source
				+ "' path='" + GetTransformPath(image.transform, root.transform)
				+ "' image='" + image.name
				+ "' sprite='" + spriteName
				+ "' override='" + overrideName
				+ "' placeholder=" + LooksLikePlaceholder(spriteName)
				+ " active=" + (image.gameObject && image.gameObject.activeInHierarchy)
				+ " enabled=" + image.enabled
				+ " size=" + size.x.ToString("0.##") + "x" + size.y.ToString("0.##") + ".");
		}
	}

	private static string GetTransformPath(Transform transform, Transform stopAt)
	{
		if (!transform)
			return "(null)";
		var path = transform.name;
		for (var current = transform.parent; current && current != stopAt; current = current.parent)
			path = current.name + "/" + path;
		if (stopAt)
			path = stopAt.name + "/" + path;
		return path;
	}

	private static void LogRecruitmentPanelReplace(object view, string key, Sprite sprite, string source, string reason)
	{
		if (_loggedRecruitmentPanelReplace >= 30)
			return;
		_loggedRecruitmentPanelReplace++;
		var component = view as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon: recruitment panel icon " + reason + " [" + source + "] key='" + key + "' sprite='"
			+ (sprite ? sprite.name : "?") + "' view='" + (component ? component.name : view?.GetType().Name ?? "?") + "'.");
	}

	private static void LogRecruitmentPullupDiag(object reason, object item, int index, string source, string sid, Image image, string detail)
	{
		if (_loggedRecruitmentItemDiag >= 220)
			return;
		_loggedRecruitmentItemDiag++;
		var component = item as Component;
		Homm3UiCardDiagnostics.Log(
			"town-recruitment-pullup-unit-portraits",
			"recruitment-item-resolution",
			"reason='" + (reason ?? "?")
			+ "' source='" + (source ?? "?")
			+ "' index=" + index
			+ " sid='" + (sid ?? "?")
			+ "' currentFaction='" + (ModActions.GetCurrentCityFraction() ?? "?")
			+ "' item='" + (component ? component.name + "/" + component.GetType().FullName : FormatObject(item))
			+ "' image=" + DescribeImageForDiag(image, component ? component.transform : null)
			+ " remembered='" + (RecallRecruitmentItemSid(item) ?? "?")
			+ "' " + (detail ?? ""),
			limit: 260);
	}

	private static void LogSurfaceDiag(object view, string key, string source, string reason)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedSurfaceDiag >= 120)
			return;
		if (!IsCustomKey(key) && !string.IsNullOrWhiteSpace(key))
			return;
		_loggedSurfaceDiag++;
		var image = FindBestImage(view);
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon diag: " + reason + " [" + source + "] key='"
			+ (key ?? "(null)") + "' view='" + (view?.GetType().FullName ?? "(null)")
			+ "' image='" + (image ? image.name : "(null)") + "' sprite='"
			+ (image && image.sprite ? image.sprite.name : "(null)") + "' override='"
			+ (image && image.overrideSprite ? image.overrideSprite.name : "(null)") + "'.");
	}

	private static void LogCityHudDiag(object view, string key, string source, string reason)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (_loggedCityHudDiag >= 40)
			return;
		_loggedCityHudDiag++;
		var storedCity = TryGetMemberValue(view, "cawv");
		var storedSid = TryGetStringMember(TryGetMemberValue(storedCity, "ciyz"), "sidConfig")
			?? TryGetStringMember(storedCity, "sidConfig")
			?? TryGetStringMember(TryGetMemberValue(storedCity, "ciyy"), "id");
		Plugin.LogSource?.LogInfo(
			"Homm3CustomUiIcon city hud diag: " + reason + " [" + source + "] key='"
			+ (key ?? "(null)") + "' storedSid='" + (storedSid ?? "(null)") + "' view='"
			+ (view?.GetType().FullName ?? "(null)") + "'.");
		if (view is Component component)
			LogCityImageHierarchy(component);
	}

	private static void LogCityImageHierarchy(Component component)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (!component || _loggedCityHudDiag >= 40)
			return;
		var images = component.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length && _loggedCityHudDiag < 40; i++)
		{
			var image = images[i];
			if (!image)
				continue;
			_loggedCityHudDiag++;
			Plugin.LogSource?.LogInfo(
				"Homm3CustomUiIcon city image: object='" + (image.gameObject ? image.gameObject.name : "(null)")
				+ "' image='" + image.name + "' sprite='" + (image.sprite ? image.sprite.name : "(null)")
				+ "' override='" + (image.overrideSprite ? image.overrideSprite.name : "(null)")
				+ "' active=" + (image.gameObject && image.gameObject.activeInHierarchy)
				+ " enabled=" + image.enabled + ".");
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "(null)";
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static void LogBattleAbilityBinderHit(BhUnitAbilityView view, object ability, string source)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		try
		{
			var abilityViewConfig = TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields);
			var iconKey = ResolveStrongholdAbilityIconKey(abilityViewConfig);
			Homm3UiCardDiagnostics.Log(
				"unit-preview-ability-icons",
				"ability-icon-binder-hit",
				"source='" + (source ?? "?")
				+ "' view='" + FormatView(view)
				+ "' ability='" + FormatObject(ability)
				+ "' abilityView='" + FormatObject(abilityViewConfig)
				+ "' iconKey='" + (iconKey ?? "?")
				+ "' customDonor=" + IsStrongholdAbilityDonorIconKey(iconKey)
				+ " imageCount=" + CountImages(view),
				limit: 80);
		}
		catch (Exception ex)
		{
			Homm3UiCardDiagnostics.Log(
				"unit-preview-ability-icons",
				"ability-icon-binder-hit-failed",
				"source='" + (source ?? "?") + "' error='" + ex.GetType().Name + ": " + ex.Message + "'",
				limit: 20);
		}
	}

	private static string FormatView(BhUnitAbilityView view)
	{
		if (!view)
			return "(null)";
		return (view.name ?? "?") + "/" + (view.GetType().FullName ?? view.GetType().Name);
	}

	private static string FormatObject(object obj)
	{
		return obj == null ? "(null)" : obj.GetType().FullName ?? obj.GetType().Name;
	}

	private static int CountImages(Component root)
	{
		if (!root)
			return 0;
		try
		{
			return root.GetComponentsInChildren<Image>(true)?.Length ?? 0;
		}
		catch
		{
			return -1;
		}
	}
}
