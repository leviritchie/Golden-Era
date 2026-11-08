using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Hud;
using Newtonsoft.Json.Linq;
using Hex.UI.City;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Harmony patches to replace hero portrait icons with HoMM3 PNG portraits
/// for homm3_stronghold heroes.
///
/// Strategy: find the Image named "PORTRAIT" (heroFace) on the panel, resolve the
/// hero SID from text labels or session data, load the portrait from the shared cache
/// (which searches both homm3_portraits/ and homm3_hero_portraits/), and apply it.
/// </summary>
internal static class Homm3HeroPortraitHook
{
	private static bool _patched;
	private static int _loggedReplace;
	private static int _loggedAttempts;
	private static int _loggedSurfaceReplace;
	private static int _loggedRefreshReplace;
	private static int _loggedRememberedSurface;
	private static int _loggedImageTree;
	private static int _loggedBinderMissDetails;
	private static readonly Dictionary<long, string> _strongholdHeroIconKeyByView = new();
	private static readonly Dictionary<long, string> _strongholdHeroIconKeyByObject = new();
	private static Dictionary<string, string> _heroSidByDisplayName;
	internal static string LastStrongholdHeroIconKey { get; private set; }

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		var patched = 0;

		// Audit A8 (2026-09-27): the legacy "ckj" sprite storage type does not exist on Golden Era
		// ("ckj sprite storage type not found" every start). Stronghold hero icon keys are served by the
		// guarded central resolver prefix (Homm3CustomUiIconHook.PrefixSpriteResolverCore ->
		// Homm3ImportPortraitSpriteCache), so no second, unguarded prefix goes on that native method.

		try
		{
			var ghk = GameMember.FindFirstMethodByNames(
				typeof(BhHeroHUDPanel),
				Type.EmptyTypes,
				GameSymbols.ImportVisuals.HeroHudPanelRefresh);
			if (ghk != null)
			{
				h.Patch(ghk, postfix: new HarmonyMethod(typeof(Homm3HeroPortraitHook), nameof(PostfixBhHeroHUDPanelGhk)));
				patched++;
				log?.LogInfo("Homm3HeroPortrait: BhHeroHUDPanel." + ghk.Name + " postfix registered.");
			}
			else log?.LogWarning("Homm3HeroPortrait: BhHeroHUDPanel legacy refresh not found.");
		}
		catch (Exception ex) { log?.LogWarning("Homm3HeroPortrait: BhHeroHUDPanel legacy refresh patch failed: " + ex.Message); }

		try
		{
			var start = AccessTools.Method(typeof(BhHeroHUDPanel), "Start");
			if (start != null)
			{
				h.Patch(start, postfix: new HarmonyMethod(typeof(Homm3HeroPortraitHook), nameof(PostfixBhHeroHUDPanelStart)));
				patched++;
				log?.LogInfo("Homm3HeroPortrait: BhHeroHUDPanel.Start postfix registered.");
			}
		}
		catch (Exception ex) { log?.LogDebug("Homm3HeroPortrait: BhHeroHUDPanel.Start: " + ex.Message); }

		try
		{
			var toj = GameMember.FindFirstMethodByNames(
				typeof(BhHeroWithPartyCityView),
				new Type[1],
				GameSymbols.ImportVisuals.CityHeroWithPartyRefresh);
			if (toj != null)
			{
				h.Patch(toj, postfix: new HarmonyMethod(typeof(Homm3HeroPortraitHook), nameof(PostfixBhHeroWithPartyCityViewToj)));
				patched++;
				log?.LogInfo("Homm3HeroPortrait: BhHeroWithPartyCityView." + toj.Name + " postfix registered.");
			}
			else log?.LogWarning("Homm3HeroPortrait: BhHeroWithPartyCityView legacy refresh not found.");
		}
		catch (Exception ex) { log?.LogWarning("Homm3HeroPortrait: BhHeroWithPartyCityView legacy refresh patch failed: " + ex.Message); }

		try
		{
			var start = AccessTools.Method(typeof(BhHeroWithPartyCityView), "Start");
			if (start != null)
			{
				h.Patch(start, postfix: new HarmonyMethod(typeof(Homm3HeroPortraitHook), nameof(PostfixBhHeroWithPartyCityViewStart)));
				patched++;
				log?.LogInfo("Homm3HeroPortrait: BhHeroWithPartyCityView.Start postfix registered.");
			}
		}
		catch (Exception ex) { log?.LogDebug("Homm3HeroPortrait: BhHeroWithPartyCityView.Start: " + ex.Message); }

		patched += TryPatchKnownHeroPortraitSurfaces(h, log);

		if (patched > 0)
			log?.LogInfo("Homm3HeroPortrait: " + patched + " hero portrait patch(es) registered.");
		_patched = true;
	}

	internal static void TryRegisterReleaseSafeUiSlice(Harmony h, ManualLogSource log, bool includeCityHeroWithPartyViews = false)
	{
		RegisterReleaseSafeUiSlice(h, log, includeCityHeroWithPartyViews, required: false);
	}

	internal static void RegisterRequiredReleaseSafeUiSlice(Harmony h, ManualLogSource log, bool includeCityHeroWithPartyViews = false)
	{
		RegisterReleaseSafeUiSlice(h, log, includeCityHeroWithPartyViews, required: true);
	}

	private static void RegisterReleaseSafeUiSlice(Harmony h, ManualLogSource log, bool includeCityHeroWithPartyViews, bool required)
	{
		if (_patched)
			return;
		if (h == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required Homm3HeroPortrait release-safe UI registration.");
			return;
		}

		var patched = 0;
		var missing = new List<string>();

		int Required(string label, Func<int> patch)
		{
			var count = patch();
			if (required && count == 0)
				missing.Add(label);
			return count;
		}

		int RequiredAnyByShape(string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName)
		{
			var count = PatchBySymbol(h, log, typeName, symbol, parameterTypes, postfixName, false);
			if (required && count == 0)
				missing.Add(typeName + "." + FirstHint(symbol));
			return count;
		}

		int RequiredSymbolGroup(string label, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName)
		{
			var count = PatchAllBySymbol(h, log, typeName, symbol, parameterTypes, postfixName, false);
			if (required && count == 0)
				missing.Add(label);
			return count;
		}

		var heroConfigType = ResolveHeroConfigType();
		var sessionHeroType = ResolveSessionHeroType();
		var actionType = ResolveIl2CppActionType();
		var sessionHeroWrapperType = ResolveSessionHeroWrapperType();
		var hudHeroWrapperType = ResolveHudHeroWrapperType();
		var cityHeroDataWrapperType = ResolveCityHeroDataWrapperType();

		patched += RequiredAnyByShape("Hex.BhHeroSelectButton", GameSymbols.HeroProfile.HeroSelectButtonBind, new[] { heroConfigType, actionType, actionType }, nameof(PostfixHeroConfigSurface));
		patched += RequiredAnyByShape("Hex.UI.BhTooltipHeroItemView", GameSymbols.HeroProfile.TooltipHeroItemBind, new[] { sessionHeroType, typeof(bool), typeof(bool) }, nameof(PostfixHeroSurface));
		patched += RequiredAnyByShape("Hex.UI.BhTooltipHeroItemView", GameSymbols.HeroProfile.TooltipHeroItemBind, new[] { sessionHeroType }, nameof(PostfixHeroSurface));
		patched += RequiredAnyByShape("Hex.UI.BhTooltipHeroItemView", GameSymbols.HeroProfile.TooltipHeroItemBind, new[] { sessionHeroType, typeof(bool) }, nameof(PostfixHeroSurface));
		if (sessionHeroWrapperType != null)
			patched += PatchAllBySymbol(h, log, "Hex.UI.BhTooltipHeroItemView", GameSymbols.HeroProfile.TooltipHeroItemWrapperBind, new[] { sessionHeroWrapperType, typeof(bool) }, nameof(PostfixHeroSurface), false);
		patched += RequiredSymbolGroup("Hex.UI.BhTooltipHeroItemView.LateUpdate", "Hex.UI.BhTooltipHeroItemView", GameSymbols.HeroProfile.TooltipHeroItemRefresh, Array.Empty<Type>(), nameof(PostfixTooltipHeroItemViewLateUpdate));
		patched += RequiredAnyByShape("Hex.Session.UI.HeroProfile.BhHeroPortraitView", GameSymbols.HeroProfile.PortraitViewBind, new[] { sessionHeroType, typeof(bool), typeof(bool) }, nameof(PostfixHeroPortraitView));
		// No BhHeroPortraitView bind takes a session Hero alone on Golden Era or 25509697 (the one-arg
		// Method_Public_Void_Hero_0 takes Hex.StoryHub.Logic.Hero). A (Hero)-only lookup here only re-patched the
		// 3-arg bind a second time on Golden Era, and misses off golden.
		patched += RequiredSymbolGroup("Hex.Session.HeroProfile.BhHeroProfileWindow", "Hex.Session.HeroProfile.BhHeroProfileWindow", GameSymbols.HeroProfile.ProfileWindowShown, Array.Empty<Type>(), nameof(PostfixHeroProfileWindowShown));
		patched += RequiredAnyByShape("Hex.Session.UI.HeroProfile.BhHeroDataView", GameSymbols.HeroProfile.DataViewInit, new[] { sessionHeroType, typeof(bool), typeof(bool) }, nameof(PostfixHeroDataViewBind));
		patched += RequiredSymbolGroup("Hex.Session.UI.HeroProfile.BhHeroDataView", "Hex.Session.UI.HeroProfile.BhHeroDataView", GameSymbols.HeroProfile.DataViewRefresh, Array.Empty<Type>(), nameof(PostfixHeroDataViewRefresh));
		patched += RequiredAnyByShape("Hex.Pick.BhSummaryCard", GameSymbols.ImportVisuals.SummaryCardHeroBind, new[] { heroConfigType, typeof(string) }, nameof(PostfixHeroConfigSurface));
		patched += RequiredAnyByShape("Hex.Pick.BhSummaryCard", GameSymbols.ImportVisuals.SummaryCardHeroBind, new[] { heroConfigType }, nameof(PostfixHeroConfigSurface));
		patched += RequiredAnyByShape("Hex.Session.UI.BhTavernHeroView", GameSymbols.HeroProfile.TavernHeroBind, new Type[6], nameof(PostfixHeroSurface));
		patched += RequiredAnyByShape("Hex.Session.Hud.BhHeroUIElement", GameSymbols.HeroProfile.SideHeroInit, new[] { sessionHeroWrapperType ?? sessionHeroType }, nameof(PostfixHeroUIElementInit));
		log?.LogInfo("Homm3HeroPortrait: navigation miniature hero refresh expansion active.");
		patched += RequiredSymbolGroup("Hex.Session.Hud.BhHeroUIElement", "Hex.Session.Hud.BhHeroUIElement", GameSymbols.HeroProfile.SideHeroRefresh, Array.Empty<Type>(), nameof(PostfixHeroUIElementRefresh));
		patched += RequiredSymbolGroup("Hex.Session.Hud.BhHeroHUDPanel", "Hex.Session.Hud.BhHeroHUDPanel", GameSymbols.ImportVisuals.HeroHudPanelRefresh, Array.Empty<Type>(), nameof(PostfixHeroHudPanelRelease));
		if (hudHeroWrapperType != null)
			patched += RequiredAnyByShape("Hex.Session.Hud.BhHeroHUDPanel", GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh, new[] { hudHeroWrapperType }, nameof(PostfixHeroHudPanelHeroArgRelease));
		else
			patched += RequiredSymbolGroup("Hex.Session.Hud.BhHeroHUDPanel", "Hex.Session.Hud.BhHeroHUDPanel", GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh, new[] { sessionHeroWrapperType ?? sessionHeroType }, nameof(PostfixHeroHudPanelHeroArgRelease));
		if (includeCityHeroWithPartyViews)
		{
			patched += PatchCityHeroWithPartyViews(h, log, cityHeroDataWrapperType, required, missing);
		}
		else
		{
			log?.LogInfo("Homm3HeroPortrait: BhHeroWithPartyCityView release surfaces skipped; stale city-view wrappers can native-crash during launch/loading.");
		}

		if (missing.Count > 0)
			throw new InvalidOperationException("required Homm3HeroPortrait release-safe UI surface(s) missing: " + string.Join(", ", missing));

		if (patched == 0)
			log?.LogWarning("Homm3HeroPortrait: release-safe UI slice registered no hero portrait surfaces.");
		else if (required)
			log?.LogInfo("Homm3HeroPortrait: release-safe UI slice registered " + patched + " required hero portrait surface patch(es).");
		else
			log?.LogInfo("Homm3HeroPortrait: release-safe UI slice registered " + patched + " hero portrait surface patch(es).");

		_patched = true;
	}

	private static string FirstHint(GameSymbols.MethodSymbol symbol)
	{
		return HintAt(symbol, 0);
	}

	private static string HintAt(GameSymbols.MethodSymbol symbol, int index)
	{
		var hints = symbol.NameHints ?? Array.Empty<string>();
		return index >= 0 && index < hints.Length ? hints[index] : "";
	}

	private static int TryPatchKnownHeroPortraitSurfaces(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		patched += PatchByShape(h, log, "Hex.BhHeroSelectButton", "hmy", 3, nameof(PostfixHeroConfigSurface));
		patched += PatchByShape(h, log, "Hex.BhHeroSelectButton", "hpf", 3, nameof(PostfixHeroConfigSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "sre", 3, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "tbj", 3, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "srf", 1, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "tbk", 1, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "srg", 2, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "tan", 2, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroPortraitView", "zfq", 3, nameof(PostfixHeroPortraitView));
		patched += PatchByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroPortraitView", "ztr", 3, nameof(PostfixHeroPortraitView));
		patched += PatchByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroPortraitView", "zft", 1, nameof(PostfixHeroPortraitView));
		patched += PatchByShape(h, log, "Hex.Session.UI.HeroProfile.BhHeroPortraitView", "ztu", 1, nameof(PostfixHeroPortraitView));
		patched += PatchByShape(h, log, "Hex.Session.UI.BhTavernHeroView", "ynz", 6, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.Session.UI.BhTavernHeroView", "zbw", 6, nameof(PostfixHeroSurface));
		patched += PatchByShape(h, log, "Hex.UI.BhTooltipHeroItemView", "LateUpdate", 0, nameof(PostfixTooltipHeroItemViewLateUpdate));
		return patched;
	}

	private static Type _heroConfigType;
	private static Type _sessionHeroType;
	private static Type _il2CppActionType;
	private static Type _sessionHeroWrapperType;
	private static Type _hudHeroWrapperType;
	private static Type _cityHeroDataWrapperType;

	private static int PatchCityHeroWithPartyViews(Harmony h, ManualLogSource log, Type cityHeroDataWrapper, bool required, List<string> missing)
	{
		var typeName = "Hex.UI.City.BhHeroWithPartyCityView";
		var count = 0;
		if (cityHeroDataWrapper != null)
			count += PatchBySymbol(h, log, typeName, GameSymbols.ImportVisuals.CityHeroWithPartyRefresh, new[] { cityHeroDataWrapper }, nameof(PostfixCityHeroWithPartyRelease), false);
		count += PatchBySymbol(h, log, typeName, GameSymbols.ImportVisuals.CityHeroWithPartyRefresh, Array.Empty<Type>(), nameof(PostfixCityHeroWithPartyRelease), false);
		if (required && count == 0)
			missing.Add(typeName + "." + FirstHint(GameSymbols.ImportVisuals.CityHeroWithPartyRefresh));
		return count;
	}

	private static Type ResolveHeroConfigType()
	{
		if (_heroConfigType != null)
			return _heroConfigType;
		try { _heroConfigType = typeof(Hex.Configs.HeroConfig); }
		catch { _heroConfigType = GameMember.FindType("hero.config", "HeroConfig"); }
		return _heroConfigType;
	}

	private static Type ResolveSessionHeroType()
	{
		if (_sessionHeroType != null)
			return _sessionHeroType;
		try { _sessionHeroType = typeof(Hex.Session.Logic.Hero); }
		catch { _sessionHeroType = GameMember.FindType("hero.session.logic", "Hero"); }
		return _sessionHeroType;
	}

	private static Type ResolveIl2CppActionType()
	{
		if (_il2CppActionType != null)
			return _il2CppActionType;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				var type = asm.GetType("Il2CppSystem.Action", throwOnError: false);
				if (type != null)
				{
					_il2CppActionType = type;
					return type;
				}
			}
			catch { }
		}
		var buttonType = FindRuntimeType("Hex.BhHeroSelectButton");
		if (buttonType != null)
		{
			foreach (var method in buttonType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				var ps = method.GetParameters();
				if (ps.Length != 3)
					continue;
				if (ps[1].ParameterType?.FullName?.IndexOf("Action", StringComparison.OrdinalIgnoreCase) >= 0)
				{
					_il2CppActionType = ps[1].ParameterType;
					return _il2CppActionType;
				}
			}
		}
		return null;
	}

	private static Type ResolveSessionHeroWrapperType()
	{
		if (_sessionHeroWrapperType != null)
			return _sessionHeroWrapperType;
		var elementType = FindRuntimeType("Hex.Session.Hud.BhHeroUIElement");
		if (elementType != null)
		{
			foreach (var method in elementType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, "Init", StringComparison.Ordinal))
					continue;
				var ps = method.GetParameters();
				if (ps.Length == 1 && ps[0].ParameterType != null)
				{
					_sessionHeroWrapperType = ps[0].ParameterType;
					return _sessionHeroWrapperType;
				}
			}
		}
		return null;
	}

	// BhHeroHUDPanel's hero-argument refresh takes the same session hero wrapper as BhHeroUIElement.Init
	// (Golden Era literal Method_Private_Void_ObjectPublicHeObInObciSiObVeSeObUnique_0). The old rule took the
	// first one-argument void method's parameter, which is reflection-order luck: on Golden Era it landed on
	// ObjectPublicVo2 and on 25509697 the scoped name then matched no shape.
	private static Type ResolveHudHeroWrapperType()
	{
		if (_hudHeroWrapperType != null)
			return _hudHeroWrapperType;
		_hudHeroWrapperType = ResolveSessionHeroWrapperType();
		return _hudHeroWrapperType;
	}

	private static Type ResolveCityHeroDataWrapperType()
	{
		if (_cityHeroDataWrapperType != null)
			return _cityHeroDataWrapperType;
		var viewType = FindRuntimeType("Hex.UI.City.BhHeroWithPartyCityView");
		if (viewType != null)
		{
			foreach (var method in viewType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
			{
				var ps = method.GetParameters();
				if (ps.Length != 1 || method.ReturnType != typeof(void))
					continue;
				if (ps[0].ParameterType == typeof(int))
					continue;
				_cityHeroDataWrapperType = ps[0].ParameterType;
				return _cityHeroDataWrapperType;
			}
		}
		return null;
	}

	private static int PatchBySymbol(Harmony h, ManualLogSource log, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName, bool logCandidates = true)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3HeroPortrait: surface type not found: " + typeName);
				return 0;
			}
			if (!TrySelectSurfaceMethod(type, symbol, parameterTypes, out var selected))
			{
				log?.LogWarning("Homm3HeroPortrait: surface method not found: " + typeName + " shape=(" + DescribeParameterTypes(parameterTypes) + ")");
				if (logCandidates)
					LogSurfaceMethodCandidates(type, log);
				return 0;
			}
			return TryApplySurfacePatch(h, log, selected, postfixName) ? 1 : 0;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3HeroPortrait: surface patch failed for " + typeName + ": " + ex.Message);
			return 0;
		}
	}

	// Unity lifecycle / adventure-HUD input handlers must never be treated as portrait
	// refresh surfaces. Patching OnDisable caused a combat-load IL2CPP trampoline stack overflow.
	// Do NOT exclude LateUpdate/Update here — TooltipHeroItemRefresh intentionally uses LateUpdate.
	private static readonly HashSet<string> PortraitSurfaceExcludedMethodNames = new HashSet<string>(StringComparer.Ordinal)
	{
		"Awake", "Start", "OnEnable", "OnDisable", "OnDestroy",
		"OnHoverStart", "OnHoverEnd", "OnHeroSelectBtn", "OnPointerClick",
		"Finalize",
	};

	private static bool IsExcludedPortraitSurfaceMethod(MethodInfo method)
	{
		return method != null && PortraitSurfaceExcludedMethodNames.Contains(method.Name);
	}

	private static int PatchAllBySymbol(Harmony h, ManualLogSource log, string typeName, GameSymbols.MethodSymbol symbol, Type[] parameterTypes, string postfixName, bool logCandidates = true)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3HeroPortrait: surface type not found: " + typeName);
				return 0;
			}
			var methods = GameMember.FindMethods(type, typeof(void), parameterTypes, symbol);
			if (methods.Length == 0 && parameterTypes != null && parameterTypes.Length == 0)
				methods = FindBestParameterlessVoidMethods(type);
			if (methods.Length == 0 && !string.IsNullOrEmpty(symbol.Id))
			{
				foreach (var hint in symbol.NameHints)
				{
					if (string.IsNullOrWhiteSpace(hint))
						continue;
					if (IsExcludedPortraitSurfaceMethodName(hint))
						continue;
					if (TrySelectSurfaceMethod(type, symbol, parameterTypes, out var selected, hint, useSymbolLookup: false))
					{
						methods = new[] { selected };
						break;
					}
				}
			}
			if (methods.Length == 0)
			{
				log?.LogWarning("Homm3HeroPortrait: surface method group not found: " + typeName + " shape=(" + DescribeParameterTypes(parameterTypes) + ")");
				if (logCandidates)
					LogSurfaceMethodCandidates(type, log);
				return 0;
			}
			var patched = 0;
			var seen = new HashSet<MethodInfo>();
			foreach (var method in methods)
			{
				if (method == null || !seen.Add(method))
					continue;
				if (IsExcludedPortraitSurfaceMethod(method))
				{
					// Allow when the symbol explicitly names this surface (e.g. LateUpdate refresh).
					var named = false;
					if (symbol.NameHints != null)
					{
						foreach (var hint in symbol.NameHints)
						{
							if (string.Equals(hint, method.Name, StringComparison.Ordinal))
							{
								named = true;
								break;
							}
						}
					}
					if (!named)
					{
						log?.LogInfo("Homm3HeroPortrait: refusing lifecycle/input surface " + FormatMethod(method) + " for portrait refresh.");
						continue;
					}
				}
				if (TryApplySurfacePatch(h, log, method, postfixName))
					patched++;
			}
			return patched;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3HeroPortrait: surface group patch failed for " + typeName + ": " + ex.Message);
			return 0;
		}
	}

	private static bool IsExcludedPortraitSurfaceMethodName(string name)
	{
		return !string.IsNullOrEmpty(name) && PortraitSurfaceExcludedMethodNames.Contains(name);
	}

	private static bool TrySelectSurfaceMethod(
		Type type,
		GameSymbols.MethodSymbol symbol,
		Type[] parameterTypes,
		out MethodInfo selected,
		string exactName = null,
		bool useSymbolLookup = true)
	{
		selected = null;
		if (type == null)
			return false;
		var paramCount = parameterTypes?.Length ?? -1;
		if (!string.IsNullOrWhiteSpace(exactName))
		{
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, exactName, StringComparison.Ordinal))
					continue;
				if (!SurfaceParameterTypesMatch(method, parameterTypes, paramCount))
					continue;
				selected = method;
				return true;
			}
		}
		if (useSymbolLookup && !string.IsNullOrEmpty(symbol.Id) && symbol.NameHints != null)
		{
			foreach (var hint in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(hint))
					continue;
				foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
				{
					if (!string.Equals(method.Name, hint, StringComparison.Ordinal))
						continue;
					if (!SurfaceParameterTypesMatch(method, parameterTypes, paramCount))
						continue;
					selected = method;
					return true;
				}
			}
		}
		if (useSymbolLookup && !string.IsNullOrEmpty(symbol.Id) && parameterTypes != null)
		{
			selected = GameMember.FindFirstMethod(type, typeof(void), parameterTypes, symbol);
			if (selected != null)
				return true;
		}
		return false;
	}

	private static bool SurfaceParameterTypesMatch(MethodInfo method, Type[] parameterTypes, int paramCount)
	{
		if (method == null)
			return false;
		var parameters = method.GetParameters();
		if (paramCount >= 0 && parameters.Length != paramCount)
			return false;
		if (parameterTypes == null)
			return true;
		if (parameters.Length != parameterTypes.Length)
			return false;
		for (var i = 0; i < parameterTypes.Length; i++)
		{
			var expected = parameterTypes[i];
			if (expected == null)
				continue;
			if (!GameInteropTypes.TypesMatch(parameters[i].ParameterType, expected))
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
			if (method.GetParameters().Length != 0)
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			if (string.Equals(method.Name, "Finalize", StringComparison.Ordinal))
				continue;
			matches.Add(method);
		}
		if (matches.Count == 0)
			return Array.Empty<MethodInfo>();
		matches.Sort(CompareParameterlessVoidMethod);
		return new[] { matches[0] };
	}

	private static int CompareParameterlessVoidMethod(MethodInfo a, MethodInfo b)
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
		var postfix = typeof(Homm3HeroPortraitHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
		{
			log?.LogWarning("Homm3HeroPortrait: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
			return false;
		}
		h.Patch(selected, postfix: new HarmonyMethod(postfix));
		log?.LogInfo("Homm3HeroPortrait: surface postfix registered on " + FormatMethod(selected) + ".");
		return true;
	}

	private static string DescribeParameterTypes(Type[] parameterTypes)
	{
		if (parameterTypes == null || parameterTypes.Length == 0)
			return "";
		return string.Join(", ", Array.ConvertAll(parameterTypes, t => t?.Name ?? "*"));
	}

	private static int PatchByShape(Harmony h, ManualLogSource log, string typeName, string methodName, int parameterCount, string postfixName, bool logCandidates = true)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("Homm3HeroPortrait: surface type not found: " + typeName);
				return 0;
			}
			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name != methodName || (parameterCount >= 0 && method.GetParameters().Length != parameterCount))
					continue;
				selected = method;
				break;
			}
			if (selected == null)
			{
				log?.LogWarning("Homm3HeroPortrait: surface method not found: " + typeName + "." + methodName + "/" + parameterCount);
				if (logCandidates)
					LogSurfaceMethodCandidates(type, log);
				return 0;
			}
			var postfix = typeof(Homm3HeroPortraitHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3HeroPortrait: refusing incompatible postfix for " + FormatMethod(selected) + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			log?.LogInfo("Homm3HeroPortrait: surface postfix registered on " + FormatMethod(selected) + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3HeroPortrait: surface patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static void LogSurfaceMethodCandidates(Type type, ManualLogSource log)
	{
		if (type == null || log == null)
			return;
		try
		{
			var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
			var logged = 0;
			foreach (var method in methods)
			{
				if (method == null)
					continue;
				if (logged >= 40)
					break;
				logged++;
				log.LogInfo("Homm3HeroPortrait diag: surface method " + FormatMethod(method) + " returns " + (method.ReturnType?.FullName ?? "?") + ".");
			}
			log.LogInfo("Homm3HeroPortrait diag: surface type '" + (type.FullName ?? type.Name) + "' declaredMethodCount=" + methods.Length + " logged=" + logged + ".");
		}
		catch (Exception ex)
		{
			log.LogWarning("Homm3HeroPortrait diag: surface method dump failed for " + (type.FullName ?? type.Name) + ": " + ex.Message);
		}
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

	private static bool IsStrongholdHeroIconKey(string key)
	{
		return Homm3CustomFactionRegistry.IsCustomHeroSid(key);
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "(unknown)";
		try
		{
			var ps = method.GetParameters();
			var args = "";
			for (var i = 0; i < ps.Length; i++)
			{
				if (i > 0)
					args += ", ";
				args += ps[i].ParameterType.Name + " " + ps[i].Name;
			}
			return method.DeclaringType?.FullName + "." + method.Name + "(" + args + ")";
		}
		catch
		{
			return method.Name;
		}
	}

	private static void LogHeroPortraitBinderHit(string surface, string source, object view, object heroOrConfig)
	{
		try
		{
			var iconKey = ResolveHeroIconKeyForDiagnostic(heroOrConfig);
			if (string.IsNullOrWhiteSpace(iconKey) && view != null && !ReferenceEquals(view, heroOrConfig))
				iconKey = ResolveHeroIconKeyForDiagnostic(view);
			var image = FindPortraitImageForDiagnostic(view);
			Homm3UiCardDiagnostics.Log(
				surface,
				"hero-portrait-binder-hit",
				"source='" + (source ?? "?")
				+ "' view='" + FormatObject(view)
				+ "' payload='" + FormatObject(heroOrConfig)
				+ "' iconKey='" + (iconKey ?? "?")
				+ "' target='" + FormatImage(image)
				+ "' imageCount=" + CountImages(view),
				limit: 60);
			if ((string.IsNullOrWhiteSpace(iconKey) || !image)
			    && _loggedBinderMissDetails < 12)
			{
				_loggedBinderMissDetails++;
				Homm3UiCardDiagnostics.Log(
					surface,
					"hero-portrait-binder-miss-detail",
					"source='" + (source ?? "?")
					+ "' viewMembers=["
					+ DescribeHeroPortraitMembersForDiag(view)
					+ "] payloadMembers=["
					+ DescribeHeroPortraitMembersForDiag(heroOrConfig)
					+ "] childImages=["
					+ DescribeChildImagesForDiag(view)
					+ "]",
					limit: 12);
			}
		}
		catch (Exception ex)
		{
			Homm3UiCardDiagnostics.Log(
				surface,
				"hero-portrait-binder-hit-failed",
				"source='" + (source ?? "?") + "' error='" + ex.GetType().Name + ": " + ex.Message + "'",
				limit: 20);
		}
	}

	private static string ResolveHeroIconKeyForDiagnostic(object obj)
	{
		return ResolveHeroIconKeyForDiagnostic(obj, new HashSet<int>(), 0);
	}

	private static string ResolveHeroIconKeyForDiagnostic(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 4)
			return null;
		if (obj is string directString && IsStrongholdHeroIconKey(directString))
			return directString.Trim();

		var key = RuntimeHelpersGetHashCode(obj);
		if (!seen.Add(key))
			return null;

		var compatKey = DeobfInteropCompat.GetSessionHeroPortraitKey(obj);
		if (!string.IsNullOrWhiteSpace(compatKey))
			return compatKey;

		var type = obj.GetType();
		foreach (var name in GameSymbols.HeroProfile.HeroConfigFields)
		{
			var value = TryGetMemberValue(obj, type, name) as string;
			if (IsStrongholdHeroIconKey(value))
				return value.Trim();
		}

		foreach (var name in GameSymbols.ImportVisuals.SessionHeroConfigFields)
		{
			var value = TryGetMemberValue(obj, type, name) as string;
			if (IsStrongholdHeroIconKey(value))
				return value.Trim();
		}

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(obj, type, name);
			var nestedKey = ResolveHeroIconKeyForDiagnostic(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.ImportVisuals.CityHeroWithPartyTooltipFields)
		{
			var nested = TryGetMemberValue(obj, type, name);
			var nestedKey = ResolveHeroIconKeyForDiagnostic(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.ImportVisuals.TooltipHeroItemSessionHeroFields)
		{
			var nested = TryGetMemberValue(obj, type, name);
			var nestedKey = ResolveHeroIconKeyForDiagnostic(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.ImportVisuals.SessionHeroWrapperHeroFields)
		{
			var nested = TryGetFieldValueOnly(obj, type, name);
			var nestedKey = ResolveHeroIconKeyForDiagnostic(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		return null;
	}

	private static Image FindPortraitImageForDiagnostic(object view)
	{
		if (view == null)
			return null;
		if (view is BhHeroWithPartyCityView cityView)
			return FindCityHeroPortraitImageFieldOnly(cityView);
		var type = view.GetType();
		// heroFace/heroIcon are interop field properties, not CLR fields, so read members (prop_ names stay excluded).
		return TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.TooltipHeroItemPortraitFields) as Image
		       ?? TryGetMemberValue(view, type, "heroIcon") as Image
		       ?? TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.HeroPortraitImageFields) as Image;
	}

	private static string FormatObject(object obj)
	{
		if (obj == null)
			return "(null)";
		try
		{
			return obj.GetType().FullName ?? obj.GetType().Name;
		}
		catch
		{
			return "?";
		}
	}

	private static string FormatImage(Image image)
	{
		if (!image)
			return "(none)";
		try
		{
			return image.GetType().FullName ?? image.GetType().Name;
		}
		catch
		{
			return "(image)";
		}
	}

	private static int CountImages(object view)
	{
		return FindPortraitImageForDiagnostic(view) ? 1 : 0;
	}

	private static string DescribeHeroPortraitMembersForDiag(object obj)
	{
		if (obj == null)
			return "(null)";
		try
		{
			var parts = new List<string>();
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var type = obj.GetType(); type != null && type != typeof(object) && parts.Count < 28; type = type.BaseType)
			{
				FieldInfo[] fields;
				try { fields = type.GetFields(flags); }
				catch { fields = Array.Empty<FieldInfo>(); }
				foreach (var field in fields)
				{
					if (parts.Count >= 28)
						break;
					if (!IsHeroPortraitDiagnosticType(field.FieldType))
						continue;
					parts.Add(field.Name + ":" + field.FieldType.Name + "=" + FormatHeroDiagValue(ReadFieldForDiag(field, obj)));
				}

			}
			return (obj.GetType().FullName ?? obj.GetType().Name) + " " + (parts.Count == 0 ? "(no simple members)" : string.Join(",", parts));
		}
		catch (Exception ex)
		{
			return (obj.GetType().FullName ?? obj.GetType().Name) + " (summary failed:" + ex.GetType().Name + ")";
		}
	}

	private static bool IsHeroPortraitDiagnosticType(Type type)
	{
		if (type == null)
			return false;
		if (type == typeof(string) || type == typeof(int) || type == typeof(bool))
			return true;
		if (typeof(Component).IsAssignableFrom(type) || typeof(UnityEngine.Object).IsAssignableFrom(type))
			return true;
		var name = type.FullName ?? type.Name;
		return name.IndexOf("Hero", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("Config", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("Wrapper", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static object ReadFieldForDiag(FieldInfo field, object obj)
	{
		try { return field.GetValue(obj); }
		catch (Exception ex) { return ex.GetType().Name; }
	}

	private static string FormatHeroDiagValue(object value)
	{
		if (value == null)
			return "(null)";
		if (value is string s)
			return "'" + TrimHeroDiag(s, 72) + "'";
		if (value is bool b)
			return b ? "true" : "false";
		if (value is int)
			return value.ToString();
		if (value is Image image)
			return "Image(" + (image.gameObject ? image.gameObject.name : "?") + ")";
		if (value is Component component)
			return component.GetType().Name + "(" + (component.gameObject ? component.gameObject.name : "?") + ")";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string DescribeChildImagesForDiag(object view)
	{
		if (view is not Component component)
			return "(not-component)";
		try
		{
			var images = component.GetComponentsInChildren<Image>(true);
			var parts = new List<string>();
			for (var i = 0; i < images.Length && parts.Count < 18; i++)
			{
				var img = images[i];
				if (!img)
					continue;
				parts.Add(
					(img.gameObject ? img.gameObject.name : "?")
					+ ":enabled=" + img.enabled
					+ ",active=" + (img.gameObject && img.gameObject.activeInHierarchy)
					+ ",sprite='" + (img.sprite ? TrimHeroDiag(img.sprite.name, 48) : "?") + "'"
					+ ",override='" + (img.overrideSprite ? TrimHeroDiag(img.overrideSprite.name, 48) : "?") + "'");
			}
			return parts.Count == 0 ? "(none)" : string.Join(";", parts);
		}
		catch (Exception ex)
		{
			return "(failed:" + ex.GetType().Name + ")";
		}
	}

	private static string TrimHeroDiag(string value, int max)
	{
		if (string.IsNullOrEmpty(value) || value.Length <= max)
			return value ?? string.Empty;
		return value.Substring(0, max) + "...";
	}

	private static void PostfixBhHeroHUDPanelGhk(BhHeroHUDPanel __instance)
	{
		LogHeroPortraitBinderHit("adventure-map-unit-card-hero-portrait", "BhHeroHUDPanel.ghk", __instance, __instance);
		TryApplyHeroPortrait(__instance, "BhHeroHUDPanel.ghk");
	}

	private static void PostfixBhHeroHUDPanelStart(BhHeroHUDPanel __instance)
	{
		LogHeroPortraitBinderHit("adventure-map-unit-card-hero-portrait", "BhHeroHUDPanel.Start", __instance, __instance);
		TryApplyHeroPortrait(__instance, "BhHeroHUDPanel.Start");
	}

	private static void PostfixBhHeroWithPartyCityViewToj(BhHeroWithPartyCityView __instance)
	{
		LogHeroPortraitBinderHit("town-unit-card-hero-portrait", "BhHeroWithPartyCityView.toj", __instance, __instance);
		TryApplyCityHeroPortrait(__instance, "BhHeroWithPartyCityView.toj");
	}

	private static void PostfixBhHeroWithPartyCityViewStart(BhHeroWithPartyCityView __instance)
	{
		LogHeroPortraitBinderHit("town-unit-card-hero-portrait", "BhHeroWithPartyCityView.Start", __instance, __instance);
		TryApplyCityHeroPortrait(__instance, "BhHeroWithPartyCityView.Start");
	}

	private static void PostfixHeroConfigSurface(object __instance, [HarmonyArgument(0)] object heroConfig, MethodBase __originalMethod)
	{
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit(ClassifyUiCardSurface(source), source, __instance, heroConfig);
		TryApplySurfacePortrait(__instance, heroConfig, source);
	}

	private static void PostfixHeroSurface(object __instance, [HarmonyArgument(0)] object hero, MethodBase __originalMethod)
	{
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit(ClassifyUiCardSurface(source), source, __instance, hero);
		TryApplySurfacePortrait(__instance, hero, source);
	}

	private static void PostfixHeroPortraitView(object __instance, [HarmonyArgument(0)] object hero, MethodBase __originalMethod)
	{
		if (__instance == null)
			return;
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source, __instance, hero);
		TryApplySurfacePortrait(__instance, hero, source);
		var tooltipView = TryGetFirstMemberValue(__instance, GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields);
		if (tooltipView != null)
		{
			LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source + ".heroView", tooltipView, hero);
			TryApplySurfacePortrait(tooltipView, hero, source + ".heroView");
		}
	}

	private static void PostfixHeroProfileWindowShown(object __instance, MethodBase __originalMethod)
	{
		if (__instance == null)
			return;
		var hero = TryGetFirstFieldValueOnly(__instance, GameSymbols.HeroProfile.HeroStateFields)
			?? TryInvokeNoArg(__instance, __instance.GetType(), "bkkj")
			?? TryInvokeNoArg(__instance, __instance.GetType(), "bkki");
		var source = "BhHeroProfileWindow." + (__originalMethod != null ? __originalMethod.Name : "shown");
		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source, __instance, hero);
		TryApplySurfacePortrait(__instance, hero, source);
		var portraitView = TryGetFirstMemberValue(__instance, GameSymbols.HeroProfile.ProfileWindowPortraitViewFields);
		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source + ".portraitView", portraitView, hero);
		TryApplySurfacePortrait(portraitView, hero, source + ".portraitView");
		var heroDataView = TryGetFirstMemberValue(__instance, GameSymbols.HeroProfile.ProfileWindowDataViewFields);
		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source + ".heroDataView", heroDataView, hero);
		TryApplyHeroDataViewPortrait(heroDataView, hero, source + ".heroDataView");
		var heroSid = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(hero);
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			hero,
			heroSid,
			__instance,
			"inventory-screen-hero-specialization");
	}

	private static void PostfixHeroDataViewBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (__instance == null)
			return;
		var hero = ResolveFirstStrongholdHeroArg(__args) ?? (__args != null && __args.Length > 0 ? __args[0] : null);
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source, __instance, hero);
		TryApplyHeroDataViewPortrait(__instance, hero, source);
		var heroSid = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(hero);
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			hero,
			heroSid,
			__instance,
			"inventory-screen-hero-specialization");
		var specializationView = TryGetFieldValueOnly(__instance, "specializationView");
		if (specializationView != null)
			Homm3HeroSpecializationIconUi.TryApplyForSpecializationView(specializationView, hero, source + ".specializationView");
	}

	private static void PostfixHeroDataViewRefresh(object __instance, MethodBase __originalMethod)
	{
		if (__instance == null)
			return;
		var hero = TryGetFirstMemberValue(__instance, GameSymbols.HeroProfile.HeroStateFields);
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source, __instance, hero);
		TryApplyHeroDataViewPortrait(__instance, hero, source);
		var heroSid = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(hero);
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			hero,
			heroSid,
			__instance,
			"inventory-screen-hero-specialization");
	}

	private static void PostfixTooltipHeroItemViewLateUpdate(object __instance)
	{
		RefreshRememberedHeroSurface(__instance, "BhTooltipHeroItemView.LateUpdate");
	}

	private static void PostfixHeroUIElementInit(object __instance, [HarmonyArgument(0)] object hero)
	{
		LogHeroPortraitBinderHit("adventure-map-hud-mini-hero-portrait", "BhHeroUIElement.Init", __instance, hero);
		TryApplyHeroUIElementPortrait(__instance, hero, "BhHeroUIElement.Init");
	}

	private static void PostfixHeroUIElementRefresh(object __instance, MethodBase __originalMethod)
	{
		if (IsExcludedPortraitSurfaceMethod(__originalMethod as MethodInfo)
		    || (__originalMethod != null && IsExcludedPortraitSurfaceMethodName(__originalMethod.Name)))
			return;
		var hero = TryGetFirstFieldValueOnly(__instance, GameSymbols.HeroProfile.SideHeroFields);
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit("adventure-map-hud-mini-hero-portrait", source, __instance, hero);
		TryApplyHeroUIElementPortrait(__instance, hero, source);
	}

	private static void PostfixHeroHudPanelRelease(object __instance, MethodBase __originalMethod)
	{
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit("adventure-map-hud-selected-hero-portrait", source, __instance, __instance);
		if (__instance is BhHeroHUDPanel panel)
		{
			TryApplyHeroPortrait(panel, source);
			return;
		}
		TryApplySurfacePortrait(__instance, __instance, source);
	}

	private static void PostfixHeroHudPanelHeroArgRelease(object __instance, [HarmonyArgument(0)] object hero, MethodBase __originalMethod)
	{
		var source = FormatMethod(__originalMethod);
		LogHeroPortraitBinderHit("adventure-map-hud-selected-hero-portrait", source, __instance, hero);
		TryApplySurfacePortrait(__instance, hero ?? __instance, source);
		if (__instance is BhHeroHUDPanel panel)
			TryApplyHeroPortrait(panel, source);
	}

	private static void PostfixCityHeroWithPartyRelease(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var source = FormatMethod(__originalMethod);
		var hero = __args != null && __args.Length > 0 ? __args[0] : __instance;
		LogHeroPortraitBinderHit("town-unit-card-hero-portrait", source, __instance, hero);
		if (__instance is BhHeroWithPartyCityView view)
		{
			TryApplyCityHeroPortrait(view, source);
			return;
		}
	}

	private static void TryApplyHeroUIElementPortrait(object view, object hero, string source)
	{
		if (view == null)
			return;
		try
		{
			hero ??= TryResolveSideHeroFromView(view);
			if (hero == null)
				return;
			var iconKey = ResolveStrongholdHeroIconKey(hero);
			if (iconKey == null)
				return;
			if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
				return;

			RememberHeroIdentityTree(hero, iconKey);
			RememberHeroSurface(view, iconKey, source);
			var image = DeobfInteropCompat.GetImageMember(view, GameSymbols.HeroProfile.SideHeroIconFields);
			if (image == null)
				image = FindBestPortraitImage(view);
			if (image == null)
				return;
			ApplySpriteToImage(image, sprite);
			LogSurfaceReplace(source, iconKey, sprite, image);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: side hero UI " + source + " failed: " + ex.Message);
		}
	}

	private static object TryResolveSideHeroFromView(object view)
	{
		if (view == null)
			return null;
		var hero = TryGetFirstFieldValueOnly(view, GameSymbols.HeroProfile.SideHeroFields);
		if (hero != null)
			return hero;
		var type = view.GetType();
		foreach (var name in GameSymbols.HeroProfile.SideHeroFields)
		{
			hero = TryGetMemberValue(view, type, name);
			if (hero != null)
				return hero;
		}
		return null;
	}

	private static void TryApplySurfacePortrait(object view, object heroOrConfig, string source)
	{
		if (view == null || heroOrConfig == null)
			return;
		try
		{
			var iconKey = ResolveStrongholdHeroIconKey(heroOrConfig);
			if (iconKey == null)
				return;
			if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
				return;
			RememberHeroIdentityTree(heroOrConfig, iconKey);
			RememberHeroSurface(view, iconKey, source);
			var image = FindBestPortraitImage(view);
			if (image == null)
				return;
			ApplySpriteToImage(image, sprite);
			HideSummaryCardRandomPortraitOverlay(view);
			LogSurfaceReplace(source, iconKey, sprite, image);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: surface " + source + " failed: " + ex.Message);
		}
	}

	private static void TryApplyHeroDataViewPortrait(object dataView, object heroOrConfig, string source)
	{
		if (dataView == null || heroOrConfig == null)
			return;

		TryApplySurfacePortrait(dataView, heroOrConfig, source);
		var heroSid = Homm3HeroSpecializationIconUi.TryGetHeroSidFromConfig(heroOrConfig);
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			heroOrConfig,
			heroSid,
			dataView,
			"inventory-screen-hero-specialization");
		var portraitView = TryGetFirstMemberValue(dataView, GameSymbols.HeroProfile.DataViewHeroPortraitFields);
		if (portraitView == null)
			return;

		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source + ".heroView", portraitView, heroOrConfig);
		TryApplySurfacePortrait(portraitView, heroOrConfig, source + ".heroView");
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			heroOrConfig,
			heroSid,
			portraitView,
			"inventory-screen-hero-specialization");
		var tooltipView = TryGetFieldValueOnly(portraitView, "heroView");
		if (tooltipView == null)
			return;

		LogHeroPortraitBinderHit("inventory-screen-hero-portrait", source + ".heroView.heroView", tooltipView, heroOrConfig);
		TryApplySurfacePortrait(tooltipView, heroOrConfig, source + ".heroView.heroView");
	}

	private static void RefreshRememberedHeroSurface(object view, string source)
	{
		if (view == null)
			return;
		try
		{
			if (!_strongholdHeroIconKeyByView.TryGetValue(GetStableObjectKey(view), out var iconKey) || string.IsNullOrWhiteSpace(iconKey))
				return;
			if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
				return;
			var image = FindBestPortraitImage(view);
			if (image == null)
				return;
			if (image.sprite == sprite && image.overrideSprite == sprite && image.enabled)
			{
				HideSummaryCardRandomPortraitOverlay(view);
				return;
			}
			ApplySpriteToImage(image, sprite);
			HideSummaryCardRandomPortraitOverlay(view);
			LogRefreshReplace(source, iconKey, sprite, image);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: remembered surface " + source + " failed: " + ex.Message);
		}
	}

	private static string ResolveStrongholdHeroIconKey(object heroOrConfig)
	{
		var seen = new HashSet<int>();
		return ResolveStrongholdHeroIconKey(heroOrConfig, seen, 0);
	}

	private static string ResolveStrongholdHeroIconKey(object obj, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 3)
			return null;
		if (obj is string directString && IsStrongholdHeroIconKey(directString))
			return directString.Trim();
		var key = RuntimeHelpersGetHashCode(obj);
		if (!seen.Add(key))
			return null;

		var configIcon = DeobfInteropCompat.GetHeroConfigIcon(obj);
		var configId = DeobfInteropCompat.GetHeroConfigId(obj);
		var compatKey = DeobfInteropCompat.GetSessionHeroPortraitKey(obj);
		if (!string.IsNullOrWhiteSpace(compatKey))
			return compatKey;
		if (Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(configIcon ?? configId, out var normalized))
			return normalized;

		var t = obj.GetType();

		foreach (var name in GameSymbols.HeroProfile.HeroConfigFields)
		{
			var direct = TryGetStringMember(obj, t, name);
			if (IsStrongholdHeroIconKey(direct))
				return direct.Trim();
		}

		if (_strongholdHeroIconKeyByObject.TryGetValue(GetStableObjectKey(obj), out var remembered) && IsStrongholdHeroIconKey(remembered))
			return remembered.Trim();

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(obj, t, name);
			var nestedKey = ResolveStrongholdHeroIconKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.HeroProfile.HeroConfigGetters)
		{
			if (!CanInvokeHeroConfigGetter(name))
				continue;
			var nested = TryInvokeNoArg(obj, t, name);
			var nestedKey = ResolveStrongholdHeroIconKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		return null;
	}

	private static int RuntimeHelpersGetHashCode(object obj)
	{
		return obj == null ? 0 : System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
	}

	private static string TryGetStringMember(object obj, Type type, string name)
	{
		var v = TryGetMemberValue(obj, type, name);
		return v as string;
	}

	private static bool CanInvokeHeroConfigGetter(string name)
	{
		return !string.IsNullOrWhiteSpace(name)
		       && !name.StartsWith("Method_", StringComparison.Ordinal);
	}

	private static object TryGetMemberValue(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var f = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (f != null)
					return f.GetValue(obj);
			}
			catch { }
			try
			{
				var p = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (p != null && p.GetIndexParameters().Length == 0 && !IsGeneratedInteropPropertyName(name))
					return p.GetValue(obj);
			}
			catch { }
			try
			{
				var getter = IsGeneratedInteropPropertyName(name)
					? null
					: current.GetMethod("get_" + name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
				if (getter != null)
					return getter.Invoke(obj, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	private static bool IsGeneratedInteropPropertyName(string name)
	{
		return !string.IsNullOrWhiteSpace(name)
		       && name.StartsWith("prop_", StringComparison.Ordinal);
	}

	private static object TryInvokeNoArg(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var m = current.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
				if (m != null)
					return m.Invoke(obj, Array.Empty<object>());
			}
			catch { return null; }
		}
		return null;
	}

	private static object TryGetFieldValue(object obj, string name)
	{
		if (obj == null)
			return null;
		try
		{
			return TryGetMemberValue(obj, obj.GetType(), name);
		}
		catch { return null; }
	}

	private static object TryGetFieldValueOnly(object obj, string name)
	{
		if (obj == null)
			return null;
		return TryGetFieldValueOnly(obj, obj.GetType(), name);
	}

	private static object TryGetFirstFieldValueOnly(object obj, IEnumerable<string> names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		foreach (var name in names)
		{
			var value = TryGetFieldValueOnly(obj, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetFieldValueOnly(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var field = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { return null; }
		}
		return null;
	}

	private static object ResolveFirstStrongholdHeroArg(object[] args)
	{
		if (args == null)
			return null;
		for (var i = 0; i < args.Length; i++)
		{
			var arg = args[i];
			if (ResolveStrongholdHeroIconKey(arg) != null)
				return arg;
		}
		return null;
	}

	private static Image FindBestPortraitImage(object view)
	{
		if (view == null)
			return null;
		foreach (var name in GameSymbols.ImportVisuals.HeroPortraitImageFields)
		{
			var img = TryGetMemberValue(view, view.GetType(), name) as Image;
			if (img != null)
				return img;
		}
		return view is Component c ? FindPortraitImage(c) : null;
	}

	private static Image FindHeroHudPanelPortraitImage(BhHeroHUDPanel panel)
	{
		if (panel == null)
			return null;
		var heroView = TryGetFirstMemberValue(panel, GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields);
		var nested = TryGetFirstMemberValue(heroView, GameSymbols.ImportVisuals.TooltipHeroItemPortraitFields) as Image;
		if (nested != null)
			return nested;
		nested = FindBestPortraitImage(heroView);
		if (nested != null)
			return nested;
		return FindPortraitImage(panel);
	}

	private static void HideSummaryCardRandomPortraitOverlay(object view)
	{
		if (view == null)
			return;
		var typeName = view.GetType().FullName ?? view.GetType().Name ?? "";
		if (typeName.IndexOf("BhSummaryCard", StringComparison.OrdinalIgnoreCase) < 0)
			return;

		foreach (var field in GameSymbols.ImportVisuals.SummaryCardRandomPortraitFields)
			DisableGraphicOrObject(TryGetMemberValue(view, view.GetType(), field));
	}

	private static void DisableGraphicOrObject(object candidate)
	{
		if (candidate is Graphic graphic)
		{
			graphic.enabled = false;
			return;
		}
		if (candidate is Component component)
		{
			var nestedGraphic = component.GetComponent<Graphic>();
			if (nestedGraphic)
				nestedGraphic.enabled = false;
			else if (component.gameObject)
				component.gameObject.SetActive(false);
			return;
		}
		if (candidate is GameObject gameObject)
			gameObject.SetActive(false);
	}

	/// <summary>
	/// Find the "PORTRAIT" Image in the panel, resolve the hero SID from text labels,
	/// load the PNG sprite from the shared cache, and apply it.
	/// </summary>
	private static void TryApplyHeroPortrait(BhHeroHUDPanel panel, string source)
	{
		if (panel == null)
			return;

		try
		{
			// Resolve the hero SID from text labels on the panel
			var heroSid = ResolveStrongholdHeroIconKey(panel) ?? ResolveHeroSidFromPanel(panel, source);
			if (string.IsNullOrEmpty(heroSid))
				return;

			// Selected HUD panels usually keep the visible portrait on nested heroView.heroFace.
			if (TryGetHeroPortraitSprite(heroSid, out var sprite) && sprite)
			{
				RememberNestedHeroIdentities(panel, heroSid);
				var portraitImage = FindHeroHudPanelPortraitImage(panel);
				if (portraitImage != null)
				{
					ApplySpriteToImage(portraitImage, sprite);
					DumpImageTree(panel, source + ".afterApply");
					LogReplace(source, heroSid, sprite);
				}
				TryApplyNestedTooltipHeroView(panel, heroSid, sprite, source);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: " + source + " failed: " + ex.Message);
		}
	}

	/// <summary>
	/// Find the "PORTRAIT" Image on city garrison hero view.
	/// </summary>
	private static void TryApplyCityHeroPortrait(BhHeroWithPartyCityView view, string source)
	{
		if (view == null)
			return;

		try
		{
			var heroSid = ResolveHeroSidFromCityViewFieldOnly(view);
			if (string.IsNullOrEmpty(heroSid))
			{
				ClearCityHeroPortraitOverrideIfStale(view, source);
				return;
			}
			SetCityHeroWithPartyVisible(view, true, source, "current-hero");

			var portraitImage = FindCityHeroPortraitImageFieldOnly(view);
			if (portraitImage == null)
				return;

			if (TryGetHeroPortraitSprite(heroSid, out var sprite) && sprite)
			{
				ApplySpriteToImage(portraitImage, sprite);
				LogReplace(source, heroSid, sprite);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: city " + source + " failed: " + ex.Message);
		}
	}

	private static void ClearCityHeroPortraitOverrideIfStale(BhHeroWithPartyCityView view, string source)
	{
		if (view == null)
			return;
		try
		{
			var heroView = TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.CityHeroWithPartyTooltipFields);
			ForgetHeroSurface(view);
			if (heroView != null)
				ForgetHeroSurface(heroView);
			SetCityHeroWithPartyVisible(view, false, source, "no-current-hero");

			var portraitImage = FindCityHeroPortraitImageFieldOnly(view);
			if (portraitImage == null || !IsCustomHeroPortraitSprite(portraitImage.sprite, portraitImage.overrideSprite))
				return;

			portraitImage.sprite = null;
			portraitImage.overrideSprite = null;
			portraitImage.enabled = false;
			Homm3UiCardDiagnostics.Log(
				"town-unit-card-hero-portrait",
				"hero-portrait-cleared",
				"source='" + (source ?? "?") + "' reason='no-current-hero'",
				limit: 24);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: city clear " + source + " failed: " + ex.Message);
		}
	}

	private static void SetCityHeroWithPartyVisible(BhHeroWithPartyCityView view, bool visible, string source, string reason)
	{
		if (view == null)
			return;
		try
		{
			var canvasGroup = TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.CityHeroWithPartyCanvasGroupFields) as CanvasGroup;
			if (canvasGroup == null)
				return;
			canvasGroup.alpha = visible ? 1f : 0f;
			canvasGroup.interactable = visible;
			canvasGroup.blocksRaycasts = visible;
			Homm3UiCardDiagnostics.Log(
				"town-unit-card-hero-portrait",
				visible ? "hero-card-shown" : "hero-card-hidden",
				"source='" + (source ?? "?") + "' reason='" + (reason ?? "?") + "'",
				limit: 24);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: city visibility " + source + " failed: " + ex.Message);
		}
	}

	private static void ForgetHeroSurface(object view)
	{
		if (view == null)
			return;
		_strongholdHeroIconKeyByView.Remove(GetStableObjectKey(view));
	}

	private static bool IsCustomHeroPortraitSprite(Sprite sprite, Sprite overrideSprite)
	{
		return IsCustomHeroPortraitSprite(sprite) || IsCustomHeroPortraitSprite(overrideSprite);
	}

	private static bool IsCustomHeroPortraitSprite(Sprite sprite)
	{
		if (!sprite)
			return false;
		var name = sprite.name;
		if (string.IsNullOrWhiteSpace(name))
			return false;
		if (name.StartsWith("homm3_static_portrait_", StringComparison.Ordinal))
			return true;
		return Homm3CustomFactionRegistry.IsCustomHeroSid(name);
	}

	/// <summary>
	/// Find the Image component whose GameObject is named "PORTRAIT".
	/// This is the heroFace on both BhHeroHUDPanel and BhHeroWithPartyCityView.
	/// </summary>
	private static Image FindPortraitImage(Component root)
	{
		if (root == null)
			return null;

		var images = root.GetComponentsInChildren<Image>(true);
		foreach (var img in images)
		{
			if (img == null)
				continue;
			if (img.gameObject != null && string.Equals(img.gameObject.name, "PORTRAIT", StringComparison.Ordinal))
				return img;
		}
		return null;
	}

	private static bool TryGetHeroPortraitSprite(string heroSid, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(heroSid))
			return false;
		return Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(heroSid, out sprite)
			|| Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(heroSid, out sprite);
	}

	private static void TryApplyNestedTooltipHeroView(object root, string heroSid, Sprite sprite, string source)
	{
		if (root == null || string.IsNullOrWhiteSpace(heroSid) || !sprite)
			return;
		try
		{
			var targets = new List<object>();
			var direct = TryGetFirstMemberValue(root, GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields);
			if (direct != null)
				targets.Add(direct);
			if (root is Component c)
			{
				var components = c.GetComponentsInChildren<Component>(true);
				foreach (var comp in components)
				{
					if (comp == null)
						continue;
					var full = comp.GetType().FullName ?? "";
					if (full.EndsWith(".BhTooltipHeroItemView", StringComparison.Ordinal) || full == "BhTooltipHeroItemView")
						targets.Add(comp);
				}
			}
			foreach (var target in targets)
			{
				var nestedSource = source + ".nestedHeroView";
				RememberHeroSurface(target, heroSid, nestedSource);
				var image = FindBestPortraitImage(target);
				if (image == null)
					continue;
				ApplySpriteToImage(image, sprite);
				DumpImageTree(target, source + ".nestedHeroView.afterApply");
				LogSurfaceReplace(source + ".nestedHeroView", heroSid, sprite, image);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: nested heroView " + source + " failed: " + ex.Message);
		}
	}

	/// <summary>
	/// Resolve the hero SID from the BhHeroHUDPanel by reading TextMeshProUGUI labels.
	/// The hero name text (e.g., "Gird", "Crag Hack") is mapped to homm3_stronghold_hero_N.
	/// Also tries accessing BhHUDSession.me to get the hero configSid via property chain.
	/// </summary>
	private static string ResolveHeroSidFromPanel(BhHeroHUDPanel panel, string source)
	{
		// Method 1: Walk TextMeshProUGUI components looking for hero names
		var texts = panel.GetComponentsInChildren<TextMeshProUGUI>(true);
		foreach (var txt in texts)
		{
			if (txt == null || string.IsNullOrWhiteSpace(txt.text))
				continue;
			var sidFromName = HeroNameToSid(txt.text.Trim());
			if (sidFromName != null)
			{
				LogAttempt(source, txt.text, sidFromName, "textMatch");
				return sidFromName;
			}
		}

		// Method 2: Try the nested tooltip hero view only through known fields.
		// Current release BhTooltipHeroItemView does not expose heroName/heroSid/configSid/sid properties;
		// probing them through Harmony AccessTools logs warnings during map load.
		try
		{
			var heroViewProp = FindPropertyQuiet(panel.GetType(), "heroView");
			if (heroViewProp != null)
			{
				var heroView = heroViewProp.GetValue(panel);
				var sid = ResolveStrongholdHeroIconKey(heroView);
				if (sid != null)
					return sid;
			}
		}
		catch { }

		// Method 3: Try BhHUDSession -> sides -> heroSid
		try
		{
			var hudType = ModActions.GetHexType("Hex.Session.Hud.BhHUDSession");
			if (hudType != null)
			{
				var hudMe = FindPropertyQuiet(hudType, "me")?.GetValue(null);
				if (hudMe != null)
				{
					// Try to find any string property that matches homm3_stronghold_hero pattern
					TryScanObjectForStrongholdHeroSid(hudMe, "BhHUDSession.me", source);
				}

				// Audit B5: static BhHeroHUDPanel.me is field_Public_Static_BhHeroHUDPanel_0 on live Golden Era.
				DeobfInteropCompat.TryGetStaticMember(typeof(BhHeroHUDPanel), out var activePanelObject, GameSymbols.LiveRenamedMembers.HeroHudPanelStaticMe);
				var activePanel = activePanelObject as BhHeroHUDPanel;
				var sid = ResolveStrongholdHeroIconKey(activePanel);
				if (sid != null)
					return sid;
			}
		}
		catch { }

		return null;
	}

	private static string ResolveHeroSidFromCityViewFieldOnly(BhHeroWithPartyCityView view)
	{
		if (view == null)
			return null;
		var direct = DeobfInteropCompat.GetSessionHeroPortraitKeyFieldOnly(view);
		if (!string.IsNullOrWhiteSpace(direct))
			return direct;
		var heroView = TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.CityHeroWithPartyTooltipFields);
		return DeobfInteropCompat.GetSessionHeroPortraitKeyFieldOnly(heroView)
			?? ResolveHeroIconKeyFieldOnly(TryGetFirstMemberValue(heroView, GameSymbols.ImportVisuals.TooltipHeroItemSessionHeroFields))
			?? ResolveHeroIconKeyFieldOnly(TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.CityHeroWithPartySessionHeroFields));
	}

	private static Image FindCityHeroPortraitImageFieldOnly(BhHeroWithPartyCityView view)
	{
		if (view == null)
			return null;
		var heroView = TryGetFirstMemberValue(view, GameSymbols.ImportVisuals.CityHeroWithPartyTooltipFields);
		return TryGetFirstMemberValue(heroView, GameSymbols.ImportVisuals.TooltipHeroItemPortraitFields) as Image;
	}

	private static string ResolveHeroIconKeyFieldOnly(object obj, int depth = 0)
	{
		if (obj == null || depth > 4)
			return null;
		if (obj is string directString && IsStrongholdHeroIconKey(directString))
			return directString.Trim();
		var compat = DeobfInteropCompat.GetSessionHeroPortraitKeyFieldOnly(obj);
		if (!string.IsNullOrWhiteSpace(compat))
			return compat;

		var type = obj.GetType();
		foreach (var name in GameSymbols.HeroProfile.HeroConfigFields)
		{
			var value = TryGetMemberValue(obj, type, name) as string;
			if (IsStrongholdHeroIconKey(value))
				return value.Trim();
		}

		foreach (var name in GameSymbols.ImportVisuals.SessionHeroConfigFields)
		{
			var nested = TryGetMemberValue(obj, type, name);
			var nestedKey = ResolveHeroIconKeyFieldOnly(nested, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.ImportVisuals.SessionHeroWrapperHeroFields)
		{
			var nested = TryGetFieldValueOnly(obj, type, name);
			var nestedKey = ResolveHeroIconKeyFieldOnly(nested, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.HeroProfile.HeroConfigNestedFields)
		{
			var nested = TryGetMemberValue(obj, type, name);
			var nestedKey = ResolveHeroIconKeyFieldOnly(nested, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in GameSymbols.HeroProfile.HeroConfigGetters)
		{
			if (!CanInvokeHeroConfigGetter(name))
				continue;
			var nested = TryInvokeNoArg(obj, type, name);
			var nestedKey = ResolveHeroIconKeyFieldOnly(nested, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		return null;
	}

	private static void RememberHeroIdentityTree(object obj, string iconKey)
	{
		if (obj == null || string.IsNullOrWhiteSpace(iconKey) || !IsStrongholdHeroIconKey(iconKey))
			return;
		RememberHeroIdentityTree(obj, iconKey.Trim(), new HashSet<int>(), 0);
	}

	private static void RememberNestedHeroIdentities(object root, string iconKey)
	{
		if (root == null || string.IsNullOrWhiteSpace(iconKey) || !IsStrongholdHeroIconKey(iconKey))
			return;
		var type = root.GetType();
		foreach (var name in GameSymbols.HeroProfile.HeroStateFields)
			RememberHeroIdentityTree(TryGetMemberValue(root, type, name), iconKey);
		foreach (var name in GameSymbols.ImportVisuals.TooltipHeroItemSessionHeroFields)
			RememberHeroIdentityTree(TryGetMemberValue(root, type, name), iconKey);
		foreach (var name in GameSymbols.ImportVisuals.SessionHeroWrapperHeroFields)
			RememberHeroIdentityTree(TryGetFieldValueOnly(root, type, name), iconKey);
	}

	private static void RememberHeroIdentityTree(object obj, string iconKey, HashSet<int> seen, int depth)
	{
		if (obj == null || depth > 2)
			return;
		var key = RuntimeHelpersGetHashCode(obj);
		if (!seen.Add(key))
			return;
		_strongholdHeroIconKeyByObject[GetStableObjectKey(obj)] = iconKey;
		var type = obj.GetType();
		foreach (var name in GameSymbols.HeroProfile.HeroStateFields)
			RememberHeroIdentityTree(TryGetMemberValue(obj, type, name), iconKey, seen, depth + 1);
		foreach (var name in GameSymbols.ImportVisuals.TooltipHeroItemSessionHeroFields)
			RememberHeroIdentityTree(TryGetMemberValue(obj, type, name), iconKey, seen, depth + 1);
		foreach (var name in GameSymbols.ImportVisuals.SessionHeroWrapperHeroFields)
			RememberHeroIdentityTree(TryGetFieldValueOnly(obj, type, name), iconKey, seen, depth + 1);
	}

	private static long GetStableObjectKey(object obj)
	{
		if (obj is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
			return il2Cpp.Pointer.ToInt64();
		return RuntimeHelpersGetHashCode(obj);
	}

	private static object TryGetFirstMemberValue(object obj, IEnumerable<string> names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		foreach (var name in names)
		{
			var value = TryGetMemberValue(obj, type, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static void ApplySpriteToImage(Image image, Sprite sprite)
	{
		if (image == null || !sprite)
			return;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = Color.white;
	}

	private static void RememberHeroSurface(object view, string iconKey, string source)
	{
		if (view == null || string.IsNullOrWhiteSpace(iconKey))
			return;
		var key = GetStableObjectKey(view);
		var trimmed = iconKey.Trim();
		_strongholdHeroIconKeyByView[key] = trimmed;
		LastStrongholdHeroIconKey = trimmed;
		if (_loggedRememberedSurface >= 20)
			return;
		_loggedRememberedSurface++;
		var component = view as Component;
		Plugin.LogSource?.LogInfo(
			"Homm3HeroPortrait: remembered surface ["
			+ source
			+ "] iconKey='"
			+ iconKey
			+ "' type='"
			+ (view.GetType().FullName ?? view.GetType().Name)
			+ "' name='"
			+ (component != null && component.gameObject != null ? component.gameObject.name : "?")
			+ "' circularAlpha=true"
			+ "'.");
	}

	private static void DumpImageTree(object root, string source)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_hero_portrait_diag.flag"))
			return;
		if (_loggedImageTree >= 10)
			return;
		var component = root as Component;
		if (component == null)
			return;
		_loggedImageTree++;
		try
		{
			var images = component.GetComponentsInChildren<Image>(true);
			var count = 0;
			foreach (var img in images)
			{
				if (img == null || count >= 30)
					continue;
				count++;
				Plugin.LogSource?.LogInfo(
					"Homm3HeroPortrait diag image ["
					+ source
					+ "] name='"
					+ (img.gameObject ? img.gameObject.name : "?")
					+ "' enabled="
					+ img.enabled
					+ " active="
					+ (img.gameObject && img.gameObject.activeInHierarchy)
					+ " sprite='"
					+ (img.sprite ? img.sprite.name : "?")
					+ "' override='"
					+ (img.overrideSprite ? img.overrideSprite.name : "?")
					+ "' color='"
					+ img.color
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Homm3HeroPortrait: image dump failed: " + ex.Message);
		}
	}

	private static string TryExtractConfigSid(object hero)
	{
		if (hero == null)
			return null;

		var t = hero.GetType();
		foreach (var name in new[] { "configSid", "sid", "id", "heroSid" })
		{
			try
			{
				var p = FindPropertyQuiet(t, name);
				if (p != null)
				{
					var v = p.GetValue(hero);
					if (v is string s && !string.IsNullOrWhiteSpace(s)
						&& IsStrongholdHeroIconKey(s))
						return s.Trim();
				}
			}
			catch { }

			try
			{
				var f = FindFieldQuiet(t, name);
				if (f != null)
				{
					var v = f.GetValue(hero);
					if (v is string s && !string.IsNullOrWhiteSpace(s)
						&& IsStrongholdHeroIconKey(s))
						return s.Trim();
				}
			}
			catch { }
		}
		return null;
	}

	private static PropertyInfo FindPropertyQuiet(Type type, string name)
	{
		return type?.GetProperty(name, BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
	}

	private static FieldInfo FindFieldQuiet(Type type, string name)
	{
		return type?.GetField(name, BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
	}

	private static string TryScanObjectForStrongholdHeroSid(object obj, string label, string source)
	{
		if (obj == null)
			return null;

		var t = obj.GetType();
		foreach (var p in t.GetProperties(System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic))
		{
			try
			{
				if (p.PropertyType == typeof(string))
				{
					var v = p.GetValue(obj) as string;
					if (!string.IsNullOrWhiteSpace(v) && IsStrongholdHeroIconKey(v))
						return v.Trim();
				}
			}
			catch { }
		}
		return null;
	}

	// ── Hero name → index mapping ────────────────────────────────────────

	private static string HeroNameToSid(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return null;
		if (TryResolveHeroNameFromManifest(name, out var manifestSid))
			return manifestSid;
		switch (name.Trim())
		{
			case "Piquedram": return "homm3_tower_hero_1";
			case "Thane": return "homm3_tower_hero_2";
			case "Josephine": return "homm3_tower_hero_3";
			case "Neela": return "homm3_tower_hero_4";
			case "Torosar": return "homm3_tower_hero_5";
			case "Fafner": return "homm3_tower_hero_6";
			case "Rissa": return "homm3_tower_hero_7";
			case "Iona": return "homm3_tower_hero_8";
			case "Astral": return "homm3_tower_hero_9";
			case "Halon": return "homm3_tower_hero_10";
			case "Serena": return "homm3_tower_hero_11";
			case "Daremyth": return "homm3_tower_hero_12";
			case "Theodorus": return "homm3_tower_hero_13";
			case "Solmyr": return "homm3_tower_hero_14";
			case "Cyra": return "homm3_tower_hero_15";
			case "Aine": return "homm3_tower_hero_16";
		}
		return null;
	}

	private static bool TryResolveHeroNameFromManifest(string name, out string sid)
	{
		sid = null;
		var table = GetHeroSidByDisplayName();
		return table != null && table.TryGetValue(NormalizeHeroDisplayName(name), out sid) && !string.IsNullOrWhiteSpace(sid);
	}

	private static Dictionary<string, string> GetHeroSidByDisplayName()
	{
		if (_heroSidByDisplayName != null)
			return _heroSidByDisplayName;
		var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
		try
		{
			var manifestPath = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "homm3_hero_portraits", "manifest.json");
			if (!File.Exists(manifestPath))
			{
				_heroSidByDisplayName = result;
				return _heroSidByDisplayName;
			}
			var root = JObject.Parse(File.ReadAllText(manifestPath));
			var entriesToken = root["entries"];
			if (entriesToken != null)
			{
				var entriesJson = entriesToken.ToString(Newtonsoft.Json.Formatting.None);
				var matches = System.Text.RegularExpressions.Regex.Matches(
					entriesJson,
					"\"(?<sid>homm3_[^\"]+_hero_\\d+)\"\\s*:\\s*\\{(?<body>.*?)\"name\"\\s*:\\s*\"(?<name>[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*)\"",
					System.Text.RegularExpressions.RegexOptions.Singleline);
				for (var i = 0; i < matches.Count; i++)
				{
					var heroSid = UnescapeJsonString(matches[i].Groups["sid"].Value);
					var displayName = UnescapeJsonString(matches[i].Groups["name"].Value);
					if (!Homm3CustomFactionRegistry.IsCustomHeroSid(heroSid) || string.IsNullOrWhiteSpace(displayName))
						continue;
					var key = NormalizeHeroDisplayName(displayName);
					if (!string.IsNullOrWhiteSpace(key) && !result.ContainsKey(key))
						result[key] = heroSid;
				}
			}
			Plugin.LogSource?.LogInfo("Homm3HeroPortrait: loaded " + result.Count + " hero name portrait mapping(s) from manifest.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3HeroPortrait: failed to load hero portrait name manifest: " + ex.Message);
		}
		_heroSidByDisplayName = result;
		return _heroSidByDisplayName;
	}

	private static string UnescapeJsonString(string value)
	{
		if (string.IsNullOrEmpty(value))
			return value;
		try
		{
			return JToken.Parse("\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"").ToString();
		}
		catch
		{
			return value.Replace("\\\"", "\"").Replace("\\\\", "\\");
		}
	}

	private static string NormalizeHeroDisplayName(string name)
	{
		return string.IsNullOrWhiteSpace(name) ? "" : name.Trim();
	}

	private static void LogReplace(string source, string sid, Sprite sprite)
	{
		LogUiCardDiagnostic(source, "hero-portrait-replaced", "sid='" + sid + "' sprite='" + (sprite ? sprite.name : "?") + "'");
		if (_loggedReplace >= 30)
			return;
		if (!IsVerboseHeroPortraitDiagnosticsEnabled())
			return;
		_loggedReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3HeroPortrait: replaced [" + source + "] sid='" + sid + "' sprite='" + (sprite ? sprite.name : "?") + "'.");
	}

	private static void LogSurfaceReplace(string source, string iconKey, Sprite sprite, Image image)
	{
		LogUiCardDiagnostic(
			source,
			"hero-portrait-surface-replaced",
			"iconKey='" + iconKey + "' image='" + (image && image.gameObject ? image.gameObject.name : "?")
			+ "' sprite='" + (sprite ? sprite.name : "?") + "'");
		if (_loggedSurfaceReplace >= 40)
			return;
		if (!IsVerboseHeroPortraitDiagnosticsEnabled())
			return;
		_loggedSurfaceReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3HeroPortrait: surface replaced ["
			+ source
			+ "] iconKey='"
			+ iconKey
			+ "' image='"
			+ (image && image.gameObject ? image.gameObject.name : "?")
			+ "' sprite='"
			+ (sprite ? sprite.name : "?")
			+ "' override='"
			+ (image && image.overrideSprite ? image.overrideSprite.name : "?")
			+ "'.");
	}

	private static void LogRefreshReplace(string source, string iconKey, Sprite sprite, Image image)
	{
		LogUiCardDiagnostic(
			source,
			"hero-portrait-refresh-replaced",
			"iconKey='" + iconKey + "' image='" + (image && image.gameObject ? image.gameObject.name : "?")
			+ "' sprite='" + (sprite ? sprite.name : "?") + "'");
		if (_loggedRefreshReplace >= 40)
			return;
		if (!IsVerboseHeroPortraitDiagnosticsEnabled())
			return;
		_loggedRefreshReplace++;
		Plugin.LogSource?.LogInfo(
			"Homm3HeroPortrait: refresh replaced ["
			+ source
			+ "] iconKey='"
			+ iconKey
			+ "' image='"
			+ (image && image.gameObject ? image.gameObject.name : "?")
			+ "' sprite='"
			+ (sprite ? sprite.name : "?")
			+ "' override='"
			+ (image && image.overrideSprite ? image.overrideSprite.name : "?")
			+ "'.");
	}

	private static void LogAttempt(string source, string name, string sid, string method)
	{
		LogUiCardDiagnostic(source, "hero-portrait-attempt", "name='" + name + "' sid='" + sid + "' method=" + method);
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_hero_portrait_diag.flag"))
			return;
		if (_loggedAttempts >= 10)
			return;
		_loggedAttempts++;
		Plugin.LogSource?.LogInfo(
			"Homm3HeroPortrait: attempt [" + source + "] name='" + name + "' -> sid='" + sid + "' method=" + method);
	}

	private static void LogUiCardDiagnostic(string source, string evt, string detail)
	{
		Homm3UiCardDiagnostics.Log(ClassifyUiCardSurface(source), evt, "source='" + (source ?? "?") + "' " + detail);
	}

	private static bool IsVerboseHeroPortraitDiagnosticsEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_hero_portrait_diag.flag")
		       || Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag");
	}

	private static string ClassifyUiCardSurface(string source)
	{
		if (source == null)
			return "hero-portrait";
		if (source.IndexOf("BhHeroWithPartyCityView", StringComparison.OrdinalIgnoreCase) >= 0)
			return "town-unit-card-hero-portrait";
		if (source.IndexOf("BhHeroHUDPanel", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("BhHeroUIElement", StringComparison.OrdinalIgnoreCase) >= 0)
			return "adventure-map-unit-card-hero-portrait";
		if (source.IndexOf("BhHeroProfileWindow", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("BhHeroPortraitView", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("heroDataView", StringComparison.OrdinalIgnoreCase) >= 0)
			return "inventory-screen-hero-portrait";
		if (source.IndexOf("BhSummaryCard", StringComparison.OrdinalIgnoreCase) >= 0
		    || source.IndexOf("HeroConfig surface", StringComparison.OrdinalIgnoreCase) >= 0)
			return "custom-game-faction-hover-unit-card-portraits";
		if (source.IndexOf("BhTavernHeroView", StringComparison.OrdinalIgnoreCase) >= 0)
			return "inventory-screen-hero-portrait";
		return "hero-portrait";
	}
}
