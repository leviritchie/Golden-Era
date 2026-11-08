using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Logic;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Narrow release battle UI portrait remap. Keep this separate from the old selected-HUD guard:
/// the runtime-manifest path can register selected HUD, selected-unit view, turn queue, and hero-view surfaces independently.
/// </summary>
internal static class Homm3ImportReleaseBattleUiHook
{
	private const string UiIconDiagnosticFlagName = "homm3_ui_icon_diag.flag";
	private static bool _patchedSelectedHud;
	private static bool _patchedSelectedUnitView;
	private static bool _patchedTurnQueue;
	private static bool _patchedHeroViews;
	private static bool _diagnosticsEnabled;
	private static int _loggedPatch;
	private static int _loggedUnitPortrait;
	private static int _loggedHeroPortrait;
	private static int _loggedMiss;
	private static int _loggedTurnViewMiss;
	private static int _loggedTurnItemMiss;
	private static int _loggedTurnViewSpriteSetter;
	private static int _loggedTimelineSetterProbe;
	private static int _loggedBattleRootProbe;
	private static int _loggedBattleSceneProbe;
	private static int _loggedBattleSceneProbeItem;
	private static int _loggedQueueAlias;
	private static bool _battleUiSeen;
	private static int _loggedBattleResultUnitPortrait;
	private static int _loggedBattleResultHeroPortrait;
	private static int _loggedBattleResultHeroPortraitMiss;
	private static int _loggedBattleResultHeroDiag;
	private static int _loggedBattleHeroOverlayHidden;
	private static int _loggedBattleHeroImageTree;
	private static string _lastBattleHeroIconKey;
	// Icon key each battle hero view last bound to; Refresh (no hero arg) reuses its own view's key.
	private static readonly Dictionary<int, string> BattleHeroIconKeyByView = new();
	private static readonly Dictionary<int, SimulatedBattleSides> LastBattleResultSidesByRoot = new();

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		Register(
			h,
			log,
			selectedHud: true,
			selectedUnitView: true,
			turnQueue: true,
			heroViews: true,
			diagnostics: true,
			required: false,
			label: "full legacy battle UI");
	}

	internal static void RegisterRequiredReleaseSafeSlice(
		Harmony h,
		ManualLogSource log,
		bool selectedHud,
		bool selectedUnitView,
		bool turnQueue,
		bool heroViews,
		bool diagnostics)
	{
		Register(
			h,
			log,
			selectedHud,
			selectedUnitView,
			turnQueue,
			heroViews,
			diagnostics,
			required: true,
			label: "release-safe micro-gated battle UI");
	}

	private static void Register(
		Harmony h,
		ManualLogSource log,
		bool selectedHud,
		bool selectedUnitView,
		bool turnQueue,
		bool heroViews,
		bool diagnostics,
		bool required,
		string label)
	{
		_diagnosticsEnabled |= diagnostics;
		if (h == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required battle UI registration.");
			return;
		}

		var patched = 0;
		if (selectedHud && !_patchedSelectedHud)
		{
			var selectedHudPatched = PatchSelectedHudPostfixes(h, log);
			if (selectedHudPatched == 0 && required)
				throw new MissingMethodException("Homm3Import release battle UI: required selected-HUD bind surfaces not found.");
			if (selectedHudPatched > 0)
				_patchedSelectedHud = true;
			patched += selectedHudPatched;
		}
		if (selectedUnitView && !_patchedSelectedUnitView)
		{
			var selectedUnitViewPatched = PatchSelectedUnitViewBind(h, log);
			if (selectedUnitViewPatched == 0 && required)
				throw new MissingMethodException("Homm3Import release battle UI: required selected-unit view bind surface not found.");
			if (selectedUnitViewPatched > 0)
				_patchedSelectedUnitView = true;
			patched += selectedUnitViewPatched;
		}
		if (turnQueue && !_patchedTurnQueue)
		{
			var turnQueuePatched = 0;
			turnQueuePatched += PatchTurnViewPostfixes(h, log);
			var queueLayoutPatched = PatchBattleQueueViewPostfixes(h, log);
			turnQueuePatched += queueLayoutPatched;
			turnQueuePatched += PatchTurnItemPostfixes(h, log);
			if (required && queueLayoutPatched == 0)
				throw new MissingMethodException("Homm3Import release battle UI: required exact turn-queue layout surface not found.");
			if (turnQueuePatched > 0)
				_patchedTurnQueue = true;
			patched += turnQueuePatched;
		}
		if (heroViews && !_patchedHeroViews)
		{
			var heroViewsPatched = 0;
			heroViewsPatched += PatchBattleHeroViewPostfixes(h, log);
			heroViewsPatched += PatchSimulatedBattleHeroesViewPostfixes(h, log);
			heroViewsPatched += PatchBattleResultPostfixes(h, log);
			heroViewsPatched += PatchBattleResultHeroPortraitPostfixes(h, log);
			if (heroViewsPatched == 0 && required)
				throw new MissingMethodException("Homm3Import release battle UI: required hero-view/result surfaces not found.");
			if (heroViewsPatched > 0)
				_patchedHeroViews = true;
			patched += heroViewsPatched;
		}

		if (patched == 0)
			log?.LogWarning("Homm3Import release battle UI: no " + label + " portrait patches registered.");
		else
			log?.LogInfo("Homm3Import release battle UI: registered " + patched + " " + label + " portrait patch(es).");
	}

	private static int PatchSelectedHudPostfixes(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		patched += PatchPostfixBySecondParameterType(
			h,
			log,
			typeof(BhSelectedUnitHud),
			GameSymbols.BattleUi.SelectedHudEventBind.NameHints,
			typeof(BattleEventArgs),
			nameof(PostfixSelectedUnitHudBind),
			"selected-HUD event bind");
		patched += PatchPostfixBySecondParameterType(
			h,
			log,
			typeof(BhSelectedUnitHud),
			GameSymbols.BattleUi.SelectedHudDirectBind.NameHints,
			typeof(Unit),
			nameof(PostfixSelectedUnitHudDirectBind),
			"selected-HUD direct bind");
		return patched;
	}

	private static int PatchSimulatedBattleHeroesViewPostfixes(Harmony h, ManualLogSource log)
	{
		var type = typeof(BhTurnView).Assembly.GetType("Hex.BhSimulatedBattleHeroesView", throwOnError: false)
		           ?? typeof(BhTurnView).Assembly.GetType("BhSimulatedBattleHeroesView", throwOnError: false);
		if (type == null)
			return 0;
		var method = FindMethodByNameAndArity(type, "Init", 2);
		if (method == null)
		{
			log?.LogWarning("Homm3Import release battle UI: BhSimulatedBattleHeroesView.Init(TransferSide,TransferSide) not found; auto-battle hero preview hook skipped.");
			return 0;
		}
		try
		{
			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixSimulatedBattleHeroesViewInit)));
			if (_loggedPatch < 12)
			{
				_loggedPatch++;
				log?.LogInfo("Homm3Import release battle UI: auto-battle hero preview postfix registered on " + FormatMethod(method) + ".");
			}
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle UI: auto-battle hero preview patch failed for " + FormatMethod(method) + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchBattleResultPostfixes(Harmony h, ManualLogSource log)
	{
		// Real-name type: Hex.Session.Hud on Golden Era, moved to Hex.UI.SimBattle on build 25672315.
		var type = typeof(BhTurnView).Assembly.GetType("Hex.Session.Hud.BhSimulatedBattle", throwOnError: false)
		           ?? typeof(BhTurnView).Assembly.GetType("Hex.UI.SimBattle.BhSimulatedBattle", throwOnError: false);
		if (type == null)
			return 0;
		var patched = 0;
		var transferPostfix = new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixBattleResultArmyBind));
		var refreshPostfix = new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixBattleResultRefresh));
		var refreshMethodNames = new HashSet<string>(GameSymbols.ReleaseTownUi.SimulatedBattleResultRefresh.NameHints, StringComparer.Ordinal);
		var patchRefreshMethods = IsVerboseBattleUiDiagnosticsEnabled();
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType != typeof(void))
				continue;
			if (method.ContainsGenericParameters || method.IsGenericMethod || method.IsGenericMethodDefinition)
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 2 && ps[0].ParameterType == typeof(TransferSide) && ps[1].ParameterType == typeof(TransferSide))
			{
				try
				{
					h.Patch(method, postfix: transferPostfix);
					patched++;
				}
				catch (Exception ex)
				{
					log?.LogWarning("Homm3Import release battle UI: battle result army bind patch failed for " + FormatMethod(method) + ": " + ex.Message);
				}
				continue;
			}
			if (patchRefreshMethods && ps.Length == 0 && refreshMethodNames.Contains(method.Name))
			{
				try
				{
					h.Patch(method, postfix: refreshPostfix);
					patched++;
				}
				catch (Exception ex)
				{
					log?.LogWarning("Homm3Import release battle UI: battle result refresh patch failed for " + FormatMethod(method) + ": " + ex.Message);
				}
			}
		}
		if (patched > 0 && _loggedPatch < 12)
		{
			_loggedPatch++;
			log?.LogInfo("Homm3Import release battle UI: battle-result unit portrait postfix registered on " + patched + " BhSimulatedBattle method(s).");
		}
		return patched;
	}

	private static int PatchBattleQueueViewPostfixes(Harmony h, ManualLogSource log)
	{
		var type = typeof(BhTurnView).Assembly.GetType("Hex.Session.Battle.BhBattleQueueView", throwOnError: false)
		           ?? typeof(BhTurnView).Assembly.GetType("BhBattleQueueView", throwOnError: false);
		if (type == null)
		{
			log?.LogWarning("Homm3Import release battle UI: BhBattleQueueView type not found; queue layout hook skipped.");
			return 0;
		}
		var method = FindQueueLayoutMethod(type);
		if (method == null)
		{
			log?.LogWarning("Homm3Import release battle UI: exact BhBattleQueueView queue layout List<turn-item> method not found; queue layout hook skipped.");
			return 0;
		}
		try
		{
			h.Patch(method,
				prefix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PrefixBattleQueueLayout)),
				finalizer: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(FinalizerBattleQueueLayout)));
			if (_loggedPatch < 12)
			{
				_loggedPatch++;
				log?.LogInfo("Homm3Import release battle UI: queue layout alias/finalizer registered on " + FormatMethod(method) + ".");
			}
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle UI: queue layout patch failed for " + FormatMethod(method) + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchBattleResultHeroPortraitPostfixes(Harmony h, ManualLogSource log)
	{
		var type = typeof(BhTurnView).Assembly.GetType("Hex.Session.Hud.BhHeroPortrait", throwOnError: false);
		if (type == null)
			return 0;
		var patched = 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			var shapeBind = ps.Length == 2
			                && ps[0].ParameterType == typeof(string)
			                && string.Equals(ps[1].ParameterType.Name, "TypeResultHero", StringComparison.Ordinal);
			var legacyRefresh = Array.IndexOf(GameSymbols.BattleUi.ResultHeroPortraitRefresh.NameHints, method.Name) >= 0;
			if (!shapeBind && !legacyRefresh)
				continue;
			try
			{
				h.Patch(method, postfix: new HarmonyMethod(
					typeof(Homm3ImportReleaseBattleUiHook),
					shapeBind ? nameof(PostfixBattleResultHeroPortraitBind) : nameof(PostfixBattleResultHeroPortraitRefreshSimple)));
				patched++;
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import release battle UI: result hero portrait patch failed for " + FormatMethod(method) + ": " + ex.Message);
			}
		}
		if (patched > 0 && _loggedPatch < 12)
		{
			_loggedPatch++;
			log?.LogInfo("Homm3Import release battle UI: result hero portrait postfix registered on " + patched + " BhHeroPortrait method(s).");
		}
		return patched;
	}

	private static int PatchBattleHeroViewPostfixes(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		var seen = new HashSet<MethodInfo>();
		patched += PatchPostfix(h, log, typeof(BhHeroView), "Init", 0, nameof(PostfixBattleHeroRefresh));
		foreach (var method in typeof(BhHeroView).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method == null || method.ReturnType != typeof(void) || method.ContainsGenericParameters || method.IsSpecialName)
				continue;
			var name = method.Name ?? string.Empty;
			if (name.StartsWith("get_", StringComparison.Ordinal) || name.StartsWith("set_", StringComparison.Ordinal))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != 1 || !seen.Add(method))
				continue;
			if (ps[0].ParameterType == typeof(Hero))
			{
				patched += PatchExistingPostfix(h, log, method, nameof(PostfixBattleHeroBind));
				continue;
			}
			if (string.Equals(ps[0].ParameterType.Name, "eii", StringComparison.Ordinal))
				patched += PatchExistingPostfix(h, log, method, nameof(PostfixBattleHeroSideBind));
		}
		return patched;
	}

	private static int PatchSelectedUnitViewBind(Harmony h, ManualLogSource log)
	{
		var type = typeof(BhTurnView).Assembly.GetType("Hex.Session.Battle.BhSelectedUnitView", throwOnError: false)
		           ?? typeof(BhSelectedUnitView);
		var names = GameSymbols.BattleUi.SelectedUnitViewBind.NameHints;
		var patched = 0;
		var seen = new HashSet<MethodInfo>();
		MethodInfo shapeMatch = null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || !seen.Add(method))
					continue;
				if (!MatchesSelectedUnitViewBindShape(method))
					continue;
				try
				{
					h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixSelectedUnitViewBind)));
					patched++;
					if (_loggedPatch < 12)
					{
						_loggedPatch++;
						log?.LogInfo("Homm3Import release battle UI: selected-unit view postfix registered on " + FormatMethod(method) + ".");
					}
					return patched;
				}
				catch (Exception ex)
				{
					log?.LogWarning("Homm3Import release battle UI: selected-unit view patch failed for " + FormatMethod(method) + ": " + ex.Message);
				}
			}
		}

		foreach (var method in type.GetMethods(flags))
		{
			if (method.IsStatic || !seen.Add(method))
				continue;
			if (!MatchesSelectedUnitViewBindShape(method))
				continue;
			shapeMatch ??= method;
			break;
		}

		if (shapeMatch != null)
		{
			try
			{
				h.Patch(shapeMatch, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixSelectedUnitViewBind)));
				patched++;
				if (_loggedPatch < 12)
				{
					_loggedPatch++;
					log?.LogInfo("Homm3Import release battle UI: selected-unit view shape-match postfix registered on " + FormatMethod(shapeMatch) + ".");
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import release battle UI: selected-unit view shape-match patch failed for " + FormatMethod(shapeMatch) + ": " + ex.Message);
			}
		}

		if (patched == 0)
			log?.LogWarning("Homm3Import release battle UI: BhSelectedUnitView one-string binder not found; selected HUD portrait lookup guard skipped.");
		return patched;
	}

	private static bool MatchesSelectedUnitViewBindShape(MethodInfo method)
	{
		if (method == null || method.ReturnType != typeof(void))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 1 && ParameterTypesMatch(ps[0].ParameterType, typeof(string));
	}

	private static int PatchTurnItemPostfixes(Harmony h, ManualLogSource log)
	{
		log?.LogWarning("Homm3Import release battle UI: direct elq turn-item portrait postfixes disabled; live 0.1.259 logs showed elq.beou(TurnState,bool) recursing through the IL2CPP patch trampoline after tactics.");
		return 0;
	}

	private static int PatchTurnViewPoolPostfixes(Harmony h, ManualLogSource log)
	{
		var type = typeof(BhTurnView).Assembly.GetType("Hex.Session.Battle.BhTurnViewsPool", throwOnError: false)
		           ?? typeof(BhTurnView).Assembly.GetType("BhTurnViewsPool", throwOnError: false);
		if (type == null)
		{
			log?.LogWarning("Homm3Import release battle UI: BhTurnViewsPool type not found; turn-view pool hook skipped.");
			return 0;
		}

		var patched = 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
		{
			if (method == null || method.ReturnType != typeof(BhTurnView))
				continue;
			if (method.IsSpecialName || method.Name.StartsWith("get_", StringComparison.Ordinal) || method.Name.StartsWith("set_", StringComparison.Ordinal))
				continue;
			if (method.ContainsGenericParameters || method.IsGenericMethod || method.IsGenericMethodDefinition)
				continue;
			if (method.GetParameters().Length != 0)
				continue;
			try
			{
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixTurnViewPoolGet)));
				patched++;
				if (_loggedPatch < 12)
				{
					_loggedPatch++;
					log?.LogInfo("Homm3Import release battle UI: turn-view pool postfix registered on " + FormatMethod(method) + ".");
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import release battle UI: turn-view pool patch failed for " + FormatMethod(method) + ": " + ex.Message);
			}
		}
		return patched;
	}

	private static IEnumerable<Type> FindTurnItemTypes()
	{
		var yielded = new HashSet<Type>();
		var asm = typeof(BhTurnView).Assembly;
		foreach (var name in GameSymbols.BattleUi.TurnItemTypeNames)
		{
			var type = asm.GetType(name, throwOnError: false);
			if (LooksLikeKnownTurnItemType(type) && yielded.Add(type))
				yield return type;
		}
	}

	private static bool LooksLikeKnownTurnItemType(Type type)
	{
		if (type == null || type.IsAbstract || type.IsGenericType)
			return false;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		for (var i = 0; i < GameSymbols.BattleUi.TurnItemKnownUnitFields.Length && i < GameSymbols.BattleUi.TurnItemKnownViewFields.Length; i++)
		{
			if (HasDeclaredMember(type, flags, GameSymbols.BattleUi.TurnItemKnownUnitFields[i], typeof(Unit))
			    && HasDeclaredMember(type, flags, GameSymbols.BattleUi.TurnItemKnownViewFields[i], typeof(BhTurnView)))
				return true;
		}
		return HasDeclaredMemberOfType(type, flags, typeof(Unit))
		       && HasDeclaredMemberOfType(type, flags, typeof(BhTurnView));
	}

	private static bool HasDeclaredMemberOfType(Type type, BindingFlags flags, Type memberType)
	{
		if (type == null || memberType == null)
			return false;
		try
		{
			foreach (var field in type.GetFields(flags))
			{
				if (field != null && ParameterTypesMatch(field.FieldType, memberType))
					return true;
			}
		}
		catch { }
		try
		{
			foreach (var prop in type.GetProperties(flags))
			{
				if (prop != null
				    && prop.GetIndexParameters().Length == 0
				    && ParameterTypesMatch(prop.PropertyType, memberType))
					return true;
			}
		}
		catch { }
		return false;
	}

	private static bool HasDeclaredMember(Type type, BindingFlags flags, string name, Type memberType)
	{
		try
		{
			var field = type.GetField(name, flags);
			if (field != null && ParameterTypesMatch(field.FieldType, memberType))
				return true;
		}
		catch { }
		try
		{
			var prop = type.GetProperty(name, flags);
			if (prop != null && prop.GetIndexParameters().Length == 0 && ParameterTypesMatch(prop.PropertyType, memberType))
				return true;
		}
		catch { }
		try
		{
			var getter = type.GetMethod("get_" + name, flags);
			if (getter != null && getter.GetParameters().Length == 0 && ParameterTypesMatch(getter.ReturnType, memberType))
				return true;
		}
		catch { }
		return false;
	}

	private static bool LooksLikeTurnItemConstructor(MethodBase method)
	{
		if (method == null)
			return false;
		var ps = method.GetParameters();
		return ps.Length == 3
		       && ps[0].ParameterType == typeof(TurnState)
		       && ps[2].ParameterType == typeof(Unit)
		       && ps[1].ParameterType.FullName.IndexOf("BhTurnView", StringComparison.Ordinal) >= 0;
	}

	private static bool LooksLikeTurnItemRefreshMethod(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
			return false;
		if (method.ContainsGenericParameters || method.IsGenericMethod || method.IsGenericMethodDefinition)
			return false;
		var ps = method.GetParameters();
		if (ps.Length == 0)
			return true;
		if (ps.Length == 1)
			return ps[0].ParameterType == typeof(int)
			       || ps[0].ParameterType == typeof(TurnState);
		if (ps.Length != 2)
			return false;
		return (ps[0].ParameterType == typeof(TurnState) && ps[1].ParameterType == typeof(bool))
		       || (ps[0].ParameterType == typeof(float) && ps[1].ParameterType == typeof(float));
	}

	private static int PatchTurnItemMethod(Harmony h, ManualLogSource log, MethodBase method)
	{
		try
		{
			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), nameof(PostfixTurnItemRefresh)));
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle UI: turn-item patch failed for " + FormatMethod(method) + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchTurnViewPostfixes(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		var seen = new HashSet<MethodInfo>();
		foreach (var method in typeof(BhTurnView).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if ((ps.Length == 2 || ps.Length == 3)
			    && ps[0].ParameterType == typeof(Unit)
			    && ps[1].ParameterType == typeof(TurnState)
			    && (ps.Length == 2 || ps[2].ParameterType == typeof(bool))
			    && seen.Add(method))
			{
				patched += PatchTurnViewMethod(h, log, method, nameof(PostfixTurnViewUpdate));
			}
		}
		return patched;
	}

	private static int PatchBattleUiImageSetters(Harmony h, ManualLogSource log)
	{
		log?.LogWarning("Homm3Import release battle UI: global Image/RawImage setter prefixes disabled; release IL2CPP can crash while resolving Unity UI setters at plugin load.");
		return 0;
	}

	private static int PatchTurnViewMethod(Harmony h, ManualLogSource log, MethodInfo method, string postfixName)
	{
		try
		{
			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), postfixName));
			if (_loggedPatch < 12)
			{
				_loggedPatch++;
				log?.LogInfo("Homm3Import release battle UI: turn-view postfix registered on " + FormatMethod(method) + ".");
			}
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle UI: turn-view patch failed for " + FormatMethod(method) + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchExistingPostfix(Harmony h, ManualLogSource log, MethodInfo method, string postfixName)
	{
		if (method == null)
			return 0;
		try
		{
			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), postfixName));
			if (_loggedPatch < 12)
			{
				_loggedPatch++;
				log?.LogInfo("Homm3Import release battle UI: postfix registered on " + FormatMethod(method) + ".");
			}
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle UI: patch failed for " + FormatMethod(method) + ": " + ex.Message);
			return 0;
		}
	}

	private static bool LooksLikeTurnViewRefreshMethod(MethodInfo method)
	{
		var name = method?.Name ?? string.Empty;
		return string.Equals(name, "Show", StringComparison.Ordinal)
		       || string.Equals(name, "Init", StringComparison.Ordinal)
		       || name.StartsWith("bef", StringComparison.Ordinal)
		       || name.StartsWith("bdp", StringComparison.Ordinal);
	}

	private static int PatchPostfix(Harmony h, ManualLogSource log, Type type, string methodName, int parameterCount, string postfixName)
	{
		try
		{
			var method = FindMethodByNameAndArity(type, methodName, parameterCount);
			if (method == null)
			{
				log?.LogWarning("Homm3Import release battle UI: method not found: " + type?.FullName + "." + methodName + "/" + parameterCount + ".");
				return 0;
			}

			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), postfixName));
			if (_loggedPatch < 12)
			{
				_loggedPatch++;
				log?.LogInfo("Homm3Import release battle UI: postfix registered on " + FormatMethod(method) + ".");
			}
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle UI: patch failed for " + type?.FullName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchPostfixBySecondParameterType(
		Harmony h,
		ManualLogSource log,
		Type type,
		string[] names,
		Type secondParameterType,
		string postfixName,
		string label)
	{
		if (type == null || secondParameterType == null)
			return 0;
		var patched = 0;
		var seen = new HashSet<MethodInfo>();
		foreach (var method in FindMethodsBySecondParameterShape(type, names, secondParameterType))
		{
			if (!seen.Add(method))
				continue;
			try
			{
				h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ImportReleaseBattleUiHook), postfixName));
				patched++;
				if (_loggedPatch < 12)
				{
					_loggedPatch++;
					log?.LogInfo("Homm3Import release battle UI: " + label + " postfix registered on " + FormatMethod(method) + ".");
				}
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import release battle UI: " + label + " patch failed for " + FormatMethod(method) + ": " + ex.Message);
			}
		}
		if (patched == 0)
			log?.LogWarning("Homm3Import release battle UI: no " + label + " method found for expected second parameter " + secondParameterType.Name + ".");
		return patched;
	}

	private static List<MethodInfo> FindMethodsBySecondParameterShape(Type type, string[] names, Type secondParameterType)
	{
		var matches = new List<MethodInfo>();
		if (type == null || secondParameterType == null)
			return matches;
		var seen = new HashSet<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		MethodInfo[] declaredMethods;
		try { declaredMethods = type.GetMethods(flags); }
		catch { declaredMethods = Array.Empty<MethodInfo>(); }

		if (names != null)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				foreach (var method in declaredMethods)
				{
					if (!string.Equals(method.Name, name, StringComparison.Ordinal))
						continue;
					if (!MatchesSelectedHudSecondParameterShape(method, secondParameterType))
						continue;
					if (seen.Add(method))
						matches.Add(method);
				}
			}
		}

		if (matches.Count > 0)
			return matches;

		MethodInfo shapeMatch = null;
		foreach (var method in declaredMethods)
		{
			if (method.IsStatic)
				continue;
			if (!MatchesSelectedHudSecondParameterShape(method, secondParameterType))
				continue;
			shapeMatch ??= method;
			break;
		}

		if (shapeMatch != null)
			matches.Add(shapeMatch);

		return matches;
	}

	private static bool MatchesSelectedHudSecondParameterShape(MethodInfo method, Type secondParameterType)
	{
		if (method == null || secondParameterType == null)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != 2 || !ParameterTypesMatch(parameters[1].ParameterType, secondParameterType))
			return false;
		if (string.Equals(secondParameterType.Name, "BattleEventArgs", StringComparison.Ordinal))
		{
			var first = parameters[0].ParameterType;
			return first == typeof(object)
			       || string.Equals(first?.Name, "Object", StringComparison.Ordinal);
		}
		if (string.Equals(secondParameterType.Name, "Unit", StringComparison.Ordinal))
		{
			var first = parameters[0].ParameterType;
			return first == typeof(bool) || string.Equals(first?.Name, "Boolean", StringComparison.Ordinal);
		}
		return true;
	}

	private static bool ParameterTypesMatch(Type actual, Type expected)
	{
		if (actual == null || expected == null)
			return actual == expected;
		if (actual == expected)
			return true;
		return string.Equals(actual.FullName, expected.FullName, StringComparison.Ordinal)
		       || string.Equals(actual.Name, expected.Name, StringComparison.Ordinal);
	}

	private static MethodInfo FindMethodByNameAndArity(Type type, string methodName, int parameterCount)
	{
		if (type == null)
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
		{
			if (method.Name != methodName)
				continue;
			if (method.GetParameters().Length == parameterCount)
				return method;
		}
		return null;
	}

	private static void PostfixSelectedUnitHudBind(
		BhSelectedUnitHud __instance,
		[HarmonyArgument(1)] BattleEventArgs args,
		MethodBase __originalMethod)
	{
		try
		{
			_battleUiSeen = true;
			ApplySelectedHudPortrait(__instance, args?.target, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("selected HUD portrait failed: " + ex.Message);
		}
	}

	private static void PostfixSelectedUnitHudDirectBind(
		BhSelectedUnitHud __instance,
		[HarmonyArgument(1)] Unit unit,
		MethodBase __originalMethod)
	{
		try
		{
			_battleUiSeen = true;
			ApplySelectedHudPortrait(__instance, unit, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("selected HUD direct portrait failed: " + ex.Message);
		}
	}

	private static void PostfixSelectedUnitViewBind(
		BhSelectedUnitView __instance,
		[HarmonyArgument(0)] string sid,
		MethodBase __originalMethod)
	{
		try
		{
			ApplyUnitPortrait(ResolveSelectedUnitViewPic(__instance, "SelectedUnitView.Bind"), sid, __instance, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("selected unit view portrait failed: " + ex.Message);
		}
	}

	private static void PostfixTurnViewUpdate(
		BhTurnView __instance,
		[HarmonyArgument(0)] Unit unit,
		MethodBase __originalMethod)
	{
		try
		{
			ApplyTurnViewPortrait(__instance, unit, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("turn-order portrait failed: " + ex.Message);
		}
	}

	private static void PrefixTurnViewImageSetSprite(Image __instance, [HarmonyArgument(0)] ref Sprite value)
	{
		if (!__instance)
			return;
		try
		{
			ProbeBattleUiGraphicSetter("Image.sprite", __instance, value ? value.name : null);
			var view = TryGetOwningTurnView(__instance);
			if (view == null)
				return;
			if (!IsTurnViewPortraitImage(view, __instance))
				return;
			var sid = ResolveUnitPortraitSid(SafeExtractUnitSidFast(TryGetCachedTurnViewUnit(view)));
			if (string.IsNullOrWhiteSpace(sid))
				return;
			var sprite = TryResolveUnitPortraitSprite(sid);
			if (!sprite || value == sprite)
				return;
			value = sprite;
			if (IsVerboseBattleUiDiagnosticsEnabled() && _loggedTurnViewSpriteSetter < 16)
			{
				_loggedTurnViewSpriteSetter++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle UI: turn-view Image.sprite redirected sid='"
					+ sid
					+ "' image='"
					+ SafeImageName(__instance)
					+ "' view='"
					+ (view.name ?? "?")
					+ "' sprite='"
					+ (sprite.name ?? "?")
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			LogMiss("turn-view Image.sprite redirect failed: " + ex.Message);
		}
	}

	private static void PrefixBattleUiImageSetOverrideSprite(Image __instance, [HarmonyArgument(0)] ref Sprite value)
	{
		if (!__instance)
			return;
		try
		{
			ProbeBattleUiGraphicSetter("Image.overrideSprite", __instance, value ? value.name : null);
		}
		catch (Exception ex)
		{
			LogMiss("Image.overrideSprite probe failed: " + ex.Message);
		}
	}

	private static void PrefixBattleUiRawImageSetTexture(RawImage __instance, [HarmonyArgument(0)] ref Texture value)
	{
		if (!__instance)
			return;
		try
		{
			ProbeBattleUiGraphicSetter("RawImage.texture", __instance, value ? value.name : null);
		}
		catch (Exception ex)
		{
			LogMiss("RawImage.texture probe failed: " + ex.Message);
		}
	}

	private static void PostfixTurnViewPrivateRefresh(
		BhTurnView __instance,
		[HarmonyArgument(0)] Unit unit,
		MethodBase __originalMethod)
	{
		try
		{
			ApplyTurnViewPortrait(__instance, unit, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("turn-order portrait failed: " + ex.Message);
		}
	}

	private static void PostfixTurnViewCachedRefresh(BhTurnView __instance, MethodBase __originalMethod)
	{
		try
		{
			ApplyTurnViewPortrait(__instance, null, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("turn-order cached portrait failed: " + ex.Message);
		}
	}

	private static void PostfixTurnItemRefresh(object __instance, MethodBase __originalMethod)
	{
		try
		{
			ApplyTurnItemPortrait(__instance, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("turn-item portrait failed: " + ex.Message);
		}
	}

	private static void PostfixTurnViewPoolGet(BhTurnView __result, MethodBase __originalMethod)
	{
		try
		{
			ApplyTurnViewPortrait(__result, null, FormatMethod(__originalMethod) + ".pool");
		}
		catch (Exception ex)
		{
			LogMiss("turn-view pool portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleHeroBind(
		BhHeroView __instance,
		[HarmonyArgument(0)] Hero hero,
		MethodBase __originalMethod)
	{
		try
		{
			_battleUiSeen = true;
			ApplyBattleHeroPortrait(__instance, hero, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("battle hero portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleHeroSideBind(
		BhHeroView __instance,
		[HarmonyArgument(0)] object heroSide,
		MethodBase __originalMethod)
	{
		try
		{
			_battleUiSeen = true;
			ApplyBattleHeroPortrait(__instance, heroSide, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("battle hero side portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleHeroRefresh(BhHeroView __instance, MethodBase __originalMethod)
	{
		try
		{
			_battleUiSeen = true;
			ApplyBattleHeroPortrait(__instance, null, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("battle hero refresh portrait failed: " + ex.Message);
		}
	}

	private static void PostfixSimulatedBattleHeroesViewInit(Component __instance, TransferSide left, TransferSide right, MethodBase __originalMethod)
	{
		try
		{
			Homm3UiCardDiagnostics.Log(
				"autobattle-preview-unit-portraits",
				"autobattle-preview-bind",
				"source='" + FormatMethod(__originalMethod)
				+ "' leftUnits=" + CountTransferUnits(left)
				+ " rightUnits=" + CountTransferUnits(right)
				+ " leftSample='" + SampleTransferUnitSids(left)
				+ "' rightSample='" + SampleTransferUnitSids(right) + "'");
			ApplySimulatedBattlePreviewHeroPortraits(__instance, left, right, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("auto-battle hero preview portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleResultRefresh(Component __instance, MethodBase __originalMethod)
	{
		try
		{
			var source = FormatMethod(__originalMethod);
			LogBattleResultBinderHit(__instance, null, null, source + ".refresh");
			ApplyBattleResultUnitPortraitsFromLastSides(__instance, source + ".refresh");
			ApplyBattleResultHeroPortrait(__instance, source);
		}
		catch (Exception ex)
		{
			LogMiss("battle result hero portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleResultRefreshSimple(Component __instance)
	{
		try
		{
			LogBattleResultBinderHit(__instance, null, null, "BhSimulatedBattle.refresh");
			ApplyBattleResultUnitPortraitsFromLastSides(__instance, "BhSimulatedBattle.refresh");
			ApplyBattleResultHeroPortrait(__instance, "BhSimulatedBattle.refresh");
		}
		catch (Exception ex)
		{
			LogMiss("battle result hero portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleResultArmyBind(Component __instance, TransferSide a, TransferSide b, MethodBase __originalMethod)
	{
		try
		{
			var source = FormatMethod(__originalMethod);
			LogBattleResultBinderHit(__instance, a, b, source);
			RememberBattleResultSides(__instance, a, b);
			ApplyBattleResultUnitPortraits(__instance, a, b, source);
			ApplyBattleResultHeroPortrait(__instance, source);
		}
		catch (Exception ex)
		{
			LogMiss("battle result army bind portrait failed: " + ex.Message);
		}
	}

	private static void PostfixBattleResultHeroPortraitBind(Component __instance, object[] __args, MethodBase __originalMethod)
	{
		try
		{
			var iconKey = __args != null && __args.Length > 0 ? __args[0] as string : null;
			ApplyBattleResultHeroPortraitObject(__instance, iconKey, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			LogMiss("battle result direct hero portrait bind failed: " + ex.Message);
		}
	}

	private static void PostfixBattleResultHeroPortraitRefreshSimple(Component __instance)
	{
		try
		{
			ApplyBattleResultHeroPortraitObject(__instance, "BhHeroPortrait.refresh");
		}
		catch (Exception ex)
		{
			LogMiss("battle result direct hero portrait failed: " + ex.Message);
		}
	}

	private static void PrefixBattleQueueLayout(object[] __args, out QueueSidAliasState __state)
	{
		try
		{
			var queue = __args != null && __args.Length > 0 ? __args[0] : null;
			__state = BeginBattleQueueSidAliases(queue);
		}
		catch (Exception ex)
		{
			__state = null;
			LogMiss("queue layout SID alias failed: " + ex.Message);
		}
	}

	private static Exception FinalizerBattleQueueLayout(
		Exception __exception,
		object[] __args,
		QueueSidAliasState __state,
		MethodBase __originalMethod)
	{
		try
		{
			RestoreBattleQueueSidAliases(__state);
			if (__exception == null)
			{
				var queue = __args != null && __args.Length > 0 ? __args[0] : null;
				ApplyBattleQueuePortraits(queue, FormatMethod(__originalMethod) + ".queue");
			}
		}
		catch (Exception ex)
		{
			LogMiss("queue layout portrait failed: " + ex.Message);
		}
		return __exception;
	}

	private static void ApplyBattleQueuePortraits(object queue, string source)
	{
		if (queue == null)
			return;
		foreach (var item in EnumerateQueueItems(queue))
			ApplyTurnItemPortrait(item, source);
	}

	private static QueueSidAliasState BeginBattleQueueSidAliases(object queue)
	{
		if (queue == null)
			return null;
		var state = new QueueSidAliasState();
		foreach (var item in EnumerateQueueItems(queue))
			AliasTurnItemUnitForNativeQueue(item, state);
		if (state.StringAliases.Count <= 0)
			return state;
		if (_loggedQueueAlias < 8)
		{
			_loggedQueueAlias++;
			Plugin.LogSource?.LogInfo("Homm3Import release battle UI: queue layout temporarily aliased " + state.StringAliases.Count + " custom unit id field(s) for native layout.");
		}
		return state;
	}

	private static void AliasTurnItemUnitForNativeQueue(object item, QueueSidAliasState state)
	{
		if (item == null || state == null)
			return;
		var type = item.GetType();
		var unit = TryGetTurnItemUnit(item, type);
		if (unit == null)
			return;
		var sid = ExtractUnitSidFast(unit);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		if (!Homm3CustomFactionRegistry.TryGetDonorSid(sid, out var donorSid) || string.IsNullOrWhiteSpace(donorSid))
			return;
		AliasUnitConfigIdsForNativeQueue(unit, donorSid, state);
	}

	private static void AliasUnitConfigIdsForNativeQueue(Unit unit, string donorSid, QueueSidAliasState state)
	{
		if (unit == null || state == null || string.IsNullOrWhiteSpace(donorSid))
			return;
		var type = unit.GetType();
		TryAliasStringMember(unit, type, "sid", donorSid, state);
		TryAliasStringMember(unit, type, "<sid>k__BackingField", donorSid, state);
		TryAliasStringMember(unit, type, "configSid", donorSid, state);
		TryAliasStringMember(unit, type, "<configSid>k__BackingField", donorSid, state);
		foreach (var name in GameSymbols.BattleUi.UnitTransferFields)
		{
			var transfer = TryGetMemberValue(unit, type, name);
			TryAliasStringMember(transfer, null, "configSid", donorSid, state);
			TryAliasStringMember(transfer, null, "<configSid>k__BackingField", donorSid, state);
		}
		foreach (var name in GameSymbols.BattleUi.UnitConfigIdFields)
			TryAliasConfigIdForNativeQueue(TryGetMemberValue(unit, type, name), donorSid, state);
	}

	private static void TryAliasConfigIdForNativeQueue(object config, string donorSid, QueueSidAliasState state)
	{
		if (config == null || state == null || string.IsNullOrWhiteSpace(donorSid))
			return;
		TryAliasStringMember(config, null, "id", donorSid, state);
		TryAliasStringMember(config, null, "<id>k__BackingField", donorSid, state);
		TryAliasStringMember(config, null, "cnas", donorSid, state);
	}

	private static bool TryAliasStringMember(object owner, Type ownerType, string name, string value, QueueSidAliasState state)
	{
		if (owner == null || state == null || string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(value))
			return false;
		if (ownerType == null)
			ownerType = owner.GetType();
		var original = TryGetStringMember(owner, ownerType, name);
		if (string.IsNullOrWhiteSpace(original) || string.Equals(original, value, StringComparison.OrdinalIgnoreCase))
			return false;
		if (!TrySetMemberValue(owner, ownerType, name, value))
			return false;
		state.StringAliases.Add(new StringMemberAlias(owner, ownerType, name, original));
		return true;
	}

	private static void RestoreBattleQueueSidAliases(QueueSidAliasState state)
	{
		if (state?.StringAliases == null || state.StringAliases.Count <= 0)
			return;
		for (var i = state.StringAliases.Count - 1; i >= 0; i--)
		{
			var alias = state.StringAliases[i];
			if (alias?.Owner == null || string.IsNullOrWhiteSpace(alias.Name))
				continue;
			TrySetMemberValue(alias.Owner, alias.OwnerType ?? alias.Owner.GetType(), alias.Name, alias.OriginalValue);
		}
	}

	private sealed class QueueSidAliasState
	{
		internal readonly List<StringMemberAlias> StringAliases = new();
	}

	private sealed class StringMemberAlias
	{
		internal StringMemberAlias(object owner, Type ownerType, string name, string originalValue)
		{
			Owner = owner;
			OwnerType = ownerType;
			Name = name;
			OriginalValue = originalValue;
		}

		internal object Owner { get; }
		internal Type OwnerType { get; }
		internal string Name { get; }
		internal string OriginalValue { get; }
	}

	private static IEnumerable<object> EnumerateQueueItems(object queue)
	{
		if (queue == null)
			yield break;
		if (queue is Array array)
		{
			for (var i = 0; i < array.Length; i++)
			{
				var item = array.GetValue(i);
				if (item != null)
					yield return item;
			}
			yield break;
		}
		if (queue is System.Collections.IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}
		var type = queue.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Public | BindingFlags.Instance)
			?? type.GetProperty("Length", BindingFlags.Public | BindingFlags.Instance);
		var itemProperty = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance);
		var getItem = itemProperty != null ? null : type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance);
		if (countProperty == null || (itemProperty == null && getItem == null))
			yield break;
		int count;
		try { count = Convert.ToInt32(countProperty.GetValue(queue, null)); }
		catch { yield break; }
		for (var i = 0; i < count; i++)
		{
			object item = null;
			try
			{
				item = itemProperty != null
					? itemProperty.GetValue(queue, new object[] { i })
					: getItem.Invoke(queue, new object[] { i });
			}
			catch { }
			if (item != null)
				yield return item;
		}
	}

	private static object GetIndexedItem(object list, int index)
	{
		if (list == null || index < 0)
			return null;
		if (list is Array array)
			return index < array.Length ? array.GetValue(index) : null;
		var type = list.GetType();
		try
		{
			var itemProperty = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance);
			if (itemProperty != null)
				return itemProperty.GetValue(list, new object[] { index });
		}
		catch { }
		try
		{
			var getItem = type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance);
			if (getItem != null)
				return getItem.Invoke(list, new object[] { index });
		}
		catch { }
		return null;
	}

	private static void ApplyTurnItemPortrait(object item, string source)
	{
		if (item == null)
			return;
		var type = item.GetType();
		var unit = TryGetTurnItemUnit(item, type);
		if (unit == null)
			return;
		var sid = ExtractUnitSidFast(unit);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		var view = TryGetTurnItemView(item, type);
		if (view == null)
		{
			LogTurnItemMiss(source, sid, item);
			return;
		}
		ApplyTurnViewPortrait(view, unit, source + ".turn-item");
	}

	private static void ApplySelectedHudPortrait(BhSelectedUnitHud hud, Unit unit, string source)
	{
		if (hud == null || unit == null)
			return;
		ProbeBattleUiRoot(hud, source + ".root-probe");

		var sid = ExtractUnitSidFast(unit);
		if (ApplyUnitPortrait(ResolveSelectedUnitViewPic(hud.unitView, source), sid, hud, source + ".unitView"))
			return;

		var sprite = TryResolveUnitPortraitSprite(sid);
		if (!sprite)
		{
			ClearComponentPortraitOverrides(hud);
			return;
		}

		var replaced = 0;
		var images = hud.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (!LooksLikeSelectedUnitPortraitImage(image))
				continue;
			if (ApplySprite(image, sprite))
				replaced++;
		}

		if (replaced > 0)
			LogUnitPortrait(source + ".scan", sid, sprite, replaced);
	}

	private static void ApplyTurnViewPortrait(BhTurnView view, Unit unit, string source)
	{
		if (view == null)
			return;

		var sid = SafeExtractUnitSidFast(unit)
		          ?? SafeExtractUnitSidFast(TryGetCachedTurnViewUnit(view));
		sid = ResolveUnitPortraitSid(sid);
		if (string.IsNullOrWhiteSpace(sid))
		{
			ClearTurnViewPortraitOverrides(view);
			LogTurnViewMiss(source, "sid", view, unit, null, 0);
			return;
		}
		var sprite = TryResolveUnitPortraitSprite(sid);
		if (!sprite)
		{
			ClearTurnViewPortraitOverrides(view);
			LogTurnViewMiss(source, "sprite", view, unit, sid, 0);
			return;
		}

		var replaced = 0;
		if (ApplySprite(view.unitPic, sprite))
			replaced++;

		var temp = view.tempPic;
		if (temp)
		{
			var images = temp.GetComponentsInChildren<Image>(true);
			for (var i = 0; i < images.Length; i++)
			{
				var image = images[i];
				if (!image || image == view.unitPic)
					continue;
				if (ApplySprite(image, sprite))
					replaced++;
			}
		}

		if (replaced > 0)
			LogUnitPortrait(source, sid, sprite, replaced);
		else
			LogTurnViewMiss(source, "image", view, unit, sid, CountTurnViewImages(view));
	}

	private static BhTurnView TryGetOwningTurnView(Image image)
	{
		if (!image)
			return null;
		try
		{
			return image.GetComponentInParent<BhTurnView>(true);
		}
		catch
		{
			try
			{
				return image.GetComponentInParent<BhTurnView>();
			}
			catch
			{
				return null;
			}
		}
	}

	private static bool IsTurnViewPortraitImage(BhTurnView view, Image image)
	{
		if (view == null || !image)
			return false;
		try
		{
			if (image == view.unitPic)
				return true;
		}
		catch { }
		try
		{
			var temp = view.tempPic;
			if (temp && image.transform && image.transform.IsChildOf(temp.transform))
				return true;
		}
		catch { }
		return false;
	}

	private static void ProbeBattleUiGraphicSetter(string kind, Graphic graphic, string nextName)
	{
		if (!_diagnosticsEnabled || !_battleUiSeen || _loggedTimelineSetterProbe >= 120 || !graphic)
			return;
		_loggedTimelineSetterProbe++;
		try
		{
			var image = graphic as Image;
			var view = TryGetOwningTurnView(image);
			var rect = graphic.rectTransform;
			var size = rect ? rect.rect.size : Vector2.zero;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI probe: graphic setter#"
				+ _loggedTimelineSetterProbe
				+ " kind='"
				+ (kind ?? "?")
				+ " name='"
				+ (graphic.name ?? "?")
				+ "' current='"
				+ CurrentGraphicAssetName(graphic)
				+ "' next='"
				+ (nextName ?? "")
				+ "' override='"
				+ (image && image.overrideSprite ? image.overrideSprite.name : "")
				+ "' enabled="
				+ graphic.enabled
				+ " active="
				+ (graphic.gameObject && graphic.gameObject.activeInHierarchy)
				+ " size=("
				+ size.x.ToString("0.0")
				+ ","
				+ size.y.ToString("0.0")
				+ ") ownerTurnView='"
				+ (view ? view.name : "")
				+ "' cachedSid='"
				+ (SafeExtractUnitSidFast(TryGetCachedTurnViewUnit(view)) ?? "")
				+ "' components='"
				+ ComponentList(graphic.gameObject)
				+ "' path='"
				+ HierarchyPath(graphic.transform, 10)
				+ "'.");
		}
		catch (Exception ex)
		{
			LogMiss("timeline setter probe failed: " + ex.Message);
		}
	}

	private static string CurrentGraphicAssetName(Graphic graphic)
	{
		if (!graphic)
			return string.Empty;
		try
		{
			if (graphic is Image image)
				return image.sprite ? image.sprite.name : string.Empty;
			if (graphic is RawImage raw)
				return raw.texture ? raw.texture.name : string.Empty;
		}
		catch { }
		return string.Empty;
	}

	private static void ProbeBattleUiRoot(Component anchor, string source)
	{
		if (!IsVerboseBattleUiDiagnosticsEnabled() || !anchor || _loggedBattleRootProbe >= 120)
			return;
		try
		{
			var root = FindBattleUiProbeRoot(anchor);
			if (!root)
				root = anchor.transform;
			var images = root.GetComponentsInChildren<Image>(true);
			var raws = root.GetComponentsInChildren<RawImage>(true);
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI probe: root source='"
				+ (source ?? "?")
				+ "' anchor='"
				+ (anchor.name ?? "?")
				+ "' anchorType='"
				+ (anchor.GetType().FullName ?? "?")
				+ "' root='"
				+ HierarchyPath(root, 10)
				+ "' images="
				+ images.Length
				+ " rawImages="
				+ raws.Length
				+ ".");
			ProbeBattleUiScene(source);
			LogBattleUiImages(images);
			LogBattleUiRawImages(raws);
		}
		catch (Exception ex)
		{
			LogMiss("battle UI root probe failed: " + ex.Message);
		}
	}

	private static bool IsVerboseBattleUiDiagnosticsEnabled()
	{
		return _diagnosticsEnabled && Homm3DiagnosticFlags.IsEnabled(UiIconDiagnosticFlagName);
	}

	private static void ProbeBattleUiScene(string source)
	{
		if (_loggedBattleSceneProbe >= 2)
			return;
		_loggedBattleSceneProbe++;
		try
		{
			var roots = CollectActiveSceneRoots();
			var canvases = Resources.FindObjectsOfTypeAll<Canvas>();
			var turnViews = Resources.FindObjectsOfTypeAll<BhTurnView>();
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI scene probe: source='"
				+ (source ?? "?")
				+ "' scenes="
				+ SceneManager.sceneCount
				+ " roots="
				+ roots.Count
				+ " canvases="
				+ (canvases?.Length ?? 0)
				+ " turnViews="
				+ (turnViews?.Length ?? 0)
				+ ".");
			LogSceneTurnViews(turnViews);
			LogSceneCanvases(canvases);
			LogSceneTimelineImages(canvases);
		}
		catch (Exception ex)
		{
			LogMiss("battle UI scene probe failed: " + ex.Message);
		}
	}

	private static List<GameObject> CollectActiveSceneRoots()
	{
		var roots = new List<GameObject>();
		try
		{
			for (var i = 0; i < SceneManager.sceneCount; i++)
			{
				var scene = SceneManager.GetSceneAt(i);
				if (!scene.IsValid() || !scene.isLoaded)
					continue;
				var sceneRoots = scene.GetRootGameObjects();
				if (sceneRoots == null)
					continue;
				for (var j = 0; j < sceneRoots.Length; j++)
				{
					var root = sceneRoots[j];
					if (root)
						roots.Add(root);
				}
			}
		}
		catch { }
		return roots;
	}

	private static void LogSceneTurnViews(BhTurnView[] turnViews)
	{
		if (turnViews == null)
			return;
		var skipped = 0;
		var failed = 0;
		for (var i = 0; i < turnViews.Length && _loggedBattleSceneProbeItem < 80; i++)
		{
			try
			{
				var view = turnViews[i];
				if (view == null)
				{
					skipped++;
					continue;
				}
				var go = view.gameObject;
				var transform = view.transform;
				if (!go || !transform)
				{
					skipped++;
					if (skipped <= 4)
					{
						_loggedBattleSceneProbeItem++;
						Plugin.LogSource?.LogInfo(
							"Homm3Import release battle UI scene probe: turnView skipped#"
							+ _loggedBattleSceneProbeItem
							+ " index="
							+ i
							+ " reason='missing gameObject/transform'.");
					}
					continue;
				}
				_loggedBattleSceneProbeItem++;
				var cachedUnit = TryGetCachedTurnViewUnit(view);
				var sid = SafeExtractUnitSidFast(cachedUnit);
				var unitPic = TryGetMemberValue(view, view.GetType(), "unitPic") as Image;
				var tempPic = TryGetMemberValue(view, view.GetType(), "tempPic") as Image;
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle UI scene probe: turnView#"
					+ _loggedBattleSceneProbeItem
					+ " index="
					+ i
					+ " name='"
					+ (view.name ?? "?")
					+ "' active="
					+ go.activeInHierarchy
					+ " cachedSid='"
					+ (sid ?? "")
					+ "' images="
					+ CountTurnViewImages(view)
					+ " unitPic='"
					+ DescribeImage(unitPic)
					+ "' tempPic='"
					+ DescribeImage(tempPic)
					+ "' components='"
					+ ComponentList(go)
					+ "' path='"
					+ HierarchyPath(transform, 12)
					+ "'.");
				ApplyTurnViewPortrait(view, null, "scene-probe.turnView");
			}
			catch (Exception ex)
			{
				failed++;
				if (failed <= 4 && _loggedBattleSceneProbeItem < 80)
				{
					_loggedBattleSceneProbeItem++;
					Plugin.LogSource?.LogWarning(
						"Homm3Import release battle UI scene probe: turnView failed#"
						+ _loggedBattleSceneProbeItem
						+ " index="
						+ i
						+ " error='"
						+ ex.GetType().Name
						+ ": "
						+ ex.Message
						+ "'.");
				}
			}
		}
		if ((skipped > 0 || failed > 0) && _loggedBattleSceneProbeItem < 80)
		{
			_loggedBattleSceneProbeItem++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI scene probe: turnView summary skipped="
				+ skipped
				+ " failed="
				+ failed
				+ ".");
		}
	}

	private static void LogSceneCanvases(Canvas[] canvases)
	{
		if (canvases == null)
			return;
		for (var i = 0; i < canvases.Length && _loggedBattleSceneProbeItem < 110; i++)
		{
			var canvas = canvases[i];
			if (!canvas || !canvas.gameObject)
				continue;
			var path = HierarchyPath(canvas.transform, 10);
			var text = ((canvas.name ?? "") + " " + path).ToLowerInvariant();
			var images = 0;
			var turnViews = 0;
			try { images = canvas.GetComponentsInChildren<Image>(true)?.Length ?? 0; } catch { }
			try { turnViews = canvas.GetComponentsInChildren<BhTurnView>(true)?.Length ?? 0; } catch { }
			if (turnViews <= 0
			    && text.IndexOf("battle", StringComparison.Ordinal) < 0
			    && text.IndexOf("combat", StringComparison.Ordinal) < 0
			    && text.IndexOf("queue", StringComparison.Ordinal) < 0
			    && text.IndexOf("turn", StringComparison.Ordinal) < 0
			    && text.IndexOf("timeline", StringComparison.Ordinal) < 0)
				continue;
			_loggedBattleSceneProbeItem++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI scene probe: canvas#"
				+ _loggedBattleSceneProbeItem
				+ " name='"
				+ (canvas.name ?? "?")
				+ "' active="
				+ canvas.gameObject.activeInHierarchy
				+ " images="
				+ images
				+ " turnViews="
				+ turnViews
				+ " components='"
				+ ComponentList(canvas.gameObject)
				+ "' path='"
				+ path
				+ "'.");
		}
	}

	private static void LogSceneTimelineImages(Canvas[] canvases)
	{
		if (canvases == null)
			return;
		for (var i = 0; i < canvases.Length && _loggedBattleSceneProbeItem < 160; i++)
		{
			var canvas = canvases[i];
			if (!canvas || !canvas.gameObject)
				continue;
			Image[] images = null;
			try { images = canvas.GetComponentsInChildren<Image>(true); } catch { }
			if (images == null)
				continue;
			for (var j = 0; j < images.Length && _loggedBattleSceneProbeItem < 160; j++)
			{
				var image = images[j];
				if (!ShouldLogSceneTimelineImage(image))
					continue;
				_loggedBattleSceneProbeItem++;
				var view = TryGetOwningTurnView(image);
				var rect = image.rectTransform;
				var size = rect ? rect.rect.size : Vector2.zero;
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle UI scene probe: timeline image#"
					+ _loggedBattleSceneProbeItem
					+ " name='"
					+ (image.name ?? "?")
					+ "' sprite='"
					+ (image.sprite ? image.sprite.name : "")
					+ "' override='"
					+ (image.overrideSprite ? image.overrideSprite.name : "")
					+ "' active="
					+ (image.gameObject && image.gameObject.activeInHierarchy)
					+ " size=("
					+ size.x.ToString("0.0")
					+ ","
					+ size.y.ToString("0.0")
					+ ") ownerTurnView='"
					+ (view ? view.name : "")
					+ "' cachedSid='"
					+ (SafeExtractUnitSidFast(TryGetCachedTurnViewUnit(view)) ?? "")
					+ "' components='"
					+ ComponentList(image.gameObject)
					+ "' path='"
					+ HierarchyPath(image.transform, 12)
					+ "'.");
			}
		}
	}

	private static bool ShouldLogSceneTimelineImage(Image image)
	{
		if (!image || !image.gameObject)
			return false;
		var path = HierarchyPath(image.transform, 12);
		var sprite = image.sprite ? image.sprite.name : string.Empty;
		var ov = image.overrideSprite ? image.overrideSprite.name : string.Empty;
		var text = ((image.name ?? "") + " " + sprite + " " + ov + " " + path).ToLowerInvariant();
		return TryGetOwningTurnView(image) != null
		       || text.IndexOf("turn", StringComparison.Ordinal) >= 0
		       || text.IndexOf("queue", StringComparison.Ordinal) >= 0
		       || text.IndexOf("timeline", StringComparison.Ordinal) >= 0
		       || text.IndexOf("initiative", StringComparison.Ordinal) >= 0
		       || text.IndexOf("round", StringComparison.Ordinal) >= 0
		       || LooksLikePlaceholder(sprite)
		       || LooksLikePlaceholder(ov);
	}

	private static string DescribeImage(Image image)
	{
		if (!image)
			return "";
		try
		{
			return (image.name ?? "?")
			       + "|sprite="
			       + (image.sprite ? image.sprite.name : "")
			       + "|override="
			       + (image.overrideSprite ? image.overrideSprite.name : "")
			       + "|active="
			       + (image.gameObject && image.gameObject.activeInHierarchy)
			       + "|path="
			       + HierarchyPath(image.transform, 8);
		}
		catch
		{
			return image.name ?? "?";
		}
	}

	private static Transform FindBattleUiProbeRoot(Component anchor)
	{
		if (!anchor || !anchor.transform)
			return null;
		var current = anchor.transform;
		var best = current;
		for (var depth = 0; current && depth < 12; depth++, current = current.parent)
		{
			try
			{
				var images = current.GetComponentsInChildren<Image>(true);
				if (images.Length >= 12 && images.Length <= 400)
					best = current;
				if (Contains(current.name, "battle") || Contains(current.name, "combat") || Contains(current.name, "hud"))
					best = current;
				if (images.Length > 400)
					break;
			}
			catch { }
		}
		return best;
	}

	private static void LogBattleUiImages(Image[] images)
	{
		if (images == null)
			return;
		for (var i = 0; i < images.Length && _loggedBattleRootProbe < 120; i++)
		{
			var image = images[i];
			if (!ShouldLogBattleUiGraphic(image))
				continue;
			_loggedBattleRootProbe++;
			var view = TryGetOwningTurnView(image);
			var rect = image.rectTransform;
			var size = rect ? rect.rect.size : Vector2.zero;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI probe: root image#"
				+ _loggedBattleRootProbe
				+ " name='"
				+ (image.name ?? "?")
				+ "' sprite='"
				+ (image.sprite ? image.sprite.name : "")
				+ "' override='"
				+ (image.overrideSprite ? image.overrideSprite.name : "")
				+ "' active="
				+ (image.gameObject && image.gameObject.activeInHierarchy)
				+ " size=("
				+ size.x.ToString("0.0")
				+ ","
				+ size.y.ToString("0.0")
				+ ") ownerTurnView='"
				+ (view ? view.name : "")
				+ "' components='"
				+ ComponentList(image.gameObject)
				+ "' path='"
				+ HierarchyPath(image.transform, 10)
				+ "'.");
		}
	}

	private static void LogBattleUiRawImages(RawImage[] raws)
	{
		if (raws == null)
			return;
		for (var i = 0; i < raws.Length && _loggedBattleRootProbe < 120; i++)
		{
			var raw = raws[i];
			if (!ShouldLogBattleUiGraphic(raw))
				continue;
			_loggedBattleRootProbe++;
			var rect = raw.rectTransform;
			var size = rect ? rect.rect.size : Vector2.zero;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle UI probe: root raw#"
				+ _loggedBattleRootProbe
				+ " name='"
				+ (raw.name ?? "?")
				+ "' texture='"
				+ (raw.texture ? raw.texture.name : "")
				+ "' active="
				+ (raw.gameObject && raw.gameObject.activeInHierarchy)
				+ " size=("
				+ size.x.ToString("0.0")
				+ ","
				+ size.y.ToString("0.0")
				+ ") components='"
				+ ComponentList(raw.gameObject)
				+ "' path='"
				+ HierarchyPath(raw.transform, 10)
				+ "'.");
		}
	}

	private static bool ShouldLogBattleUiGraphic(Graphic graphic)
	{
		if (!graphic || !graphic.gameObject)
			return false;
		var name = graphic.name ?? string.Empty;
		var asset = CurrentGraphicAssetName(graphic);
		var path = HierarchyPath(graphic.transform, 8);
		var text = (name + " " + asset + " " + path).ToLowerInvariant();
		return text.IndexOf("turn", StringComparison.Ordinal) >= 0
			|| text.IndexOf("queue", StringComparison.Ordinal) >= 0
			|| text.IndexOf("timeline", StringComparison.Ordinal) >= 0
			|| text.IndexOf("round", StringComparison.Ordinal) >= 0
			|| text.IndexOf("unit", StringComparison.Ordinal) >= 0
			|| text.IndexOf("pic", StringComparison.Ordinal) >= 0
			|| text.IndexOf("portrait", StringComparison.Ordinal) >= 0
			|| text.IndexOf("icon", StringComparison.Ordinal) >= 0
			|| LooksLikePlaceholder(asset);
	}

	private static string ComponentList(GameObject obj)
	{
		if (!obj)
			return string.Empty;
		try
		{
			var components = obj.GetComponents<Component>();
			var parts = new List<string>();
			for (var i = 0; i < components.Length && i < 8; i++)
			{
				var component = components[i];
				if (!component)
					continue;
				parts.Add(component.GetType().FullName ?? component.GetType().Name);
			}
			return string.Join(",", parts);
		}
		catch
		{
			return string.Empty;
		}
	}

	private static string HierarchyPath(Transform transform, int maxDepth)
	{
		if (!transform)
			return string.Empty;
		var names = new List<string>();
		var current = transform;
		for (var depth = 0; current && depth < maxDepth; depth++, current = current.parent)
			names.Add(current.name ?? "?");
		names.Reverse();
		return string.Join("/", names);
	}

	private static Unit TryGetCachedTurnViewUnit(BhTurnView view)
	{
		if (view == null)
			return null;
		try
		{
			return DeobfInteropCompat.TryReadNativeObjectMember<Unit>(view, GameSymbols.BattleUi.TurnViewUnitFields)
			       ?? TryGetFirstMemberValue(view, view.GetType(), GameSymbols.BattleUi.TurnViewUnitFields) as Unit;
		}
		catch
		{
			return null;
		}
	}

	private static Unit TryGetTurnItemUnit(object item, Type type)
	{
		foreach (var name in GameSymbols.BattleUi.TurnItemUnitFields)
		{
			var native = DeobfInteropCompat.TryReadNativeObjectMember<Unit>(item, name);
			if (native != null)
				return native;
			if (TryGetMemberValue(item, type, name) is Unit unit)
				return unit;
		}
		return null;
	}

	private static BhTurnView TryGetTurnItemView(object item, Type type)
	{
		foreach (var name in GameSymbols.BattleUi.TurnItemViewFields)
		{
			if (TryGetMemberValue(item, type, name) is BhTurnView view)
				return view;
		}
		return null;
	}

	// Audit B5: BhSelectedUnitView.pic is renamed on live Golden Era (field_Private_Image_0), so the
	// direct getter threw MissingMethodException. Read it through GameSymbols.LiveRenamedMembers.
	private static bool _loggedSelectedUnitViewPicUnresolved;

	private static Image ResolveSelectedUnitViewPic(BhSelectedUnitView view, string source)
	{
		if (view == null)
			return null;
		var pic = DeobfInteropCompat.GetImageMember(view, GameSymbols.LiveRenamedMembers.SelectedUnitViewPic);
		if (pic == null && !_loggedSelectedUnitViewPicUnresolved)
		{
			_loggedSelectedUnitViewPicUnresolved = true;
			Plugin.LogSource?.LogWarning("Homm3Import release battle UI: selected unit view portrait Image unresolved (" + string.Join("/", GameSymbols.LiveRenamedMembers.SelectedUnitViewPic) + ") at " + source + "; custom portrait not applied.");
		}
		return pic;
	}

	private static bool ApplyUnitPortrait(Image image, string rawSid, Component owner, string source)
	{
		var sid = ResolveUnitPortraitSid(rawSid);
		if (!image || string.IsNullOrWhiteSpace(sid))
		{
			ClearStrongholdPortraitOverride(image);
			return false;
		}

		var sprite = TryResolveUnitPortraitSprite(sid);
		if (!sprite)
		{
			ClearStrongholdPortraitOverride(image);
			return false;
		}

		if (!ApplySprite(image, sprite))
			return false;
		LogUnitPortrait(source, sid, sprite, 1);
		return true;
	}

	private static int CountTurnViewImages(BhTurnView view)
	{
		if (view == null)
			return 0;
		var count = 0;
		try
		{
			if (view.unitPic)
				count++;
		}
		catch { }
		try
		{
			var temp = view.tempPic;
			if (temp)
				count += temp.GetComponentsInChildren<Image>(true).Length;
		}
		catch { }
		return count;
	}

	private static void LogTurnViewMiss(string source, string reason, BhTurnView view, Unit argUnit, string sid, int imageCount)
	{
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		if (_loggedTurnViewMiss >= 24)
			return;
		_loggedTurnViewMiss++;
		string cachedSid = null;
		try
		{
			cachedSid = SafeExtractUnitSidFast(TryGetCachedTurnViewUnit(view));
		}
		catch { }
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: turn-order portrait miss reason='"
			+ (reason ?? "?")
			+ "' source="
			+ (source ?? "?")
			+ " argSid='"
			+ (SafeExtractUnitSidFast(argUnit) ?? "")
			+ "' cachedSid='"
			+ (cachedSid ?? "")
			+ "' resolvedSid='"
			+ (sid ?? "")
			+ "' unitPic="
			+ SafeImageName(view?.unitPic)
			+ " tempPicImages="
			+ imageCount
			+ ".");
	}

	private static void LogTurnItemMiss(string source, string sid, object item)
	{
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		if (_loggedTurnItemMiss >= 12)
			return;
		_loggedTurnItemMiss++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: turn-item portrait deferred source="
			+ (source ?? "?")
			+ " type='"
			+ (item?.GetType().FullName ?? "?")
			+ "' sid='"
			+ (sid ?? "")
			+ "' reason='view not created'.");
	}

	private static Sprite TryResolveUnitPortraitSprite(string sid)
	{
		sid = ResolveUnitPortraitSid(sid);
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		return Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out var sprite) && sprite ? sprite : null;
	}

	private static string SafeExtractUnitSidFast(Unit unit)
	{
		try
		{
			return ExtractUnitSidFast(unit);
		}
		catch
		{
			return null;
		}
	}

	private static string ExtractUnitSidFast(Unit unit)
	{
		if (unit == null)
			return null;
		var type = unit.GetType();
		foreach (var value in EnumerateUnitSidHints(unit, type))
		{
			if (IsCustomUnitSid(value))
				return value.Trim();
		}
		return null;
	}

	private static MethodInfo FindQueueLayoutMethod(Type type)
	{
		if (type == null)
			return null;

		MethodInfo shapeMatch = null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		if (GameSymbols.BattleUi.QueueLayout.NameHints != null)
		{
			for (var i = 0; i < GameSymbols.BattleUi.QueueLayout.NameHints.Length; i++)
			{
				var name = GameSymbols.BattleUi.QueueLayout.NameHints[i];
				foreach (var method in type.GetMethods(flags))
				{
					if (method == null || method.Name != name || method.ReturnType != typeof(void))
						continue;
					var ps = method.GetParameters();
					if (ps.Length == 1 && IsTurnItemListType(ps[0].ParameterType))
						return method;
				}
			}
		}

		foreach (var method in type.GetMethods(flags))
		{
			if (method == null || method.ReturnType != typeof(void))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 1 && IsTurnItemListType(ps[0].ParameterType))
				shapeMatch ??= method;
		}

		return shapeMatch;
	}

	private static bool IsTurnItemListType(Type type)
	{
		if (type == null)
			return false;
		Type itemType = null;
		try
		{
			var args = type.IsGenericType ? type.GetGenericArguments() : Type.EmptyTypes;
			if (args != null && args.Length == 1)
				itemType = args[0];
		}
		catch { }
		if (itemType == null)
			return false;
		if (LooksLikeKnownTurnItemType(itemType))
			return true;
		foreach (var name in GameSymbols.BattleUi.TurnItemTypeNames)
		{
			if (string.Equals(itemType.Name, name, StringComparison.Ordinal)
			    || string.Equals(itemType.FullName, name, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static MethodInfo FindFirstMethodByNames(Type type, int parameterCount, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var method = FindMethodByNameAndArity(type, names[i], parameterCount);
			if (method != null)
				return method;
		}
		return null;
	}

	private static IEnumerable<string> EnumerateUnitSidHints(Unit unit, Type type)
	{
		yield return TryGetStringMember(unit, type, "sid");
		yield return TryGetStringMember(unit, type, "configSid");
		foreach (var name in GameSymbols.BattleUi.UnitTransferFields)
		{
			var transfer = TryGetMemberValue(unit, type, name)
			               ?? DeobfInteropCompat.TryReadNativeObjectMember<TransferUnit>(unit, name);
			if (Homm3CoveCannonVisuals.TryResolveRememberedUnitSid(transfer, out var cannonSid))
				yield return cannonSid;
			yield return TryGetStringMember(transfer, null, "configSid");
		}
		foreach (var name in GameSymbols.BattleUi.UnitConfigIdFields)
			yield return TryGetStringMember(TryGetMemberValue(unit, type, name), null, "id");
	}

	private static string ResolveUnitPortraitSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var key = sid.Trim();
		return IsCustomUnitSid(key) ? key : null;
	}

	private static bool IsCustomUnitSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid) && Homm3CustomFactionRegistry.IsCustomUnitSid(sid.Trim());
	}

	private static bool LooksLikeSelectedUnitPortraitImage(Image image)
	{
		if (!image || !image.gameObject)
			return false;
		var name = image.name ?? string.Empty;
		var parent = image.transform?.parent ? image.transform.parent.name : string.Empty;
		var spriteName = image.sprite ? image.sprite.name : string.Empty;
		return Contains(name, "pic")
			|| Contains(name, "portrait")
			|| Contains(name, "unit")
			|| Contains(parent, "portrait")
			|| Contains(parent, "selected")
			|| Contains(spriteName, "hydra")
			|| LooksLikePlaceholder(spriteName);
	}

	private static bool LooksLikeBattleResultHeroImage(Image image)
	{
		if (!image || !image.gameObject)
			return false;
		var name = image.name ?? string.Empty;
		var parent = image.transform?.parent ? image.transform.parent.name : string.Empty;
		var spriteName = image.sprite ? image.sprite.name : string.Empty;
		return Contains(name, "hero")
		       || Contains(name, "portrait")
		       || Contains(name, "face")
		       || Contains(parent, "hero")
		       || Contains(parent, "portrait")
		       || Contains(spriteName, "necrom")
		       || Contains(spriteName, "necro")
		       || LooksLikePlaceholder(spriteName);
	}

	private static void ApplyBattleHeroPortrait(BhHeroView view, object hero, string source)
	{
		if (view == null)
			return;
		ProbeBattleUiRoot(view, source + ".root-probe");
		var iconKey = ResolveStrongholdHeroIconKey(hero) ?? ResolveStrongholdHeroIconKey(view);
		var viewId = view.GetInstanceID();
		// Never fall back to the global last-drawn hero key: in multi-hero games that is often a teammate.
		if (string.IsNullOrWhiteSpace(iconKey))
		{
			// A bind to a non-custom hero clears the view's key so a pooled view can't keep a stale face.
			if (hero != null)
			{
				BattleHeroIconKeyByView.Remove(viewId);
				return;
			}
			BattleHeroIconKeyByView.TryGetValue(viewId, out iconKey);
		}
		if (string.IsNullOrWhiteSpace(iconKey))
			return;
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
			return;
		BattleHeroIconKeyByView[viewId] = iconKey;
		if (!ApplySprite(view.heroFace, sprite))
			return;
		_lastBattleHeroIconKey = iconKey;
		LogHeroPortrait(source, iconKey, sprite);
	}

	private static void ApplyBattleResultHeroPortrait(Component root, string source)
	{
		if (!root)
			return;
		ApplyBattleResultUnitPortraits(root, source);
		var iconKey = ResolveStrongholdHeroIconKey(root) ?? _lastBattleHeroIconKey;
		if (string.IsNullOrWhiteSpace(iconKey))
		{
			LogBattleResultHeroDiagnostics(root, source, "no-icon-key", null, 0);
			return;
		}
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
		{
			LogBattleResultHeroDiagnostics(root, source, "no-sprite", iconKey, 0);
			return;
		}

		var replaced = 0;
		var type = root.GetType();
		replaced += ApplyBattleResultHeroPortraitObject(TryGetMemberValue(root, type, "portraitLeft"), sprite);
		replaced += ApplyBattleResultHeroPortraitObject(TryGetMemberValue(root, type, "portraitRight"), sprite);
		LogBattleResultHeroDiagnostics(root, source, replaced > 0 ? "applied" : "no-target-image", iconKey, replaced);
		if (replaced <= 0 || _loggedBattleResultHeroPortrait >= 12)
			return;
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		_loggedBattleResultHeroPortrait++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: battle result hero portrait replaced count="
			+ replaced
			+ " iconKey='"
			+ iconKey
			+ "' sprite='"
			+ sprite.name
			+ "' via "
			+ source
			+ ".");
	}

	private static void LogBattleResultHeroDiagnostics(Component root, string source, string reason, string iconKey, int replaced)
	{
		if (_loggedBattleResultHeroDiag >= 80)
			return;
		_loggedBattleResultHeroDiag++;
		if (!root)
			return;
		var type = root.GetType();
		Homm3UiCardDiagnostics.Log(
			"battle-results-hero-portraits",
			"battle-result-hero-resolution",
			"reason='" + (reason ?? "?")
			+ "' source='" + (source ?? "?")
			+ "' iconKey='" + (iconKey ?? "?")
			+ "' lastIcon='" + (_lastBattleHeroIconKey ?? "?")
			+ "' replaced=" + replaced
			+ " root='" + FormatComponent(root)
			+ "' portraitLeft=" + DescribePortraitObject(TryGetMemberValue(root, type, "portraitLeft"))
			+ " portraitRight=" + DescribePortraitObject(TryGetMemberValue(root, type, "portraitRight")),
			limit: 100);
		if (string.Equals(reason, "applied", StringComparison.Ordinal))
		{
			LogBattleHeroImageTree(TryGetMemberValue(root, type, "portraitLeft"), "battle-result-left", source);
			LogBattleHeroImageTree(TryGetMemberValue(root, type, "portraitRight"), "battle-result-right", source);
		}
	}

	private static string DescribePortraitObject(object value)
	{
		if (value == null)
			return "(null)";
		if (value is Image image)
			return DescribeBattleResultImage(image);
		if (value is Component component)
		{
			var imageField = TryGetMemberValue(value, value.GetType(), "icon") as Image;
			return FormatComponent(component) + " icon=" + DescribeBattleResultImage(imageField);
		}
		return value.GetType().FullName ?? value.GetType().Name;
	}

	private static void ApplyBattleResultUnitPortraits(Component root, string source)
	{
		if (!root)
			return;
		var type = root.GetType();
		var replaced = 0;
		var armyFields = GameSymbols.ReleaseTownUi.SimulatedBattleArmyListFields;
		for (var i = 0; i < armyFields.Length; i++)
			replaced += ApplyBattleResultUnitPortraitList(TryGetMemberValue(root, type, armyFields[i]));
		LogBattleResultUnitPortraits(replaced, source);
	}

	private static void ApplyBattleResultUnitPortraits(Component root, TransferSide left, TransferSide right, string source)
	{
		if (!root)
			return;
		var type = root.GetType();
		var replaced = 0;
		var armyFields = GameSymbols.ReleaseTownUi.SimulatedBattleArmyListFields;
		replaced += ApplyBattleResultUnitPortraitList(TryGetMemberValue(root, type, armyFields[0]), left);
		replaced += ApplyBattleResultUnitPortraitList(TryGetMemberValue(root, type, armyFields[1]), right);
		LogBattleResultUnitPortraits(replaced, source);
	}

	private static void ApplyBattleResultUnitPortraits(Component root, string[] leftUnitSids, string[] rightUnitSids, string source)
	{
		if (!root)
			return;
		var type = root.GetType();
		var replaced = 0;
		var armyFields = GameSymbols.ReleaseTownUi.SimulatedBattleArmyListFields;
		replaced += ApplyBattleResultUnitPortraitList(TryGetMemberValue(root, type, armyFields[0]), leftUnitSids);
		replaced += ApplyBattleResultUnitPortraitList(TryGetMemberValue(root, type, armyFields[1]), rightUnitSids);
		LogBattleResultUnitPortraits(replaced, source);
	}

	private static void ApplyBattleResultUnitPortraitsFromLastSides(Component root, string source)
	{
		if (!root)
			return;
		if (LastBattleResultSidesByRoot.TryGetValue(root.GetInstanceID(), out var sides)
		    && (sides.LeftUnitSids.Length > 0 || sides.RightUnitSids.Length > 0))
		{
			ApplyBattleResultUnitPortraits(root, sides.LeftUnitSids, sides.RightUnitSids, source + ".transfer-side-cache");
			return;
		}
		ApplyBattleResultUnitPortraits(root, source + ".remembered");
	}

	private static void RememberBattleResultSides(Component root, TransferSide left, TransferSide right)
	{
		if (!root)
			return;
		LastBattleResultSidesByRoot[root.GetInstanceID()] = new SimulatedBattleSides(
			SnapshotTransferUnitSids(left),
			SnapshotTransferUnitSids(right));
	}

	private static void LogBattleResultUnitPortraits(int replaced, string source)
	{
		Homm3UiCardDiagnostics.Log(
			"battle-results-unit-portraits",
			"battle-result-unit-portrait-summary",
			"source='" + (source ?? "?") + "' replaced=" + replaced);
		if (replaced <= 0 || _loggedBattleResultUnitPortrait >= 12)
			return;
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		_loggedBattleResultUnitPortrait++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: battle result unit portraits reapplied count="
			+ replaced
			+ " via "
			+ source
			+ ".");
	}

	private static int ApplyBattleResultUnitPortraitList(object list)
	{
		if (list == null)
			return 0;
		var replaced = 0;
		foreach (var item in EnumerateQueueItems(list))
		{
			if (Homm3ImportTooltipPortraitHook.TryApplyRememberedPortrait(item, "battle-result-remembered"))
				replaced++;
		}
		return replaced;
	}

	private static int ApplyBattleResultUnitPortraitList(object list, TransferSide side)
	{
		if (list == null || side == null)
			return ApplyBattleResultUnitPortraitList(list);
		return ApplyBattleResultUnitPortraitList(list, SnapshotTransferUnitSids(side));
	}

	private static int ApplyBattleResultUnitPortraitList(object list, string[] unitSids)
	{
		if (list == null || unitSids == null || unitSids.Length == 0)
			return ApplyBattleResultUnitPortraitList(list);
		var replaced = 0;
		var index = 0;
		foreach (var item in EnumerateQueueItems(list))
		{
			var sid = index < unitSids.Length ? unitSids[index] : null;
			if (!string.IsNullOrWhiteSpace(sid)
			    ? Homm3ImportTooltipPortraitHook.TryApplyPortraitForSid(item, sid, "battle-result-transfer-side")
			      || Homm3ImportTooltipPortraitHook.TryApplyRememberedPortrait(item, "battle-result-remembered")
			    : Homm3ImportTooltipPortraitHook.TryApplyRememberedPortrait(item, "battle-result-remembered"))
				replaced++;
			index++;
		}
		return replaced;
	}

	private static string[] SnapshotTransferUnitSids(TransferSide side)
	{
		if (side == null)
			return Array.Empty<string>();
		var units = TryGetFirstMemberValue(side, side.GetType(), GameSymbols.ReleaseTownUi.TransferSideUnitsFields);
		if (units == null)
			return Array.Empty<string>();
		var sids = new List<string>();
		foreach (var unit in EnumerateQueueItems(units))
			sids.Add(ExtractTransferUnitSid(unit));
		return sids.ToArray();
	}

	private static string ExtractTransferUnitSid(object unit)
	{
		if (unit == null)
			return null;
		var type = unit.GetType();
		var sid = TryGetFirstStringMember(unit, type, GameSymbols.ReleaseTownUi.TransferUnitConfigSidFields)
		          ?? TryGetStringMember(TryGetMemberValue(unit, type, "cnux"), null, "id");
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static int CountTransferUnits(TransferSide side)
	{
		if (side == null)
			return 0;
		var units = TryGetFirstMemberValue(side, side.GetType(), GameSymbols.ReleaseTownUi.TransferSideUnitsFields);
		return GetCollectionCount(units);
	}

	private static void LogBattleResultBinderHit(Component root, TransferSide left, TransferSide right, string source)
	{
		try
		{
			Homm3UiCardDiagnostics.Log(
				"battle-results-unit-portraits",
				"battle-result-binder-hit",
				"source='" + (source ?? "?")
				+ "' root='" + FormatComponent(root)
				+ "' leftUnits=" + CountTransferUnits(left)
				+ " rightUnits=" + CountTransferUnits(right)
				+ " leftSample='" + SampleTransferUnitSids(left)
				+ "' rightSample='" + SampleTransferUnitSids(right)
				+ "' armyLeft=" + CountMemberList(root, "armyLeft")
				+ " armyRight=" + CountMemberList(root, "armyRight"),
				limit: 80);
		}
		catch (Exception ex)
		{
			Homm3UiCardDiagnostics.Log(
				"battle-results-unit-portraits",
				"battle-result-binder-hit-failed",
				"source='" + (source ?? "?") + "' error='" + ex.GetType().Name + ": " + ex.Message + "'",
				limit: 20);
		}
	}

	private static string SampleTransferUnitSids(TransferSide side)
	{
		if (side == null)
			return "";
		var units = TryGetFirstMemberValue(side, side.GetType(), GameSymbols.ReleaseTownUi.TransferSideUnitsFields);
		if (units == null)
			return "";
		var result = "";
		var index = 0;
		foreach (var unit in EnumerateQueueItems(units))
		{
			if (index >= 5)
				break;
			if (index > 0)
				result += ",";
			result += ExtractTransferUnitSid(unit) ?? "?";
			index++;
		}
		return result;
	}

	private static int CountMemberList(Component root, string memberName)
	{
		if (!root)
			return 0;
		return GetCollectionCount(TryGetMemberValue(root, root.GetType(), memberName));
	}

	private static string FormatComponent(Component component)
	{
		if (!component)
			return "(null)";
		return (component.name ?? "?") + "/" + (component.GetType().FullName ?? component.GetType().Name);
	}

	private static string DescribeBattleResultImage(Image image)
	{
		if (!image)
			return "(null)";
		var rect = image.rectTransform;
		var size = rect ? rect.rect.size : Vector2.zero;
		return "'" + GetTransformPath(image.transform, null)
			+ "' sprite='" + (image.sprite ? image.sprite.name : "(null)")
			+ "' override='" + (image.overrideSprite ? image.overrideSprite.name : "(null)")
			+ "' active=" + (image.gameObject && image.gameObject.activeInHierarchy)
			+ " enabled=" + image.enabled
			+ " size=" + size.x.ToString("0.##") + "x" + size.y.ToString("0.##");
	}

	private static string GetTransformPath(Transform transform, Transform stopAt)
	{
		if (!transform)
			return "(null)";
		var parts = new List<string>();
		var current = transform;
		while (current && current != stopAt && parts.Count < 16)
		{
			parts.Add(current.name ?? "?");
			current = current.parent;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static int GetCollectionCount(object collection)
	{
		if (collection == null)
			return 0;
		try
		{
			var count = collection.GetType().GetProperty("Count", BindingFlags.Public | BindingFlags.Instance);
			if (count != null)
				return Convert.ToInt32(count.GetValue(collection, null));
		}
		catch { }
		return 0;
	}

	private static void ApplyBattleResultHeroPortraitObject(Component portrait, string source)
	{
		if (!portrait)
			return;
		var iconKey = _lastBattleHeroIconKey;
		ApplyBattleResultHeroPortraitObject(portrait, iconKey, source);
	}

	private static void ApplyBattleResultHeroPortraitObject(Component portrait, string iconKey, string source)
	{
		if (!portrait)
			return;
		if (string.IsNullOrWhiteSpace(iconKey))
			return;
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
			return;
		_lastBattleHeroIconKey = iconKey;
		var replaced = ApplyBattleResultHeroPortraitObject((object)portrait, sprite);
		if (replaced <= 0)
		{
			if (IsVerboseBattleUiDiagnosticsEnabled() && _loggedBattleResultHeroPortraitMiss < 8)
			{
				_loggedBattleResultHeroPortraitMiss++;
				Plugin.LogSource?.LogInfo("Homm3Import release battle UI: battle result direct hero portrait miss component='" + (portrait.name ?? "?") + "' type='" + portrait.GetType().FullName + "'.");
			}
			return;
		}
		if (_loggedBattleResultHeroPortrait >= 12)
			return;
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		_loggedBattleResultHeroPortrait++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: battle result direct hero portrait replaced count="
			+ replaced
			+ " iconKey='"
			+ iconKey
			+ "' sprite='"
			+ sprite.name
			+ "' via "
			+ source
			+ ".");
	}

	private static int ApplyBattleResultHeroPortraitObject(object portrait, Sprite sprite)
	{
		if (portrait == null || !sprite)
			return 0;
		var type = portrait.GetType();
		var replaced = 0;
		if (string.Equals(type.FullName, "Hex.Session.Hud.BhHeroPortrait", StringComparison.Ordinal)
		    || string.Equals(type.Name, "BhHeroPortrait", StringComparison.Ordinal))
		{
			if (TryGetMemberValue(portrait, type, "icon") is not Image heroIcon || !ApplySprite(heroIcon, sprite))
				return 0;
			HideBattleResultHeroPlaceholderOverlays(portrait, type, heroIcon, "BhHeroPortrait");
			return 1;
		}
		if (portrait is Component component)
		{
			var directImage = component as Image;
			if (directImage && LooksLikeBattleResultHeroImage(directImage) && ApplySprite(directImage, sprite))
			{
				HideSiblingHeroPlaceholderOverlays(directImage, "battle-result-direct-image");
				replaced++;
			}
			var scopedImages = component.GetComponentsInChildren<Image>(true);
			for (var i = 0; i < scopedImages.Length; i++)
			{
				var image = scopedImages[i];
				if (!LooksLikeBattleResultHeroImage(image))
					continue;
				if (ApplySprite(image, sprite))
				{
					HideSiblingHeroPlaceholderOverlays(image, "battle-result-scoped-image");
					replaced++;
				}
			}
		}
		if (TryGetMemberValue(portrait, type, "icon") is Image icon && ApplySprite(icon, sprite))
		{
			HideSiblingHeroPlaceholderOverlays(icon, "battle-result-icon-field");
			replaced++;
		}
		return replaced;
	}

	private static void ApplySimulatedBattlePreviewHeroPortraits(Component view, TransferSide left, TransferSide right, string source)
	{
		if (!view)
			return;
		var type = view.GetType();
		var replaced = 0;
		var leftImage = TryGetMemberValue(view, type, "heroLeft") as Image;
		var rightImage = TryGetMemberValue(view, type, "heroRight") as Image;
		replaced += ApplySideHeroPreviewImage(leftImage, left, source + ".left");
		replaced += ApplySideHeroPreviewImage(rightImage, right, source + ".right");
		LogAutoBattleHeroPreviewDiagnostics(view, leftImage, left, rightImage, right, source, replaced);
		if (replaced > 0 && IsVerboseBattleUiDiagnosticsEnabled() && _loggedHeroPortrait < 12)
		{
			_loggedHeroPortrait++;
			Plugin.LogSource?.LogInfo("Homm3Import release battle UI: auto-battle hero preview replaced count=" + replaced + " via " + source + ".");
		}
	}

	private static int ApplySideHeroPreviewImage(Image image, TransferSide side, string source)
	{
		if (!image || side == null)
			return 0;
		var iconKey = ResolveStrongholdHeroIconKey(side.logicHero)
		              ?? ResolveStrongholdHeroIconKey(side.hero)
		              ?? ResolveStrongholdHeroIconKey(side);
		if (string.IsNullOrWhiteSpace(iconKey))
			return 0;
		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(iconKey, out var sprite) || !sprite)
			return 0;
		if (!ApplySprite(image, sprite))
			return 0;
		HideSiblingHeroPlaceholderOverlays(image, source);
		_lastBattleHeroIconKey = iconKey;
		LogHeroPortrait(source, iconKey, sprite);
		return 1;
	}

	private static int HideBattleResultHeroPlaceholderOverlays(object portrait, Type type, Image portraitImage, string source)
	{
		if (portrait == null || type == null || !portraitImage)
			return 0;
		var hidden = 0;
		var lossPanel = TryGetMemberValue(portrait, type, "panelLossHero") as Image;
		var deathSprite = TryGetMemberValue(portrait, type, "deathHero") as Sprite;
		var escapeSprite = TryGetMemberValue(portrait, type, "escapeHero") as Sprite;
		if (ShouldHideLossPanelOverlay(lossPanel, portraitImage, deathSprite, escapeSprite))
			hidden += DisableHeroPlaceholderOverlay(lossPanel, source + ".panelLossHero");
		hidden += HideSiblingHeroPlaceholderOverlays(portraitImage, source);
		return hidden;
	}

	private static bool ShouldHideLossPanelOverlay(Image overlay, Image portraitImage, Sprite deathSprite, Sprite escapeSprite)
	{
		if (!overlay || overlay == portraitImage)
			return false;
		var activeSprite = overlay.overrideSprite ? overlay.overrideSprite : overlay.sprite;
		if (activeSprite && (activeSprite == deathSprite || activeSprite == escapeSprite))
			return false;
		return overlay.enabled;
	}

	private static int HideSiblingHeroPlaceholderOverlays(Image portraitImage, string source)
	{
		if (!portraitImage || !portraitImage.transform)
			return 0;
		var root = portraitImage.transform.parent;
		if (!root)
			return 0;
		var hidden = 0;
		try
		{
			var images = root.GetComponentsInChildren<Image>(true);
			for (var i = 0; i < images.Length; i++)
			{
				var image = images[i];
				if (ShouldHideHeroPlaceholderOverlay(image, portraitImage))
					hidden += DisableHeroPlaceholderOverlay(image, source + ".sibling-placeholder");
			}
		}
		catch { }
		return hidden;
	}

	private static bool ShouldHideHeroPlaceholderOverlay(Image overlay, Image portraitImage)
	{
		if (!overlay || overlay == portraitImage || !overlay.enabled)
			return false;
		var spriteName = overlay.overrideSprite ? overlay.overrideSprite.name : overlay.sprite ? overlay.sprite.name : "";
		var name = overlay.name ?? "";
		var path = GetTransformPath(overlay.transform, portraitImage ? portraitImage.transform.parent : null);
		if (Contains(name, "frame") || Contains(name, "border") || Contains(name, "mask") || Contains(name, "background") || Contains(name, "backplate"))
			return false;
		return LooksLikeNamedPlaceholder(name)
		       || LooksLikeNamedPlaceholder(spriteName)
		       || LooksLikeNamedPlaceholder(path);
	}

	private static bool LooksLikeNamedPlaceholder(string value)
	{
		return Contains(value, "random")
		       || Contains(value, "placeholder")
		       || Contains(value, "plug")
		       || Contains(value, "default")
		       || Contains(value, "missing")
		       || Contains(value, "unknown")
		       || Contains(value, "orange")
		       || Contains(value, "wip");
	}

	private static int DisableHeroPlaceholderOverlay(Image overlay, string source)
	{
		if (!overlay || !overlay.enabled)
			return 0;
		overlay.enabled = false;
		if (_loggedBattleHeroOverlayHidden < 40)
		{
			_loggedBattleHeroOverlayHidden++;
			Homm3UiCardDiagnostics.Log(
				"battle-hero-placeholder-overlays",
				"placeholder-overlay-hidden",
				"source='" + (source ?? "?")
				+ "' image=" + DescribeBattleResultImage(overlay),
				limit: 80);
		}
		return 1;
	}

	private static void LogAutoBattleHeroPreviewDiagnostics(Component view, Image leftImage, TransferSide left, Image rightImage, TransferSide right, string source, int replaced)
	{
		if (_loggedBattleResultHeroDiag >= 80)
			return;
		_loggedBattleResultHeroDiag++;
		Homm3UiCardDiagnostics.Log(
			"autobattle-preview-hero-portraits",
			"autobattle-hero-preview-resolution",
			"source='" + (source ?? "?")
			+ "' replaced=" + replaced
			+ " view='" + FormatComponent(view)
			+ "' leftIcon='" + (ResolveStrongholdHeroIconKey(left?.logicHero) ?? ResolveStrongholdHeroIconKey(left?.hero) ?? ResolveStrongholdHeroIconKey(left) ?? "?")
			+ "' rightIcon='" + (ResolveStrongholdHeroIconKey(right?.logicHero) ?? ResolveStrongholdHeroIconKey(right?.hero) ?? ResolveStrongholdHeroIconKey(right) ?? "?")
			+ "' leftImage=" + DescribeBattleResultImage(leftImage)
			+ " rightImage=" + DescribeBattleResultImage(rightImage),
			limit: 100);
		if (replaced > 0)
		{
			LogBattleHeroImageTree(leftImage, "autobattle-preview-left", source);
			LogBattleHeroImageTree(rightImage, "autobattle-preview-right", source);
		}
	}

	private static void LogBattleHeroImageTree(object owner, string label, string source)
	{
		if (_loggedBattleHeroImageTree >= 40)
			return;
		var tree = DescribeBattleHeroImageTree(owner);
		if (string.IsNullOrWhiteSpace(tree))
			return;
		_loggedBattleHeroImageTree++;
		Homm3UiCardDiagnostics.Log(
			"battle-hero-image-tree",
			"hero-image-tree",
			"source='" + (source ?? "?")
			+ "' label='" + (label ?? "?")
			+ "' "
			+ tree,
			limit: 60);
	}

	private static string DescribeBattleHeroImageTree(object owner)
	{
		if (owner == null)
			return "owner=(null)";
		if (owner is Image image)
			return "ownerImage=" + DescribeBattleResultImage(image)
			       + " parentImages=[" + DescribeImageSet(image.transform ? image.transform.parent : null, 16) + "]"
			       + " grandParentImages=[" + DescribeImageSet(image.transform && image.transform.parent ? image.transform.parent.parent : null, 20) + "]";
		if (owner is Component component)
			return "owner='" + FormatComponent(component)
			       + "' memberImages=[" + DescribeImageSet(component.transform, 24) + "]"
			       + " parentImages=[" + DescribeImageSet(component.transform ? component.transform.parent : null, 24) + "]";
		return "ownerType='" + (owner.GetType().FullName ?? owner.GetType().Name) + "'";
	}

	private static string DescribeImageSet(Transform root, int limit)
	{
		if (!root)
			return "(null)";
		try
		{
			var images = root.GetComponentsInChildren<Image>(true);
			var parts = new List<string>();
			for (var i = 0; i < images.Length && parts.Count < limit; i++)
			{
				var image = images[i];
				if (!image)
					continue;
				parts.Add(DescribeImageForTree(image, root));
			}
			if (images.Length > limit)
				parts.Add("...+" + (images.Length - limit));
			return string.Join(" | ", parts);
		}
		catch (Exception ex)
		{
			return "error=" + ex.GetType().Name + ":" + ex.Message;
		}
	}

	private static string DescribeImageForTree(Image image, Transform root)
	{
		if (!image)
			return "(null)";
		var rect = image.rectTransform;
		var size = rect ? rect.rect.size : Vector2.zero;
		var spriteName = image.sprite ? image.sprite.name : "(null)";
		var overrideName = image.overrideSprite ? image.overrideSprite.name : "(null)";
		var relativePath = GetTransformPath(image.transform, root);
		return "{path='" + relativePath
		       + "' name='" + (image.name ?? "?")
		       + "' sprite='" + spriteName
		       + "' override='" + overrideName
		       + "' activeSelf=" + (image.gameObject && image.gameObject.activeSelf)
		       + " active=" + (image.gameObject && image.gameObject.activeInHierarchy)
		       + " enabled=" + image.enabled
		       + " raycast=" + image.raycastTarget
		       + " sibling=" + (image.transform ? image.transform.GetSiblingIndex() : -1)
		       + " size=" + size.x.ToString("0.##") + "x" + size.y.ToString("0.##")
		       + " alpha=" + image.color.a.ToString("0.###")
		       + " hasMask=" + (image.GetComponent<Mask>() != null)
		       + " hasRectMask=" + (image.GetComponent<RectMask2D>() != null)
		       + " placeholder=" + (LooksLikeNamedPlaceholder(image.name ?? "") || LooksLikeNamedPlaceholder(spriteName) || LooksLikeNamedPlaceholder(overrideName))
		       + "}";
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
		var key = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
		if (!seen.Add(key))
			return null;

		var t = obj.GetType();
		foreach (var name in new[] { "icon", "configSid", "configId", "sid", "id", "heroSid", "cmyj" })
		{
			var direct = TryGetStringMember(obj, t, name);
			if (IsStrongholdHeroIconKey(direct))
				return direct.Trim();
		}

		foreach (var name in GameSymbols.BattleUi.HeroNestedFields)
		{
			var nested = TryGetMemberValue(obj, t, name);
			var nestedKey = ResolveStrongholdHeroIconKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		foreach (var name in new[] { "bdxl", "eif", "get_cbye", "cnuz", "get_chyt", "xlt", "get_cbyf", "get_chpd", "get_cnva", "get_cmyj", "ivd", "ipk", "get_cmeo", "get_bqax", "get_ciaj", "get_cnxy", "get_heroConfig" })
		{
			var nested = TryInvokeNoArg(obj, t, name);
			var nestedKey = ResolveStrongholdHeroIconKey(nested, seen, depth + 1);
			if (nestedKey != null)
				return nestedKey;
		}

		return null;
	}

	private static bool IsStrongholdHeroIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(key.Trim(), out _);
	}

	private static string TryGetStringMember(object obj, Type type, string name)
	{
		if (obj != null && type == null)
			type = obj.GetType();
		return TryGetMemberValue(obj, type, name) as string
		       ?? DeobfInteropCompat.TryReadNativeStringMember(obj, name);
	}

	private static string TryGetFirstStringMember(object obj, Type type, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetStringMember(obj, type, names[i]);
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	private static object TryGetMemberValue(object obj, Type type, string name)
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
			catch { }
			try
			{
				var prop = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (prop != null && prop.CanRead)
					return prop.GetValue(obj);
			}
			catch { }
		}
		return null;
	}

	private static object TryGetFirstMemberValue(object obj, Type type, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetMemberValue(obj, type, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static bool TrySetMemberValue(object obj, Type type, string name, object value)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return false;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var field = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (field != null)
				{
					field.SetValue(obj, value);
					return true;
				}
			}
			catch { }
			try
			{
				var prop = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
				if (prop != null && prop.CanWrite)
				{
					prop.SetValue(obj, value);
					return true;
				}
			}
			catch { }
		}
		return false;
	}

	private static object TryInvokeNoArg(object obj, Type type, string name)
	{
		if (obj == null || type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			try
			{
				var method = current.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
				if (method != null)
					return method.Invoke(obj, null);
			}
			catch { }
		}
		return null;
	}

	private static bool ApplySprite(Image image, Sprite sprite)
	{
		if (!image || !sprite)
			return false;
		image.sprite = sprite;
		image.overrideSprite = null;
		image.color = Color.white;
		image.enabled = true;
		image.preserveAspect = true;
		return true;
	}

	private static void ClearTurnViewPortraitOverrides(BhTurnView view)
	{
		if (view == null)
			return;
		ClearStrongholdPortraitOverride(view.unitPic);
		var temp = view.tempPic;
		if (!temp)
			return;
		try
		{
			var images = temp.GetComponentsInChildren<Image>(true);
			for (var i = 0; i < images.Length; i++)
				ClearStrongholdPortraitOverride(images[i]);
		}
		catch { }
	}

	private static void ClearComponentPortraitOverrides(Component root)
	{
		if (!root)
			return;
		try
		{
			var images = root.GetComponentsInChildren<Image>(true);
			for (var i = 0; i < images.Length; i++)
				ClearStrongholdPortraitOverride(images[i]);
		}
		catch { }
	}

	private static void ClearStrongholdPortraitOverride(Image image)
	{
		if (!image || !image.overrideSprite)
			return;
		if (IsHomm3PortraitSprite(image.overrideSprite))
			image.overrideSprite = null;
	}

	private static bool IsHomm3PortraitSprite(Sprite sprite)
	{
		var name = sprite ? sprite.name : null;
		return !string.IsNullOrWhiteSpace(name)
		       && (name.StartsWith("homm3_static_portrait_", StringComparison.Ordinal)
		           || name.StartsWith("homm3_preview_", StringComparison.Ordinal)
		           || name.StartsWith("vanilla_dungeon_preview_", StringComparison.Ordinal));
	}

	private static bool Contains(string value, string needle)
	{
		return !string.IsNullOrWhiteSpace(value)
			&& value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool LooksLikePlaceholder(string spriteName)
	{
		return string.IsNullOrWhiteSpace(spriteName)
			|| Contains(spriteName, "placeholder")
			|| Contains(spriteName, "plug")
			|| Contains(spriteName, "default")
			|| Contains(spriteName, "missing")
			|| Contains(spriteName, "unknown")
			|| Contains(spriteName, "wip");
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

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string SafeImageName(Image image)
	{
		if (!image)
			return "(null)";
		var spriteName = image.sprite ? image.sprite.name : "(null sprite)";
		return "'" + (image.name ?? "?") + "' sprite='" + spriteName + "'";
	}

	private static void LogUnitPortrait(string source, string sid, Sprite sprite, int replaced)
	{
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		if (_loggedUnitPortrait >= 40)
			return;
		_loggedUnitPortrait++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: unit portrait replaced count=" + replaced
			+ " sid='" + (sid ?? "?") + "' sprite='" + (sprite ? sprite.name : "?") + "' via " + source + ".");
	}

	private static void LogHeroPortrait(string source, string iconKey, Sprite sprite)
	{
		if (!IsVerboseBattleUiDiagnosticsEnabled())
			return;
		if (_loggedHeroPortrait >= 12)
			return;
		_loggedHeroPortrait++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle UI: hero portrait replaced iconKey='" + (iconKey ?? "?")
			+ "' sprite='" + (sprite ? sprite.name : "?") + "' via " + source + ".");
	}

	private static void LogMiss(string reason)
	{
		if (_loggedMiss >= 12)
			return;
		_loggedMiss++;
		Plugin.LogSource?.LogDebug("Homm3Import release battle UI: " + reason);
	}

	private readonly struct SimulatedBattleSides
	{
		internal SimulatedBattleSides(string[] leftUnitSids, string[] rightUnitSids)
		{
			LeftUnitSids = leftUnitSids ?? Array.Empty<string>();
			RightUnitSids = rightUnitSids ?? Array.Empty<string>();
		}

		internal string[] LeftUnitSids { get; }
		internal string[] RightUnitSids { get; }
	}
}
