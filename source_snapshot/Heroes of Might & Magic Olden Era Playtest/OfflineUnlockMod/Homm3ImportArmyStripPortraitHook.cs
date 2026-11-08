using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Pick;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Persistent army-slot portrait swap for HoMM3-imported unit SIDs.
/// Covers the following surfaces:
/// <list type="bullet">
/// <item><see cref="BhUnitSlot"/> (<c>Hex.Pick</c>) — lobby / army-pick screen;
///   <c>lrt(Mode, sid, _, _)</c> is the binder; replaces <c>portrait</c> Image and hides <c>random</c> placeholder.</item>
/// <item><see cref="Hex.Session.Hud.BhUnitUI"/> (<c>Hex.Session.Hud</c>) — in-game bottom army strip per-slot;
///   <c>Start()</c> postfix reapplies portrait from <c>cmko.sid</c> (covers Init, pool-reuse, and re-population).</item>
/// <item><see cref="Hex.Session.Hud.BhUnitSlots"/> (<c>Hex.Session.Hud</c>) — in-game army strip panel;
///   <c>Init(dwp)</c> populates the whole strip; postfix iterates all <c>BhUnitUI</c> slots and applies portraits.</item>
/// <item><see cref="Hex.UI.City.BhHeroWithPartyCityView"/> — city garrison/visitor panel;
///   <c>toj(dwp)</c> is the binder; postfix applies portraits to <c>unitsPanel</c> slots.</item>
/// </list>
/// Sprites come from <see cref="Homm3ImportPortraitSpriteCache"/>.
/// </summary>
internal static class Homm3ImportArmyStripPortraitHook
{
	private static bool _patched;
	private static int _loggedReplace;
	private static int _loggedMiss;
	private static int _loggedKeyNotFound;

	internal static void TryRegisterReleaseSafeUiSlice(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		var patched = 0;

		try
		{
			var lrt = FindPickUnitSlotBinder();
			if (lrt != null)
			{
				h.Patch(lrt, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixLrt)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhUnitSlot." + lrt.Name + " patch registered.");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitSlot bind method not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitSlot bind patch failed: " + ex.Message);
		}

		patched += PatchSummaryCardBinders(h, log);

		try
		{
			var uiStart = AccessTools.Method(typeof(Hex.Session.Hud.BhUnitUI), "Start");
			if (uiStart != null)
			{
				h.Patch(uiStart, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhUnitUIStart)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhUnitUI.Start postfix registered (released cnev/vuk data path).");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitUI.Start not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitUI.Start patch failed: " + ex.Message);
		}

		try
		{
			var uiInit = FindMethodByNameAndArity(typeof(Hex.Session.Hud.BhUnitUI), "Init", 6);
			if (uiInit != null)
			{
				h.Patch(uiInit, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhUnitUIInit)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhUnitUI.Init postfix registered (released Unit arg path).");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitUI.Init/6 not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitUI.Init patch failed: " + ex.Message);
		}

		try
		{
			var slotsInit = AccessTools.Method(typeof(Hex.Session.Hud.BhUnitSlots), "Init");
			if (slotsInit != null)
			{
				h.Patch(slotsInit, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhUnitSlotsInit)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhUnitSlots.Init patch registered (released cnfi/wbv data path).");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitSlots.Init not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUnitSlots.Init patch failed: " + ex.Message);
		}

		patched += PatchCityHeroWithPartyBinders(h, log);
		patched += PatchUnitWindowPartySelectorBinders(h, log);

		try
		{
			var ghkMethods = FindHeroHudRefreshMethods();
			if (ghkMethods.Count > 0)
			{
				foreach (var ghk in ghkMethods)
				{
					h.Patch(ghk, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhHeroHUDPanelGhk)));
					patched++;
					log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhHeroHUDPanel." + ghk.Name + " patch registered.");
				}
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhHeroHUDPanel refresh method not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhHeroHUDPanel refresh patch failed: " + ex.Message);
		}

		if (patched > 0)
			log?.LogInfo("Homm3Import: release-safe army-strip UI slice registered on " + patched + " method(s).");
		else
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: no methods registered.");

		_patched = true;
	}

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		var patched = 0;

		// Lobby / pick screen slot
		try
		{
			var lrt = FindPickUnitSlotBinder();
			if (lrt != null)
			{
				h.Patch(lrt, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixLrt)));
				patched++;
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip portrait: BhUnitSlot.lrt not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip portrait: BhUnitSlot.lrt patch failed: " + ex.Message);
		}

		// In-game army strip per-slot: BhUnitUI.Start — fires on Enable (covers Init, pool-reuse, re-pop)
		// Check __instance type at runtime to avoid patching every MonoBehaviour.Start in the game.
		try
		{
			var uiStart = AccessTools.Method(typeof(Hex.Session.Hud.BhUnitUI), "Start");
			if (uiStart != null)
			{
				h.Patch(uiStart, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhUnitUIStart)));
				patched++;
				log?.LogInfo("Homm3Import army-strip portrait: BhUnitUI.Start postfix registered.");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip portrait: BhUnitUI.Start not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip portrait: BhUnitUI.Start patch failed: " + ex.Message);
		}

		// In-game army strip panel: BhUnitSlots.Init(dwp) — iterate all slots after panel population
		try
		{
			var slotsInit = AccessTools.Method(typeof(Hex.Session.Hud.BhUnitSlots), "Init");
			if (slotsInit != null)
			{
				h.Patch(slotsInit, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhUnitSlotsInit)));
				patched++;
				log?.LogInfo("Homm3Import army-strip portrait: BhUnitSlots.Init patch registered.");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip portrait: BhUnitSlots.Init not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip portrait: BhUnitSlots.Init patch failed: " + ex.Message);
		}

		// In-game army strip panel: BhHeroHUDPanel.ghk() — OnShow virtual (slot 9), fires when HUD becomes visible
		try
		{
			var ghk = GameMember.FindFirstMethodByNames(
				typeof(Hex.Session.Hud.BhHeroHUDPanel),
				Type.EmptyTypes,
				GameSymbols.ImportVisuals.HeroHudPanelRefresh);
			if (ghk != null)
			{
				h.Patch(ghk, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhHeroHUDPanelGhk)));
				patched++;
				log?.LogInfo("Homm3Import army-strip portrait: BhHeroHUDPanel." + ghk.Name + " patch registered.");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip portrait: BhHeroHUDPanel legacy refresh not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip portrait: BhHeroHUDPanel legacy refresh patch failed: " + ex.Message);
		}

		// City garrison/visitor panel: BhHeroWithPartyCityView.toj(dwp)
		try
		{
			var toj = GameMember.FindFirstMethodByNames(
				typeof(Hex.UI.City.BhHeroWithPartyCityView),
				new Type[1],
				GameSymbols.ImportVisuals.CityHeroWithPartyRefresh);
			if (toj != null)
			{
				h.Patch(toj, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhHeroWithPartyCityViewToj)));
				patched++;
				log?.LogInfo("Homm3Import army-strip portrait: BhHeroWithPartyCityView." + toj.Name + " patch registered.");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip portrait: BhHeroWithPartyCityView legacy refresh not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip portrait: BhHeroWithPartyCityView legacy refresh patch failed: " + ex.Message);
		}

		// Battle turn-order queue: BhTurnView.UpdateView(Unit, TurnState, bool)
		// Postfix applies portrait; finalizer suppresses the KeyNotFoundException that spams when
		// h3_* unit SIDs are not found in the vanilla portrait/config dictionary.
		try
		{
			var updateView = AccessTools.Method(typeof(BhTurnView), "UpdateView");
			if (updateView != null)
			{
				h.Patch(updateView,
					postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhTurnViewUpdateView)),
					finalizer: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(FinalizerBhTurnViewUpdateView)));
				patched++;
				log?.LogInfo("Homm3Import army-strip portrait: BhTurnView.UpdateView postfix+finalizer registered.");
			}
			else
			{
				log?.LogWarning("Homm3Import army-strip portrait: BhTurnView.UpdateView not found.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip portrait: BhTurnView.UpdateView patch failed: " + ex.Message);
		}

		if (patched > 0)
			log?.LogInfo("Homm3Import: Harmony postfix on " + patched + " army-strip portrait method(s).");

		_patched = true;
	}

	// ── Lobby / pick screen ────────────────────────────────────────────────

	private static List<MethodInfo> FindHeroHudRefreshMethods()
	{
		var methods = new List<MethodInfo>();
		var type = typeof(Hex.Session.Hud.BhHeroHUDPanel);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		foreach (var name in GameSymbols.ImportVisuals.HeroHudPanelRefresh.NameHints)
		{
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && !methods.Contains(method))
				methods.Add(method);
		}
		if (methods.Count == 0)
		{
			foreach (var method in GameMember.FindParameterlessReturning(
			         type,
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

	private static MethodInfo FindPickUnitSlotBinder()
	{
		foreach (var typeName in GameSymbols.CustomGame.UnitSlotTypeHints)
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
				continue;
			foreach (var methodName in GameSymbols.CustomGame.UnitSlotBind.NameHints)
			{
				var method = FindMethodByNameAndArity(type, methodName, 4);
				if (method != null)
					return method;
			}
			var shapeMatch = GameMember.FindFirstMethod(
				type,
				typeof(void),
				new[] { null, typeof(string), typeof(int), typeof(int) },
				GameSymbols.CustomGame.UnitSlotBind);
			if (shapeMatch != null)
				return shapeMatch;
		}
		return null;
	}

	private static int PatchSummaryCardBinders(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		foreach (var methodName in GameSymbols.ImportVisuals.SummaryCardHeroBind.NameHints)
		{
			try
			{
				var method = FindRuntimeMethodByNameAndArity("Hex.Pick.BhSummaryCard", methodName, -1);
				if (method == null)
					continue;
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixSummaryCardBind)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhSummaryCard." + method.Name + " patch registered.");
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhSummaryCard." + methodName + " patch failed: " + ex.Message);
			}
		}
		if (patched == 0)
		{
			var cardType = FindRuntimeType("Hex.Pick.BhSummaryCard");
			var heroConfigType = FindRuntimeType("Hex.Configs.HeroConfig");
			var method = cardType != null && heroConfigType != null
				? GameMember.FindFirstMethod(
					cardType,
					typeof(void),
					new[] { heroConfigType, typeof(string) },
					GameSymbols.ImportVisuals.SummaryCardHeroBind)
				: null;
			if (method != null)
			{
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixSummaryCardBind)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhSummaryCard." + method.Name + " shape patch registered.");
			}
		}
		if (patched == 0)
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhSummaryCard bind method not found.");
		return patched;
	}

	private static int PatchCityHeroWithPartyBinders(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		foreach (var methodName in GameSymbols.ImportVisuals.CityHeroWithPartyRefresh.NameHints)
		{
			try
			{
				var method = FindRuntimeMethodByNameAndArity("Hex.UI.City.BhHeroWithPartyCityView", methodName, -1);
				if (method == null)
					continue;
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhHeroWithPartyCityViewToj)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhHeroWithPartyCityView." + method.Name + " patch registered.");
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhHeroWithPartyCityView." + methodName + " patch failed: " + ex.Message);
			}
		}
		if (patched == 0)
		{
			var cityViewType = FindRuntimeType("Hex.UI.City.BhHeroWithPartyCityView");
			if (cityViewType != null)
			{
				foreach (var method in GameMember.FindMethodsByNames(
				         cityViewType,
				         null,
				         GameSymbols.ImportVisuals.CityHeroWithPartyRefresh))
				{
					if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
						continue;
					h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixBhHeroWithPartyCityViewToj)));
					patched++;
					log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhHeroWithPartyCityView." + method.Name + " shape patch registered.");
				}
			}
		}
		if (patched == 0)
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhHeroWithPartyCityView bind method not found.");
		return patched;
	}

	private static int PatchUnitWindowPartySelectorBinders(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		try
		{
			var type = FindRuntimeType(GameSymbols.UnitPreview.PartySelectorSlotType);
			if (type == null)
			{
				log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUpgradeUnitSlot type not found.");
				return 0;
			}

			foreach (var methodName in GameSymbols.UnitPreview.PartySelectorSlotUnitBind.NameHints)
			{
				var method = FindMethodByNameAndArity(type, methodName, 7);
				if (method == null)
					continue;
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixUnitWindowPartySelectorUnitBind)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhUpgradeUnitSlot." + method.Name + " unit bind patch registered.");
			}

			foreach (var methodName in GameSymbols.UnitPreview.PartySelectorSlotSidBind.NameHints)
			{
				var method = FindMethodByNameAndArity(type, methodName, 5);
				if (method == null)
					continue;
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportArmyStripPortraitHook), nameof(PostfixUnitWindowPartySelectorSidBind)));
				patched++;
				log?.LogInfo("Homm3Import army-strip release-safe UI slice: BhUpgradeUnitSlot." + method.Name + " sid bind patch registered.");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUpgradeUnitSlot bind patch failed: " + ex.Message);
		}
		if (patched == 0)
			log?.LogWarning("Homm3Import army-strip release-safe UI slice: BhUpgradeUnitSlot bind methods not found.");
		return patched;
	}

	// BhUnitSlot(Hex.Pick).lrt(Mode, string sid, int, int)
	private static void PostfixLrt(BhUnitSlot __instance, BhUnitSlot.Mode a, string b)
	{
		if (__instance == null || string.IsNullOrWhiteSpace(b))
			return;
		if (a == BhUnitSlot.Mode.Empty)
			return;
		var spriteSid = ResolvePortraitSid(b);
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(spriteSid, out var sprite) || sprite == null)
			return;
		var portrait = __instance.portrait;
		if (portrait != null)
		{
			portrait.sprite = sprite;
			portrait.preserveAspect = true;
			portrait.enabled = true;
		}
		var random = __instance.random;
		if (random != null)
			random.enabled = false;
		var shadow = __instance.shadow;
		if (shadow != null)
			shadow.enabled = false;
		LogReplace("BhUnitSlot.lrt", spriteSid, sprite);
	}

	private static void PostfixSummaryCardBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var list = TryGetMemberValue(__instance, "unitSlots");
			if (list == null)
				return;
			var squadSids = ExtractHeroStartSquadSids(__args != null && __args.Length > 0 ? __args[0] : null);
			var checkedSlots = 0;
			foreach (var item in EnumerateIl2CppList(list))
			{
				if (item is not BhUnitSlot slot)
					continue;
				var sid = checkedSlots < squadSids.Count ? squadSids[checkedSlots] : null;
				if (string.IsNullOrWhiteSpace(sid))
					sid = TryInferPickSlotSid(slot);
				if (!string.IsNullOrWhiteSpace(sid))
					ApplyToPickUnitSlot(slot, sid, FormatMethod(__originalMethod));
				checkedSlots++;
			}
			LogDiagnostic("Homm3Import army-strip portrait: BhSummaryCard checked unitSlots=" + checkedSlots + " for " + FormatMethod(__originalMethod) + ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import army-strip portrait: BhSummaryCard postfix failed: " + ex.Message);
		}
	}

	private static void PostfixUnitWindowPartySelectorUnitBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var unit = __args != null && __args.Length > 0 ? __args[0] : null;
			var sid = ExtractSid(unit) ?? ExtractSid(TryGetFirstMemberOrNoArg(__instance, GameSymbols.UnitPreview.PartySelectorSlotUnitFields));
			ApplyToUnitWindowPartySelectorSlot(__instance, sid, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import unit-window party selector portrait: unit bind postfix failed: " + ex.Message);
		}
	}

	private static void PostfixUnitWindowPartySelectorSidBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var sid = __args != null && __args.Length > 0 ? __args[0] as string : null;
			if (string.IsNullOrWhiteSpace(sid))
				sid = TryGetFirstStringMemberOrNoArg(__instance, GameSymbols.UnitPreview.PartySelectorSlotSidFields);
			ApplyToUnitWindowPartySelectorSlot(__instance, sid, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import unit-window party selector portrait: sid bind postfix failed: " + ex.Message);
		}
	}

	// ── In-game army strip — per-slot ─────────────────────────────────────

	// BhUnitUI.Start() — fires on first Enable; cmko is already populated by Init.
	// This catches Init data, pool-reused slots, and re-population after enable.
	private static void PostfixBhUnitUIStart(Hex.Session.Hud.BhUnitUI __instance)
	{
		if (__instance == null)
			return;
		try
		{
			var dataUnit = TryGetFirstMemberOrNoArg(__instance, GameSymbols.ImportVisuals.UnitUiDataUnitMembers);
			if (dataUnit == null)
				return;
			var sid = ExtractSid(dataUnit);
			if (string.IsNullOrWhiteSpace(sid))
				return;
			ApplyToUnitUI(__instance, sid, "BhUnitUI.Start");
		}
		catch { }
	}

	private static void PostfixBhUnitUIInit(Hex.Session.Hud.BhUnitUI __instance, object __0)
	{
		if (__instance == null)
			return;
		var sid = ExtractSid(__0);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		ApplyToUnitUI(__instance, sid, "BhUnitUI.Init");
	}

	// ── In-game army strip — panel-level ──────────────────────────────────

	// BhUnitSlots.Init(dwp _party) — full strip population; iterate list after init
	private static void PostfixBhUnitSlotsInit(Hex.Session.Hud.BhUnitSlots __instance)
	{
		LogDiagnostic("Homm3Import army-strip portrait: BhUnitSlots.Init postfix fired.");
		ApplyPortraitsToSlots(__instance, "BhUnitSlots.Init");
	}

	// BhHeroHUDPanel.ghk() — OnShow virtual override; panel just became visible
	private static void PostfixBhHeroHUDPanelGhk(Hex.Session.Hud.BhHeroHUDPanel __instance)
	{
		LogDiagnostic("Homm3Import army-strip portrait: BhHeroHUDPanel.ghk postfix fired.");
		if (__instance == null)
			return;
		var slots = TryGetFirstMemberOrNoArg(__instance, GameSymbols.ImportVisuals.HeroHudPanelUnitSlotsMembers) as Hex.Session.Hud.BhUnitSlots;
		ApplyPortraitsToSlots(slots, "BhHeroHUDPanel.ghk");
	}

	// BhHeroWithPartyCityView.toj(dwp _party) — city garrison/visitor panel population
	private static void PostfixBhHeroWithPartyCityViewToj(Hex.UI.City.BhHeroWithPartyCityView __instance)
	{
		LogDiagnostic("Homm3Import army-strip portrait: BhHeroWithPartyCityView.toj postfix fired.");
		if (__instance == null)
			return;
		Hex.Session.Hud.BhUnitSlots slots;
		try { slots = __instance.unitsPanel; } catch { return; }
		ApplyPortraitsToSlots(slots, "BhHeroWithPartyCityView.toj");
	}

	private static void ApplyPortraitsToSlots(Hex.Session.Hud.BhUnitSlots slots, string source)
	{
		if (slots == null)
			return;
		try
		{
			var list = TryGetFirstMemberOrNoArg(slots, GameSymbols.ImportVisuals.UnitSlotsListMembers);
			if (list == null)
			{
				LogDiagnostic("Homm3Import army-strip portrait: active slot list is null (" + source + ").");
				return;
			}
			var i = 0;
			foreach (var item in EnumerateIl2CppList(list))
			{
				try
				{
					var ya = item as Hex.Session.Hud.BhUnitUI;
					if (ya == null)
						continue;
					var dataUnit = TryGetFirstMemberOrNoArg(ya, GameSymbols.ImportVisuals.UnitUiDataUnitMembers);
					if (dataUnit == null)
						continue;
					var sid = ExtractSid(dataUnit);
					if (string.IsNullOrWhiteSpace(sid))
						continue;
					ApplyToUnitUI(ya, sid, source);
				}
				catch { }
				i++;
			}
			LogDiagnostic("Homm3Import army-strip portrait: active slots checked=" + i + " (" + source + ").");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import army-strip portrait: ApplyPortraitsToSlots threw: " + ex.Message);
		}
	}

	// ── Shared helpers ────────────────────────────────────────────────────

	private static void ApplyToUnitUI(Hex.Session.Hud.BhUnitUI ya, string sid, string source)
	{
		var spriteSid = ResolvePortraitSid(sid);
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(spriteSid, out var sprite) || sprite == null)
		{
			LogUiCardDiagnostic(source, "missing-sprite", "sid='" + sid + "' spriteSid='" + spriteSid + "'");
			if (Homm3DiagnosticFlags.IsEnabled("homm3_army_strip_diag.flag") && _loggedMiss < 20)
			{
				_loggedMiss++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import army-strip portrait: no sprite for sid='" + sid + "' source=" + source + ".");
			}
			return;
		}
		var icon = ya.icon;
		if (icon == null)
			return;
		icon.sprite = sprite;
		icon.preserveAspect = true;
		icon.enabled = true;
		LogReplace(source, spriteSid, sprite);
	}

	private static void ApplyToPickUnitSlot(BhUnitSlot slot, string sid, string source)
	{
		if (slot == null || string.IsNullOrWhiteSpace(sid))
			return;
		var spriteSid = ResolvePortraitSid(sid);
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(spriteSid, out var sprite) || sprite == null)
			return;
		try
		{
			var portrait = slot.portrait;
			if (portrait != null)
			{
				portrait.sprite = sprite;
				portrait.preserveAspect = true;
				portrait.enabled = true;
			}
			var random = slot.random;
			if (random != null)
				random.enabled = false;
			var shadow = slot.shadow;
			if (shadow != null)
				shadow.enabled = false;
			LogReplace(source, spriteSid, sprite);
		}
		catch { }
	}

	// ── Battle turn-order queue ───────────────────────────────────────────

	// BhTurnView.UpdateView(Unit _unit, TurnState _turnState, bool _withAnim)
	private static void PostfixBhTurnViewUpdateView(BhTurnView __instance, [HarmonyArgument(0)] Unit unit)
	{
		if (__instance == null || unit == null)
			return;
		var sid = ExtractSid(unit);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		ApplyToTurnView(__instance, sid);
	}

	// Finalizer: catch the KeyNotFoundException thrown when h3_* SIDs are absent from vanilla dicts.
	private static Exception FinalizerBhTurnViewUpdateView(
		Exception __exception,
		BhTurnView __instance,
		[HarmonyArgument(0)] Unit unit)
	{
		if (__exception == null)
			return null;
		if (!IsKeyNotFoundException(__exception))
			return __exception;

		if (_loggedKeyNotFound < 5)
		{
			_loggedKeyNotFound++;
			Plugin.LogSource?.LogWarning(
				"Homm3Import turn-order: KeyNotFoundException suppressed in BhTurnView.UpdateView — "
				+ __exception.Message);
		}
		if (__instance != null && unit != null)
		{
			var sid = ExtractSid(unit);
			if (!string.IsNullOrWhiteSpace(sid))
				ApplyToTurnView(__instance, sid);
		}
		return null; // suppress
	}

	private static void ApplyToTurnView(BhTurnView instance, string sid)
	{
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out var sprite) || sprite == null)
			return;
		try
		{
			var pic = instance.unitPic;
			if (pic == null)
				return;
			pic.sprite = sprite;
			pic.preserveAspect = true;
			pic.enabled = true;
			LogReplace("BhTurnView.UpdateView", sid, sprite);
		}
		catch { }
	}

	private static bool IsKeyNotFoundException(Exception ex)
	{
		for (var e = ex; e != null; e = e.InnerException)
		{
			if (e.GetType().Name == "KeyNotFoundException")
				return true;
		}
		return ex.ToString().IndexOf("KeyNotFoundException", StringComparison.Ordinal) >= 0;
	}

	// ── SID extraction (battle Unit + data Data.Unit) ─────────────────────

	private static string ExtractSid(Unit unit)
	{
		if (unit == null)
			return null;
		return ExtractBattleUnitSidBySymbols(unit);
	}

	private static string ExtractSid(object unit)
	{
		if (unit == null)
			return null;

		if (unit is Unit battleUnit)
			return ExtractBattleUnitSidBySymbols(battleUnit);

		var sid = DeobfInteropCompat.GetUnitPortraitSid(unit)
		          ?? TryGetStringMember(unit, "sid")
		          ?? TryGetStringMember(unit, "configSid")
		          ?? TryGetStringMember(unit, "unitSid")
		          ?? TryGetStringMember(TryGetMemberValue(unit, "cnuj"), "id")
		          ?? TryGetStringMember(TryInvokeNoArg(unit, "bget"), "id");
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string ExtractBattleUnitSidBySymbols(object unit)
	{
		var transfer = TryGetFirstMemberOrNoArg(unit, GameSymbols.BattleUi.UnitTransferFields);
		var sid = DeobfInteropCompat.GetUnitPortraitSid(transfer)
		          ?? TryGetStringMember(transfer, "configSid")
		          ?? TryGetStringMember(transfer, "sid")
		          ?? TryGetStringMember(transfer, "id");
		if (!string.IsNullOrWhiteSpace(sid))
			return sid.Trim();

		var config = TryGetFirstMemberOrNoArg(unit, GameSymbols.BattleUi.UnitConfigIdFields);
		sid = DeobfInteropCompat.GetConfigElementId(config)
		      ?? TryGetStringMember(config, "id")
		      ?? TryGetStringMember(config, "sid")
		      ?? TryGetStringMember(config, "configSid");
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string ResolvePortraitSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return sid;
		var trimmed = sid.Trim();
		return IsStrongholdSid(trimmed) ? trimmed : null;
	}

	private static List<string> ExtractHeroStartSquadSids(object heroConfig)
	{
		var sids = new List<string>();
		if (heroConfig == null)
			return sids;
		AppendStartSquadSids(sids, TryGetMemberValue(heroConfig, "startSquad"));
		if (sids.Count == 0)
			AppendStartSquadSids(sids, TryGetMemberValue(heroConfig, "startSquadAlt"));
		return sids;
	}

	private static void AppendStartSquadSids(List<string> sids, object squad)
	{
		if (sids == null || squad == null)
			return;
		foreach (var item in EnumerateIl2CppList(squad))
		{
			var sid = TryGetStringMember(item, "sid") ?? TryGetStringMember(item, "configSid");
			sids.Add(string.IsNullOrWhiteSpace(sid) ? null : sid.Trim());
		}
	}

	private static void ApplyToUnitWindowPartySelectorSlot(object slot, string sid, string source)
	{
		if (slot == null || string.IsNullOrWhiteSpace(sid))
			return;
		var spriteSid = ResolvePortraitSid(sid);
		if (string.IsNullOrWhiteSpace(spriteSid))
			return;
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(spriteSid, out var sprite) || sprite == null)
			return;

		var image = TryGetFirstMemberOrNoArg(slot, GameSymbols.UnitPreview.PartySelectorSlotIconFields) as UnityEngine.UI.Image;
		if (image == null)
		{
			LogDiagnostic("Homm3Import unit-window party selector portrait: icon image not found source=" + source + " sid='" + sid + "'.");
			return;
		}
		ApplyToUnitWindowPartySelectorImage(image, spriteSid, sprite);
		LogReplace(source, spriteSid, sprite);
	}

	private static void ApplyToUnitWindowPartySelectorImage(UnityEngine.UI.Image image, string spriteSid, Sprite fallback)
	{
		if (image == null || fallback == null)
			return;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = Color.white;
		if (image.gameObject)
			image.gameObject.SetActive(true);

		image.overrideSprite = null;
		if (Homm3HireUnitPortraitAnimator.TryApplyRifeShowcase(image, spriteSid, fallback, scaleRife: false))
			return;

		Homm3HireUnitPortraitAnimator.Stop(image);
		image.sprite = fallback;
		image.overrideSprite = fallback;
	}

	private static bool IsStrongholdSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
			&& (sid.StartsWith("h3_", StringComparison.Ordinal)
				|| Homm3CustomFactionRegistry.IsCustomHeroSid(sid));
	}

	private static MethodInfo FindMethodByNameAndArity(Type type, string name, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
		{
			if (method.Name == name && (parameterCount < 0 || method.GetParameters().Length == parameterCount))
				return method;
		}
		return null;
	}

	private static string TryGetFirstStringMemberOrNoArg(object instance, IEnumerable<string> names)
	{
		var value = TryGetFirstMemberOrNoArg(instance, names);
		return value as string;
	}

	private static MethodInfo FindRuntimeMethodByNameAndArity(string fullName, string name, int parameterCount)
	{
		return FindMethodByNameAndArity(FindRuntimeType(fullName), name, parameterCount);
	}

	private static Type FindRuntimeType(string fullName)
	{
		if (string.IsNullOrWhiteSpace(fullName))
			return null;
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type found = null;
			try { found = assembly.GetType(fullName, throwOnError: false); }
			catch { }
			if (found != null)
				return found;
		}
		return null;
	}

	private static string TryInferPickSlotSid(BhUnitSlot slot)
	{
		if (slot == null)
			return null;
		try
		{
			var spriteName = slot.portrait != null && slot.portrait.sprite != null ? slot.portrait.sprite.name : null;
			if (spriteName != null && IsStrongholdSid(spriteName))
				return spriteName;
		}
		catch { }
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static object TryGetMemberValue(object instance, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = instance.GetType();
		try
		{
			var property = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (property != null && property.GetIndexParameters().Length == 0)
				return property.GetValue(instance, null);
		}
		catch { }
		try
		{
			var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (field != null)
				return field.GetValue(instance);
		}
		catch { }
		return null;
	}

	private static string TryGetStringMember(object instance, string name)
	{
		var value = TryGetMemberValue(instance, name);
		return value as string;
	}

	private static object TryGetFirstMemberOrNoArg(object instance, IEnumerable<string> names)
	{
		if (instance == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = TryGetMemberValue(instance, name) ?? TryInvokeNoArg(instance, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryInvokeNoArg(object instance, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var method = instance.GetType().GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (method == null || method.GetParameters().Length != 0)
				return null;
			return method.Invoke(instance, null);
		}
		catch { return null; }
	}

	private static System.Collections.Generic.IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;
		if (list is Array array)
		{
			for (var i = 0; i < array.Length; i++)
			{
				var item = array.GetValue(i);
				if (item != null)
					yield return item;
			}
			yield break;
		}
		if (list is System.Collections.IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}
		var type = list.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Public | BindingFlags.Instance)
			?? type.GetProperty("Length", BindingFlags.Public | BindingFlags.Instance);
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

	private static void LogReplace(string source, string sid, Sprite sprite)
	{
		LogUiCardDiagnostic(source, "replaced", "sid='" + sid + "' sprite='" + (sprite ? sprite.name : "?") + "'");
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_army_strip_diag.flag"))
			return;
		if (_loggedReplace >= 40)
			return;
		_loggedReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import army-strip portrait: replaced portrait [" + source + "] sid='"
			+ sid + "' sprite='" + (sprite ? sprite.name : "?") + "'.");
	}

	private static void LogDiagnostic(string message)
	{
		if (Homm3DiagnosticFlags.IsEnabled("homm3_army_strip_diag.flag"))
			Plugin.LogSource?.LogInfo(message);
	}

	private static void LogUiCardDiagnostic(string source, string evt, string detail)
	{
		Homm3UiCardDiagnostics.Log(ClassifyUiCardSurface(source), evt, "source='" + (source ?? "?") + "' " + detail);
	}

	private static string ClassifyUiCardSurface(string source)
	{
		if (source == null)
			return "unit-card-portraits";
		if (source.IndexOf("BhHeroWithPartyCityView", StringComparison.OrdinalIgnoreCase) >= 0)
			return "town-unit-card-hero-portrait";
		if (source.IndexOf("BhHeroHUDPanel", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("BhUnitSlots", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("BhUnitUI", StringComparison.OrdinalIgnoreCase) >= 0)
			return "adventure-map-unit-card-hero-portrait";
		if (source.IndexOf("BhSummaryCard", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("BhUnitSlot", StringComparison.OrdinalIgnoreCase) >= 0)
			return "custom-game-faction-hover-unit-card-portraits";
		return "unit-card-portraits";
	}
}
