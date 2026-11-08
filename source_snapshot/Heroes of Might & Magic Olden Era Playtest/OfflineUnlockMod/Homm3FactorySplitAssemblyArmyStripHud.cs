using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Adventure army-strip Split Assembly readout left of <c>BhHeroHUDPanel.heroView.heroFace</c>
/// on <c>CanvasHeroHUDPanel</c>: leaf + green x/4, gear + orange-brown x/4, hover tooltip.
/// </summary>
internal static class Homm3FactorySplitAssemblyArmyStripHud
{
	private const string OverlayRootName = "HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS";
	private const string TooltipRootName = "HOMM3_FACTORY_SPLIT_ASSEMBLY_TOOLTIP";
	private const float IconSize = 22f;
	private const float TextSize = 16f;
	private const float RowGap = 5f;
	private const float IconTextGap = 4f;
	private const float BlockGap = 6f;
	private const float CountLabelWidth = 34f;
	private static readonly Color NatureGreen = new(0.20f, 0.76f, 0.28f, 1f);
	private static readonly Color IndustryOrangeBrown = new(0.82f, 0.46f, 0.12f, 1f);
	private static readonly Color GearTint = new(0.72f, 0.42f, 0.10f, 1f);
	private static readonly object Gate = new();
	private static readonly Dictionary<int, MeterView> ViewsByElement = new();

	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedSkips;
	private static int _loggedApplies;
	private static GameObject _sharedTooltip;
	private static TextMeshProUGUI _sharedTooltipText;
	private static int _tooltipOwnerKey = -1;
	private static Sprite _leafSprite;
	private static Sprite _gearSprite;

	private sealed class MeterView
	{
		internal GameObject Root;
		internal TextMeshProUGUI NaturalCount;
		internal TextMeshProUGUI IndustrialCount;
		internal Homm3FactorySplitAssemblyEvaluator.Snapshot Snapshot;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FactorySplitAssemblyHudHoverPump>();
			}
			catch (Exception ex)
			{
				_log?.LogDebug("HoMM3 Factory Split Assembly HUD hover pump already registered: " + ex.Message);
			}

			if (!Homm3FactorySplitAssemblyHudHoverPump.Ensure(_log))
				throw new InvalidOperationException("Split Assembly HUD hover pump failed to start");

			var panelType = ResolveRequiredType(
				"Hex.Session.Hud.BhHeroHUDPanel",
				"homm3.factory.splitAssembly.armyStrip.heroHudPanel");
			var refreshMethods = FindHeroHudRefreshMethods(panelType);
			if (refreshMethods.Count == 0)
				throw new MissingMethodException("BhHeroHUDPanel army-strip refresh surface missing");
			foreach (var refresh in refreshMethods)
				PatchPostfix(harmony, refresh, nameof(PostfixHeroHudPanelRefresh));

			var heroArgRefresh = GameMember.FindFirstMethodByNames(
				panelType,
				new Type[1],
				GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh);
			if (heroArgRefresh != null
			    && !heroArgRefresh.IsStatic
			    && heroArgRefresh.ReturnType == typeof(void)
			    && heroArgRefresh.GetParameters().Length == 1
			    && IsSessionHeroParameterType(heroArgRefresh.GetParameters()[0].ParameterType))
			{
				PatchPostfix(harmony, heroArgRefresh, nameof(PostfixHeroHudPanelHeroArgRefresh));
			}
			else
			{
				// Fail closed: a same-shape method with another parameter type (the stale "vso"
				// bound junk type ObjectPublicVo2) cannot carry a hero. The parameterless refresh
				// patches above still run.
				_log?.LogWarning(
					"HoMM3 Factory Split Assembly army-strip HUD: hero-arg refresh not patched; "
					+ (heroArgRefresh == null
						? "no method named " + string.Join("/", GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh.NameHints)
						: heroArgRefresh.Name + " parameter is " + (heroArgRefresh.GetParameters().Length > 0 ? heroArgRefresh.GetParameters()[0].ParameterType.FullName : "<none>"))
					+ ", not the session hero type.");
			}

			_registered = true;
			_log?.LogInfo(
				"HoMM3 Factory Split Assembly army-strip HUD registered (leaf/gear x/4 left of BhHeroHUDPanel.heroView.heroFace).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(
				"HoMM3 Factory Split Assembly army-strip HUD not registered; exact startup surface missing: "
				+ ex.Message);
		}
	}

	private static bool IsSessionHeroParameterType(Type parameterType)
	{
		if (parameterType == null || parameterType.IsValueType)
			return false;
		foreach (var hint in GameSymbols.HeroMap.SessionHeroTypeHints)
		{
			if (!string.IsNullOrEmpty(hint)
			    && (string.Equals(parameterType.Name, hint, StringComparison.Ordinal)
			        || string.Equals(parameterType.FullName, hint, StringComparison.Ordinal)))
				return true;
		}
		return false;
	}

	private static List<MethodInfo> FindHeroHudRefreshMethods(Type panelType)
	{
		var methods = new List<MethodInfo>();
		const BindingFlags flags =
			BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		foreach (var name in GameSymbols.ImportVisuals.HeroHudPanelRefresh.NameHints)
		{
			var method = panelType.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && !methods.Contains(method))
				methods.Add(method);
		}
		if (methods.Count == 0)
		{
			foreach (var method in GameMember.FindParameterlessReturning(
				         panelType,
				         typeof(void),
				         GameSymbols.ImportVisuals.HeroHudPanelRefresh.Id,
				         GameSymbols.ImportVisuals.HeroHudPanelRefresh.NameHints))
			{
				if (method != null && !methods.Contains(method))
					methods.Add(method);
			}
		}
		return methods;
	}

	private static void PostfixHeroHudPanelRefresh(object __instance)
	{
		TryRefresh(__instance, null, "BhHeroHUDPanel.Refresh");
	}

	private static void PostfixHeroHudPanelHeroArgRefresh(object __instance, [HarmonyArgument(0)] object hero)
	{
		TryRefresh(__instance, hero, "BhHeroHUDPanel.HeroArgRefresh");
	}

	private static void TryRefresh(object element, object sessionHero, string source)
	{
		try
		{
			if (!(element is Component component) || !component)
			{
				Hide(element);
				return;
			}

			if (!TryBuildSnapshot(
				    sessionHero ?? TryResolveSessionHeroFromPanel(element),
				    out var snapshot,
				    out var failReason))
			{
				Hide(element);
				if (_loggedSkips++ < 24 && !string.IsNullOrWhiteSpace(failReason))
					_log?.LogWarning("HoMM3 Factory Split Assembly HUD skip (" + source + "): " + failReason);
				return;
			}

			if (snapshot.NaturalTier == 0 && snapshot.IndustrialTier == 0)
			{
				Hide(element);
				if (_loggedSkips++ < 24)
				{
					_log?.LogWarning(
						"HoMM3 Factory Split Assembly HUD skip ("
						+ source
						+ "): both branch tiers are 0 (rank="
						+ snapshot.Rank
						+ " naturalLines="
						+ snapshot.NaturalLines
						+ " industrialLines="
						+ snapshot.IndustrialLines
						+ ").");
				}
				return;
			}

			if (!TryEnsureView(component, out var view, out var viewFail))
			{
				Hide(element);
				LogLimited("meter view failed: " + viewFail);
				return;
			}

			ApplySnapshot(view, snapshot);
			if (_loggedApplies++ < 16)
			{
				_log?.LogInfo(
					"HoMM3 Factory Split Assembly HUD applied ("
					+ source
					+ "): natural="
					+ snapshot.NaturalTier
					+ "/4 industrial="
					+ snapshot.IndustrialTier
					+ "/4 rank="
					+ snapshot.Rank
					+ ".");
			}
		}
		catch (Exception ex)
		{
			Hide(element);
			var detail = ex.GetType().Name + ": " + ex.Message;
			if (!string.IsNullOrEmpty(ex.StackTrace))
			{
				foreach (var rawLine in ex.StackTrace.Split('\n'))
				{
					if (rawLine == null)
						continue;
					var line = rawLine.Trim();
					if (line.IndexOf("Homm3FactorySplitAssembly", StringComparison.Ordinal) < 0)
						continue;
					detail += " @ " + line;
					break;
				}
			}
			LogLimited("refresh failed closed: " + detail);
		}
	}

	internal static bool TryBuildSnapshot(
		object sessionHero,
		out Homm3FactorySplitAssemblyEvaluator.Snapshot snapshot,
		out string failReason)
	{
		snapshot = null;
		failReason = null;
		if (sessionHero == null)
		{
			failReason = "session hero missing";
			return false;
		}

		if (!TryResolveDataHero(sessionHero, out var dataHero, out failReason))
			return false;
		if (!TryResolveFactorySkillRank(dataHero, out var rank, out failReason))
			return false;
		if (!TryEnumerateAdventureArmySids(dataHero, out var unitSids, out failReason))
			return false;

		var naturalOverclock = HasHeroSubSkill(dataHero, Homm3FactorySplitAssemblyEvaluator.NaturalOverclockSubSkillSid);
		var industrialOverclock = HasHeroSubSkill(dataHero, Homm3FactorySplitAssemblyEvaluator.IndustrialOverclockSubSkillSid);
		return Homm3FactorySplitAssemblyEvaluator.TryEvaluate(
			unitSids,
			rank,
			naturalOverclock,
			industrialOverclock,
			out snapshot,
			out failReason);
	}

	internal static object TryResolveSessionHeroFromPanel(object panel)
	{
		var heroView = ReadMember(panel, GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields);
		if (heroView == null)
			return null;
		return ReadMember(heroView, GameSymbols.ImportVisuals.TooltipHeroItemSessionHeroFields);
	}

	private static bool TryResolveDataHero(object sessionHero, out DataHero dataHero, out string failReason)
	{
		dataHero = null;
		failReason = null;
		if (sessionHero is DataHero direct)
		{
			dataHero = direct;
			return true;
		}

		var candidate = ReadMember(sessionHero, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers)
			?? ReadMember(sessionHero, GameSymbols.CustomFactionLawRuntime.LogicHeroDataHeroMembers)
			?? ReadMember(sessionHero, GameSymbols.SkeletalNecromancy.LogicHeroDataHeroMembers)
			?? ReadMember(sessionHero, GameSymbols.TowerBottomlessKnowledge.LogicHeroDataHeroMembers)
			?? ReadMember(sessionHero, GameSymbols.DraconicDominion.BattleLogicHeroDataHeroMembers);
		if (candidate is DataHero nested)
		{
			dataHero = nested;
			return true;
		}

		var logicHero = ReadMember(sessionHero, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers)
			?? ReadMember(sessionHero, GameSymbols.HeroMap.SessionHeroLogicFields)
			?? ReadMember(sessionHero, GameSymbols.HeroProfile.HeroStateFields);
		if (logicHero != null && !ReferenceEquals(logicHero, sessionHero))
			return TryResolveDataHero(logicHero, out dataHero, out failReason);

		failReason = "Data.Hero unresolved from session hero type "
			+ (sessionHero.GetType().FullName ?? "?");
		return false;
	}

	private static bool TryResolveFactorySkillRank(DataHero dataHero, out int rank, out string failReason)
	{
		rank = 0;
		failReason = null;
		if (dataHero == null)
		{
			failReason = "data-Hero missing";
			return false;
		}

		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		if (skillList == null)
		{
			failReason = "HeroSkills list missing";
			return false;
		}

		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, Homm3FactorySplitAssemblyEvaluator.FactorySkillSid, StringComparison.Ordinal))
				continue;
			if (!TryReadInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers, out rank))
			{
				failReason = "Factory skill level member missing";
				return false;
			}
			if (rank < 1 || rank > 3)
			{
				failReason = "Factory skill level outside Basic/Advanced/Expert range: " + rank;
				rank = 0;
				return false;
			}
			return true;
		}

		failReason = "Factory faction skill not present";
		return false;
	}

	private static bool TryEnumerateAdventureArmySids(
		DataHero dataHero,
		out List<string> unitSids,
		out string failReason)
	{
		unitSids = null;
		failReason = null;
		var party = ReadMember(dataHero, GameSymbols.AdventureAiDecision.DataHeroPartyFieldHints);
		if (party == null)
		{
			failReason = "Data.Hero.party missing";
			return false;
		}
		var units = ReadMember(party, GameSymbols.AdventureAiDecision.DataPartyUnitsFieldHints);
		if (units == null)
		{
			failReason = "Data.Party.units missing";
			return false;
		}

		var sids = new List<string>(8);
		foreach (var unit in EnumerateObjects(units))
		{
			var sid = NormalizeSid(TryReadString(unit, GameSymbols.DraconicDominion.DataPartyUnitSidMembers));
			if (sid == null)
			{
				failReason = "adventure party unit has empty sid (DataPartyUnitSidMembers)";
				return false;
			}
			sids.Add(sid);
		}

		unitSids = sids;
		return true;
	}

	private static bool HasHeroSubSkill(DataHero dataHero, string subSkillSid)
	{
		if (dataHero == null || string.IsNullOrWhiteSpace(subSkillSid))
			return false;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
			foreach (var subSkill in EnumerateObjects(subSkills))
			{
				var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.DraconicDominion.HeroSubSkillSidMembers));
				if (string.Equals(sid, subSkillSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	private static bool TryResolveArmyStripPortrait(Component panel, out Image portrait, out string failReason)
	{
		portrait = null;
		failReason = null;
		var heroView = ReadMember(panel, GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields);
		if (heroView == null)
		{
			failReason = "BhHeroHUDPanel.heroView missing";
			return false;
		}

		portrait = DeobfInteropCompat.GetImageMember(
			heroView,
			GameSymbols.ImportVisuals.TooltipHeroItemPortraitFields);
		if (!portrait)
		{
			failReason = "BhHeroHUDPanel.heroView.heroFace missing";
			return false;
		}
		return true;
	}

	private static bool TryEnsureView(Component element, out MeterView view, out string failReason)
	{
		view = null;
		failReason = null;
		var key = element.GetInstanceID();
		if (!TryResolveArmyStripPortrait(element, out var portrait, out failReason))
			return false;
		var portraitRt = portrait.rectTransform;
		var faceParentTf = portraitRt.parent;
		var faceParent = faceParentTf != null ? faceParentTf.GetComponent<RectTransform>() : null;
		if (!faceParent || faceParent == portraitRt)
		{
			failReason = "army-strip heroFace parent RectTransform missing";
			return false;
		}

		lock (Gate)
		{
			if (ViewsByElement.TryGetValue(key, out view)
			    && view?.Root
			    && view.Root.transform.parent == faceParent)
			{
				view.Root.SetActive(true);
				PositionMeterLeftOfPortrait(view.Root.GetComponent<RectTransform>(), portraitRt, faceParent);
				return true;
			}
		}

		var existing = faceParent.Find(OverlayRootName);
		if (existing)
			UnityEngine.Object.Destroy(existing.gameObject);

		var blockWidth = IconSize + IconTextGap + CountLabelWidth;
		var blockHeight = IconSize * 2f + RowGap;
		var root = CreateUiObject(OverlayRootName, faceParent, out var rootRect, out var hit);
		root.layer = element.gameObject.layer;
		rootRect.pivot = new Vector2(1f, 0.5f);
		rootRect.sizeDelta = new Vector2(blockWidth, blockHeight);
		rootRect.localScale = Vector3.one;
		PositionMeterLeftOfPortrait(rootRect, portraitRt, faceParent);
		root.transform.SetAsLastSibling();
		hit.color = new Color(1f, 1f, 1f, 0.02f);
		hit.raycastTarget = true;

		view = new MeterView { Root = root };
		view.NaturalCount = CreateBranchRow(
			root.transform,
			"natural_row",
			EnsureLeafSprite(),
			NatureGreen,
			"0/4",
			new Vector2(0f, RowGap * 0.5f),
			element);
		view.IndustrialCount = CreateBranchRow(
			root.transform,
			"industrial_row",
			EnsureGearSprite(),
			IndustryOrangeBrown,
			"0/4",
			new Vector2(0f, -(IconSize + RowGap)),
			element,
			GearTint);

		lock (Gate)
			ViewsByElement[key] = view;
		return true;
	}

	private static TextMeshProUGUI CreateBranchRow(
		Transform parent,
		string rowName,
		Sprite iconSprite,
		Color textColor,
		string label,
		Vector2 anchoredPos,
		Component fontRoot,
		Color? iconTint = null)
	{
		var row = new GameObject(rowName);
		row.transform.SetParent(parent, false);
		var rowRt = row.AddComponent<RectTransform>();
		rowRt.anchorMin = new Vector2(0f, 0.5f);
		rowRt.anchorMax = new Vector2(0f, 0.5f);
		rowRt.pivot = new Vector2(0f, 0.5f);
		rowRt.sizeDelta = new Vector2(IconSize + IconTextGap + CountLabelWidth, IconSize);
		rowRt.anchoredPosition = anchoredPos;

		var iconGo = new GameObject("icon");
		iconGo.transform.SetParent(row.transform, false);
		var iconRt = iconGo.AddComponent<RectTransform>();
		iconRt.anchorMin = new Vector2(0f, 0.5f);
		iconRt.anchorMax = new Vector2(0f, 0.5f);
		iconRt.pivot = new Vector2(0f, 0.5f);
		iconRt.sizeDelta = new Vector2(IconSize, IconSize);
		iconRt.anchoredPosition = Vector2.zero;
		var icon = iconGo.AddComponent<Image>();
		icon.sprite = iconSprite;
		icon.preserveAspect = true;
		icon.raycastTarget = false;
		icon.color = iconTint ?? Color.white;

		var textGo = new GameObject("count");
		textGo.transform.SetParent(row.transform, false);
		var textRt = textGo.AddComponent<RectTransform>();
		textRt.anchorMin = new Vector2(0f, 0.5f);
		textRt.anchorMax = new Vector2(0f, 0.5f);
		textRt.pivot = new Vector2(0f, 0.5f);
		textRt.sizeDelta = new Vector2(CountLabelWidth, IconSize);
		textRt.anchoredPosition = new Vector2(IconSize + IconTextGap, 0f);
		var text = textGo.AddComponent<TextMeshProUGUI>();
		text.text = label;
		text.fontSize = TextSize;
		text.color = textColor;
		text.alignment = TextAlignmentOptions.MidlineLeft;
		text.raycastTarget = false;
		TryAssignDefaultTmpFont(text, fontRoot);
		return text;
	}

	private static void PositionMeterLeftOfPortrait(RectTransform meterRect, RectTransform portraitRt, RectTransform faceParent)
	{
		if (!meterRect || !portraitRt || !faceParent)
			return;

		meterRect.anchorMin = portraitRt.anchorMin;
		meterRect.anchorMax = portraitRt.anchorMax;
		meterRect.pivot = new Vector2(1f, 0.5f);
		var faceW = portraitRt.rect.width > 1f ? portraitRt.rect.width : Mathf.Abs(portraitRt.sizeDelta.x);
		if (faceW < 1f)
			faceW = IconSize * 3f;
		var blockHeight = IconSize * 2f + RowGap;
		meterRect.sizeDelta = new Vector2(IconSize + IconTextGap + CountLabelWidth, blockHeight);
		meterRect.anchoredPosition = new Vector2(
			portraitRt.anchoredPosition.x - faceW * 0.5f - BlockGap,
			portraitRt.anchoredPosition.y);
		meterRect.localRotation = Quaternion.identity;
		meterRect.localScale = Vector3.one;
	}

	private static void ApplySnapshot(MeterView view, Homm3FactorySplitAssemblyEvaluator.Snapshot snapshot)
	{
		view.Snapshot = snapshot;
		view.Root.SetActive(true);
		if (view.NaturalCount)
			view.NaturalCount.text = snapshot.NaturalTier + "/4";
		if (view.IndustrialCount)
			view.IndustrialCount.text = snapshot.IndustrialTier + "/4";
	}

	private static void Hide(object element)
	{
		if (!(element is Component component) || !component)
			return;
		var key = component.GetInstanceID();
		MeterView view;
		lock (Gate)
			ViewsByElement.TryGetValue(key, out view);
		if (view?.Root)
			view.Root.SetActive(false);
		if (key == _tooltipOwnerKey)
			HideTooltip();
	}

	internal static void TickHover()
	{
		MeterView hovered = null;
		var hoveredKey = -1;
		var mouse = Input.mousePosition;
		lock (Gate)
		{
			foreach (var pair in ViewsByElement)
			{
				var view = pair.Value;
				if (view?.Root == null || !view.Root.activeInHierarchy || view.Snapshot == null)
					continue;
				var rect = view.Root.GetComponent<RectTransform>();
				if (!rect)
					continue;
				if (!RectTransformUtility.RectangleContainsScreenPoint(rect, mouse))
					continue;
				hovered = view;
				hoveredKey = pair.Key;
				break;
			}
		}

		if (hovered != null)
		{
			if (_tooltipOwnerKey != hoveredKey)
				ShowTooltip(hovered, hoveredKey);
			else
				PositionTooltip(hovered);
			return;
		}

		if (_tooltipOwnerKey >= 0)
			HideTooltip();
	}

	private static void ShowTooltip(MeterView view, int ownerKey)
	{
		if (view?.Snapshot == null || !view.Root)
			return;
		EnsureTooltip();
		if (!_sharedTooltip || !_sharedTooltipText)
			return;
		_sharedTooltipText.text = Homm3FactorySplitAssemblyEvaluator.BuildTooltipText(view.Snapshot);
		TryAssignDefaultTmpFont(_sharedTooltipText, view.Root.transform);
		_tooltipOwnerKey = ownerKey;
		PositionTooltip(view);
		_sharedTooltip.SetActive(true);
	}

	private static void PositionTooltip(MeterView view)
	{
		if (view?.Root == null || !_sharedTooltip)
			return;
		var canvas = view.Root.GetComponentInParent<Canvas>();
		var tipRect = _sharedTooltip.GetComponent<RectTransform>();
		var meterRect = view.Root.GetComponent<RectTransform>();
		if (!tipRect || !meterRect || !canvas)
			return;

		var canvasRect = canvas.GetComponent<RectTransform>();
		if (!canvasRect)
			return;

		_sharedTooltip.transform.SetParent(canvas.transform, false);
		_sharedTooltip.transform.SetAsLastSibling();
		var lossy = canvas.transform.lossyScale;
		var sx = Math.Abs(lossy.x) > 0.0001f ? 1f / lossy.x : 1f;
		var sy = Math.Abs(lossy.y) > 0.0001f ? 1f / lossy.y : 1f;
		tipRect.localScale = new Vector3(sx, sy, 1f);
		tipRect.anchorMin = new Vector2(0.5f, 0.5f);
		tipRect.anchorMax = new Vector2(0.5f, 0.5f);
		tipRect.pivot = new Vector2(1f, 0f);

		var meterCorners = new Vector3[4];
		meterRect.GetWorldCorners(meterCorners);
		var anchorWorld = meterCorners[1];
		Camera cam = null;
		if (canvas.renderMode != RenderMode.ScreenSpaceOverlay)
			cam = canvas.worldCamera != null ? canvas.worldCamera : Camera.main;
		var screenPoint = RectTransformUtility.WorldToScreenPoint(cam, anchorWorld);
		if (RectTransformUtility.ScreenPointToLocalPointInRectangle(canvasRect, screenPoint, cam, out var localPoint))
			tipRect.anchoredPosition = localPoint + new Vector2(-6f, 8f);
	}

	private static void HideTooltip()
	{
		_tooltipOwnerKey = -1;
		if (_sharedTooltip)
			_sharedTooltip.SetActive(false);
	}

	private static void EnsureTooltip()
	{
		if (_sharedTooltip)
			return;
		_sharedTooltip = CreateUiObject(TooltipRootName, null, out var rect, out var bg);
		rect.sizeDelta = new Vector2(220f, 140f);
		bg.color = new Color(0.16f, 0.11f, 0.07f, 0.94f);
		bg.raycastTarget = false;

		var textGo = new GameObject("text");
		var textRect = textGo.AddComponent<RectTransform>();
		textRect.SetParent(_sharedTooltip.transform, false);
		textRect.anchorMin = new Vector2(0f, 0f);
		textRect.anchorMax = new Vector2(1f, 1f);
		textRect.offsetMin = new Vector2(8f, 8f);
		textRect.offsetMax = new Vector2(-8f, -8f);
		_sharedTooltipText = textGo.AddComponent<TextMeshProUGUI>();
		_sharedTooltipText.fontSize = 12f;
		_sharedTooltipText.color = new Color(0.95f, 0.88f, 0.72f, 1f);
		_sharedTooltipText.alignment = TextAlignmentOptions.TopLeft;
		_sharedTooltipText.enableWordWrapping = true;
		_sharedTooltipText.raycastTarget = false;
		TryAssignDefaultTmpFont(_sharedTooltipText, null);
		_sharedTooltip.SetActive(false);
	}

	private static Sprite EnsureLeafSprite()
	{
		if (_leafSprite)
			return _leafSprite;
		const int w = 32;
		const int h = 32;
		var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
		var clear = new Color(0f, 0f, 0f, 0f);
		var fill = new Color(0.18f, 0.70f, 0.24f, 1f);
		var stroke = new Color(0.10f, 0.48f, 0.14f, 1f);
		for (var y = 0; y < h; y++)
		{
			for (var x = 0; x < w; x++)
				tex.SetPixel(x, y, clear);
		}
		for (var y = 4; y < h - 4; y++)
		{
			for (var x = 6; x < w - 4; x++)
			{
				var nx = (x - 10f) / 14f;
				var ny = (y - 10f) / 12f;
				var body = nx * nx + ny * ny * 1.35f;
				if (body <= 1f)
					tex.SetPixel(x, y, fill);
				else if (body <= 1.15f)
					tex.SetPixel(x, y, stroke);
			}
		}
		for (var y = 8; y < h - 8; y++)
		{
			var t = (y - 8f) / (h - 16f);
			var x = Mathf.RoundToInt(Mathf.Lerp(15f, 24f, t));
			if (x >= 0 && x < w)
				tex.SetPixel(x, y, stroke);
		}
		tex.Apply();
		tex.filterMode = FilterMode.Bilinear;
		_leafSprite = Sprite.Create(tex, new Rect(0f, 0f, w, h), new Vector2(0.5f, 0.5f), 100f);
		return _leafSprite;
	}

	private static Sprite EnsureGearSprite()
	{
		if (_gearSprite)
			return _gearSprite;
		const int w = 32;
		const int h = 32;
		var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
		var clear = new Color(0f, 0f, 0f, 0f);
		var fill = new Color(0.78f, 0.44f, 0.10f, 1f);
		var stroke = new Color(0.52f, 0.28f, 0.06f, 1f);
		var cx = 15.5f;
		var cy = 15.5f;
		for (var y = 0; y < h; y++)
		{
			for (var x = 0; x < w; x++)
			{
				var dx = x - cx;
				var dy = y - cy;
				var dist = Mathf.Sqrt(dx * dx + dy * dy);
				var angle = Mathf.Atan2(dy, dx);
				var tooth = Mathf.Cos(angle * 8f);
				var outer = 11.5f + tooth * 2.2f;
				var inner = 5.5f;
				if (dist <= inner)
					tex.SetPixel(x, y, clear);
				else if (dist <= outer - 0.8f)
					tex.SetPixel(x, y, fill);
				else if (dist <= outer)
					tex.SetPixel(x, y, stroke);
				else
					tex.SetPixel(x, y, clear);
			}
		}
		tex.Apply();
		tex.filterMode = FilterMode.Bilinear;
		_gearSprite = Sprite.Create(tex, new Rect(0f, 0f, w, h), new Vector2(0.5f, 0.5f), 100f);
		return _gearSprite;
	}

	private static void TryAssignDefaultTmpFont(TextMeshProUGUI text, Component searchRoot)
	{
		if (!text || text.font)
			return;
		try
		{
			if (searchRoot)
			{
				var canvas = searchRoot.GetComponentInParent<Canvas>();
				var donors = canvas
					? canvas.GetComponentsInChildren<TextMeshProUGUI>(true)
					: searchRoot.GetComponentsInChildren<TextMeshProUGUI>(true);
				for (var i = 0; i < donors.Length; i++)
				{
					var donor = donors[i];
					if (donor == null || !donor.font || donor == text)
						continue;
					text.font = donor.font;
					return;
				}
			}
		}
		catch
		{
		}
	}

	private static GameObject CreateUiObject(string name, Transform parent, out RectTransform rect, out Image image)
	{
		var go = new GameObject(name);
		if (parent)
			go.transform.SetParent(parent, false);
		rect = go.AddComponent<RectTransform>();
		image = go.AddComponent<Image>();
		return go;
	}

	private static Type ResolveRequiredType(string fullName, string symbolId)
	{
		var type = AccessTools.TypeByName(fullName) ?? typeof(TransferSide).Assembly.GetType(fullName);
		if (type != null)
			return type;
		throw new MissingMemberException(symbolId + " type not found: " + fullName);
	}

	private static void PatchPostfix(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = AccessTools.Method(typeof(Homm3FactorySplitAssemblyArmyStripHud), postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}

	private static object ReadMember(object target, IEnumerable<string> names)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (TryReadMemberDeclared(type, target, name, out var value) && value != null)
				return value;
		}
		return null;
	}

	private static bool TryReadMemberDeclared(Type type, object target, string name, out object value)
	{
		value = null;
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			const BindingFlags flags =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

			FieldInfo field = null;
			try { field = cur.GetField(name, flags); }
			catch (AmbiguousMatchException) { field = null; }
			catch { field = null; }
			if (field != null)
			{
				try
				{
					value = field.GetValue(target);
					return true;
				}
				catch
				{
				}
			}

			PropertyInfo property = null;
			try { property = cur.GetProperty(name, flags); }
			catch (AmbiguousMatchException) { property = null; }
			catch { property = null; }
			if (property != null && property.CanRead && property.GetIndexParameters().Length == 0)
			{
				try
				{
					value = property.GetValue(target, null);
					return true;
				}
				catch
				{
				}
			}

			MethodInfo method = null;
			try { method = cur.GetMethod(name, flags, null, Type.EmptyTypes, null); }
			catch (AmbiguousMatchException) { method = null; }
			catch { method = null; }
			if (method != null && method.ReturnType != typeof(void) && !method.IsStatic)
			{
				try
				{
					value = method.Invoke(target, Array.Empty<object>());
					return true;
				}
				catch
				{
				}
			}
		}

		return false;
	}

	private static string TryReadString(object target, IEnumerable<string> names)
	{
		return ReadMember(target, names) as string;
	}

	private static bool TryReadInt(object target, IEnumerable<string> names, out int value)
	{
		value = 0;
		var raw = ReadMember(target, names);
		if (raw is int i)
		{
			value = i;
			return true;
		}
		return false;
	}

	private static IEnumerable<object> EnumerateObjects(object list)
	{
		if (list == null)
			yield break;

		var type = list.GetType();
		var count = TryReadCount(list, type);
		var indexer = ResolveIntIndexer(type);
		if (count != null && count.Value > 0 && indexer != null)
		{
			for (var i = 0; i < count.Value; i++)
			{
				object item = null;
				try { item = indexer.Invoke(list, new object[] { i }); }
				catch { }
				if (item != null)
					yield return item;
			}
			yield break;
		}

		if (list is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
		}
	}

	private static int? TryReadCount(object value, Type type)
	{
		if (value == null || type == null)
			return null;
		if (TryReadMemberDeclared(type, value, "Count", out var raw) && raw is int propertyCount)
			return propertyCount;
		if (TryReadMemberDeclared(type, value, "get_Count", out var viaGetter) && viaGetter is int methodCount)
			return methodCount;
		return null;
	}

	private static MethodInfo ResolveIntIndexer(Type type)
	{
		if (type == null)
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType == typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length == 1
			    && parameters[0].ParameterType == typeof(int)
			    && (string.Equals(method.Name, "get_Item", StringComparison.Ordinal)
			        || string.Equals(method.Name, "get_ItemOf", StringComparison.Ordinal)))
				return method;
		}
		return null;
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "null";
		var parameters = method.GetParameters();
		var names = new string[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
			names[i] = parameters[i].ParameterType.Name;
		return method.DeclaringType?.FullName + "." + method.Name + "(" + string.Join(",", names) + ")";
	}

	private static void LogLimited(string message)
	{
		if (_loggedSkips++ >= 48)
			return;
		_log?.LogWarning("HoMM3 Factory Split Assembly HUD: " + message);
	}
}

/// <summary>DontDestroyOnLoad hover pump — per-overlay LateUpdate is unreliable on Il2Cpp-injected UI.</summary>
public sealed class Homm3FactorySplitAssemblyHudHoverPump : MonoBehaviour
{
	private static bool _typeRegistered;
	private static bool _created;

	public Homm3FactorySplitAssemblyHudHoverPump(IntPtr ptr) : base(ptr) { }

	internal static bool Ensure(ManualLogSource log)
	{
		if (_created)
			return true;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FactorySplitAssemblyHudHoverPump>();
				_typeRegistered = true;
			}
			var go = new GameObject("Homm3FactorySplitAssemblyHudHoverPump");
			go.AddComponent<Homm3FactorySplitAssemblyHudHoverPump>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_created = true;
			log?.LogInfo("HoMM3 Factory Split Assembly army-strip HUD hover pump registered.");
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning(
				"HoMM3 Factory Split Assembly army-strip HUD hover pump failed: "
				+ ex.GetType().Name
				+ ": "
				+ ex.Message);
			return false;
		}
	}

	private void LateUpdate()
	{
		Homm3FactorySplitAssemblyArmyStripHud.TickHover();
	}
}
