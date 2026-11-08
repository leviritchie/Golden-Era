using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.GameHub.UICommon;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Narrow diagnostics for the released Custom Game picker. This intentionally avoids
/// compile-time references to release-only obfuscated members so playtest builds still compile.
/// Enable with <c>releaseCustomGameUiProbes=true</c> in the mod config.
/// </summary>
internal static class ReleaseCustomGameUiProbe
{
	private const float QuickPlayFactionTileLabelFontScale = 3f;
	private const float QuickPlayFactionGridCenterXRatio = -0.12f;
	private const float QuickPlayFactionVerticalSpacingScale = 0.92f;

	private static bool _patched;
	private static ManualLogSource _log;
	private static int _pickInitLogged;
	private static int _stateLogged;
	private static int _clickLogged;
	private static int _heroGridLogged;
	private static int _heroButtonLogged;
	private static int _summaryLogged;
	private static int _lobbyLogged;
	private static int _strongholdHeroIconLogged;
	private static int _pickUnitPortraitLogged;
	private static int _pickSkillIconLogged;
	private static int _quickPlayFactionTextLogged;
	private static int _quickPlayFactionLayoutLogged;
	private static int _quickPlayFactionActiveLayoutLogged;
	private static int _quickPlayFactionBackgroundLogged;
	private static int _quickPlayFactionDetailsLayoutLogged;
	private static int _quickPlayFactionNativeListLogged;
	private static int _quickPlayHeroTextLogged;
	private static readonly Dictionary<int, Vector2> _quickPlayFactionDetailsOriginalPositions = new();
	private static readonly HashSet<string> _loggedFactionInjected = new(StringComparer.OrdinalIgnoreCase);
	private static bool _translateDungeonSelectionToStronghold;
	private static readonly HashSet<string> _stateSignatures = new(StringComparer.Ordinal);

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		_log = log;
		var patched = 0;
		patched += PatchByName(h, log, "Hex.Pick.BhPickGameView", "Init", 0, postfixName: nameof(PostfixPickInit));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhPickGameView", new[] { "luv", "luk", "lqd" }, 2, prefixName: nameof(PrefixPickStateChange));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhPickGameView", new[] { "luo", "lup", "lue", "lpx" }, 1, prefixName: nameof(PrefixFactionClick));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhPickGameView", new[] { "luq", "lur", "luf", "lpy" }, 2, prefixName: nameof(PrefixHeroClick));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhPickGameView", new[] { "lur", "luq", "lug", "lpz" }, 2, prefixName: nameof(PrefixHeroHover));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhPickGameView", new[] { "lvc", "lur", "lqk" }, 5, prefixName: nameof(PrefixHeroGrid));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhPickGameView", new[] { "lvi", "lux", "lqq" }, 6, prefixName: nameof(PrefixSummaryTransition));
		patched += PatchByAnyName(h, log, "Hex.BhHeroSelectButton", GameSymbols.CustomGame.HeroSelectButtonBind.NameHints, 3, prefixName: nameof(PrefixHeroSelectButtonSetup));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhSummaryCard", new[] { "lwh", "lvw", "lro" }, 2, prefixName: nameof(PrefixSummarySetup));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhSummaryCard", new[] { "lwi", "lvx", "lrp" }, 2, prefixName: nameof(PrefixSummarySpinner));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhSummaryCard", new[] { "lwl", "lwa", "lrs" }, 1, prefixName: nameof(PrefixSummaryHeroConfigInternal));
		patched += PatchSummaryCardHeroBinds(h, log);
		patched += PatchPickSkillView(h, log);
		patched += PatchPickUnitSlot(h, log);
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "Open", 1, prefixName: nameof(PrefixLobbyPopupOpen));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qwn", 0, postfixName: nameof(PostfixLobbyFractionList));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qvm", 0, postfixName: nameof(PostfixLobbyFractionList));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qwo", 4, prefixName: nameof(PrefixLobbyFractionCurrent));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qvn", 4, prefixName: nameof(PrefixLobbyFractionCurrent));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qwp", 1, prefixName: nameof(PrefixLobbyFractionSelected));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qvo", 1, prefixName: nameof(PrefixLobbyFractionSelected));
		patched += PatchLobbyFractionElement(h, log, prefixName: nameof(PrefixLobbyFractionElement), postfixName: nameof(PostfixLobbyFractionElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhFraction", "OnBtn", 1, prefixName: nameof(PrefixLobbyElementClick));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScHeroSelect", "Open", 1, prefixName: nameof(PrefixLobbyPopupOpen));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScHeroSelect", "qwv", 3, prefixName: nameof(PrefixLobbyHeroCurrent));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScHeroSelect", "qvs", 3, prefixName: nameof(PrefixLobbyHeroCurrent));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScHeroSelect", "qww", 1, prefixName: nameof(PrefixLobbyHeroSelected));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScHeroSelect", "qvt", 1, prefixName: nameof(PrefixLobbyHeroSelected));
		patched += PatchLobbyHeroElement(h, log, prefixName: nameof(PrefixLobbyHeroElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhHero", "OnBtn", 1, prefixName: nameof(PrefixLobbyElementClick));

		_patched = true;
		log?.LogInfo("ReleaseCustomGameUiProbe: " + patched + " Custom Game UI probe patch(es) registered.");
	}

	internal static void TryRegisterStrongholdGameHubIntegration(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		_log = log;
		_translateDungeonSelectionToStronghold = false;
		var patched = 0;
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qwn", 0, postfixName: nameof(PostfixLobbyFractionList));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qvl", 0, postfixName: nameof(PostfixLobbyFractionList));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qwo", 4, prefixName: nameof(PrefixStrongholdFractionElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.ScFractionSelect", "qvm", 4, prefixName: nameof(PrefixStrongholdFractionElement));
		patched += PatchLobbyFractionElement(h, log, prefixName: nameof(PrefixStrongholdFractionElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhFraction", "OnBtn", 1, prefixName: nameof(PrefixStrongholdFractionButtonClick), postfixName: nameof(PostfixStrongholdFractionButtonClick));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhFraction", "qoc", 0, prefixName: nameof(PrefixStrongholdFractionButtonClick), postfixName: nameof(PostfixStrongholdFractionButtonClick));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhFraction", "qnf", 0, prefixName: nameof(PrefixStrongholdFractionButtonClick), postfixName: nameof(PostfixStrongholdFractionButtonClick));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhFractionAdditionalInfo", "Show", 1, postfixName: nameof(PostfixStrongholdFractionAdditionalInfo));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhFractionAdditionalInfo", "Init", 1, postfixName: nameof(PostfixStrongholdFractionAdditionalInfo));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhLobbyPopupFractionElement", "Init", 4, postfixName: nameof(PostfixStrongholdLobbyPopupFractionElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhLobbyPopupFractionElement", "OnPointerEnter", 1, postfixName: nameof(PostfixStrongholdLobbyPopupFractionElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhLobbyPopupFractionElement", "qpt", 1, postfixName: nameof(PostfixStrongholdLobbyPopupFractionElement));
		patched += PatchByName(h, log, "Hex.GameHub.Lobby.UI.BhLobbyPopupFractionElement", "qow", 1, postfixName: nameof(PostfixStrongholdLobbyPopupFractionElement));
		foreach (var methodName in GameSymbols.CustomGame.FactionDetailsBind.NameHints)
			patched += PatchByName(h, log, "Hex.BhFactionDetails", methodName, 1, postfixName: nameof(PostfixStrongholdPickFactionDetails));
		patched += PatchByName(h, log, "Hex.BhFactionDetails", GameSymbols.CustomGame.FactionDetailsRefresh.NameHints[0], 0, postfixName: nameof(PostfixStrongholdPickFactionDetailsRefresh));
		for (var i = 1; i < GameSymbols.CustomGame.FactionDetailsRefresh.NameHints.Length; i++)
			patched += PatchByName(h, log, "Hex.BhFactionDetails", GameSymbols.CustomGame.FactionDetailsRefresh.NameHints[i], 3, postfixName: nameof(PostfixStrongholdPickFactionDetailsRefresh), logMissing: i == GameSymbols.CustomGame.FactionDetailsRefresh.NameHints.Length - 1);
		foreach (var methodName in GameSymbols.CustomGame.FactionSelectButtonBind.NameHints)
			patched += PatchByName(h, log, "Hex.BhFactionSelectButton", methodName, 3, postfixName: nameof(PostfixStrongholdPickFactionButton), logMissing: methodName == GameSymbols.CustomGame.FactionSelectButtonBind.NameHints[^1]);
		foreach (var methodName in GameSymbols.CustomGame.FactionSelectButtonRefresh.NameHints)
			patched += PatchByName(h, log, "Hex.BhFactionSelectButton", methodName, 3, postfixName: nameof(PostfixHomm3PickFactionButtonRefresh), logMissing: methodName == GameSymbols.CustomGame.FactionSelectButtonRefresh.NameHints[^1]);
		patched += PatchQuickStartRectLayouts(h, log);
		patched += PatchByAnyName(h, log, "Hex.BhHeroSelectButton", GameSymbols.CustomGame.HeroSelectButtonBind.NameHints, 3, postfixName: nameof(PostfixHomm3PickHeroButton));
		patched += PatchByAnyName(h, log, "Hex.Pick.BhHeroDetails", GameSymbols.CustomGame.HeroDetailsBind.NameHints, 1, postfixName: nameof(PostfixHomm3PickHeroDetails));
		patched += PatchPickSkillView(h, log);
		patched += PatchPickUnitSlot(h, log);
		patched += PatchLobbyHeroElement(h, log, postfixName: nameof(PostfixStrongholdHeroElement));

		_patched = true;
		log?.LogInfo("ReleaseCustomGameUiProbe: " + patched + " release Stronghold Custom Game integration patch(es) registered.");
	}

	private static int PatchQuickStartRectLayouts(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		var seen = new HashSet<string>();
		for (var i = 0; i < GameSymbols.CustomGame.QuickStartRectLayoutMethods.Length; i++)
		{
			var candidate = GameSymbols.CustomGame.QuickStartRectLayoutMethods[i];
			var key = candidate.Name + "/" + candidate.ParameterCount;
			if (!seen.Add(key))
				continue;
			patched += PatchByName(
				h,
				log,
				"Hex.QuickStart.ScQuickStart",
				candidate.Name,
				candidate.ParameterCount,
				postfixName: nameof(PostfixScQuickStartRectLayout),
				logMissing: i == GameSymbols.CustomGame.QuickStartRectLayoutMethods.Length - 1);
		}
		return patched;
	}

	private static int PatchPickUnitSlot(Harmony h, ManualLogSource log)
	{
		foreach (var typeName in GameSymbols.CustomGame.UnitSlotTypeHints)
		{
			var count = PatchByAnyName(h, log, typeName, GameSymbols.CustomGame.UnitSlotBind.NameHints, 4, postfixName: nameof(PostfixStrongholdPickUnitSlot));
			if (count > 0)
				return count;
		}
		return 0;
	}

	private static int PatchPickSkillView(Harmony h, ManualLogSource log)
	{
		foreach (var typeName in GameSymbols.CustomGame.SkillViewTypeHints)
		{
			var count = PatchByAnyName(
				h,
				log,
				typeName,
				GameSymbols.CustomGame.SkillViewSkillBind.NameHints,
				2,
				postfixName: nameof(PostfixHomm3PickSkillView));
			if (count > 0)
				return count;
		}
		return 0;
	}

	private static int PatchByAnyName(Harmony h, ManualLogSource log, string typeName, string[] methodNames, int parameterCount, string prefixName = null, string postfixName = null)
	{
		if (methodNames == null || methodNames.Length == 0)
			return 0;

		for (var i = 0; i < methodNames.Length; i++)
		{
			var result = PatchByName(h, log, typeName, methodNames[i], parameterCount, prefixName, postfixName, logMissing: i == methodNames.Length - 1);
			if (result > 0)
				return result;
		}

		return 0;
	}

	private static int PatchByName(Harmony h, ManualLogSource log, string typeName, string methodName, int parameterCount, string prefixName = null, string postfixName = null, bool logMissing = true)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name == methodName && method.GetParameters().Length == parameterCount)
				{
					selected = method;
					break;
				}
			}

			if (selected == null)
			{
				if (logMissing)
				{
					log?.LogWarning("ReleaseCustomGameUiProbe: method not found: " + typeName + "." + methodName + "/" + parameterCount);
					LogCandidates(type, log);
				}
				return 0;
			}

			var probeType = typeof(ReleaseCustomGameUiProbe);
			var prefixMethod = prefixName == null ? null : probeType.GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
			var postfixMethod = postfixName == null ? null : probeType.GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, prefixMethod, out var prefixReason))
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: refusing incompatible prefix for " + FormatMethod(selected) + ": " + prefixReason);
				return 0;
			}
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfixMethod, out var postfixReason))
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: refusing incompatible postfix for " + FormatMethod(selected) + ": " + postfixReason);
				return 0;
			}
			var prefix = prefixMethod == null ? null : new HarmonyMethod(prefixMethod);
			var postfix = postfixMethod == null ? null : new HarmonyMethod(postfixMethod);
			h.Patch(selected, prefix: prefix, postfix: postfix);
			log?.LogInfo("ReleaseCustomGameUiProbe: patched " + FormatMethod(selected) + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("ReleaseCustomGameUiProbe: failed to patch " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchLobbyFractionElement(Harmony h, ManualLogSource log, string prefixName = null, string postfixName = null)
	{
		return PatchByShape(
			h,
			log,
			"Hex.GameHub.Lobby.UI.BhFraction",
			"String, Sprite, Boolean, Boolean",
			parameters =>
				parameters.Length == 4
				&& IsString(parameters[0].ParameterType)
				&& IsSprite(parameters[1].ParameterType)
				&& IsBool(parameters[2].ParameterType)
				&& IsBool(parameters[3].ParameterType),
			prefixName,
			postfixName);
	}

	private static int PatchLobbyHeroElement(Harmony h, ManualLogSource log, string prefixName = null, string postfixName = null)
	{
		return PatchByShape(
			h,
			log,
			"Hex.GameHub.Lobby.UI.BhHero",
			"String, Boolean, Boolean, Action<T>",
			parameters =>
				parameters.Length == 4
				&& IsString(parameters[0].ParameterType)
				&& IsBool(parameters[1].ParameterType)
				&& IsBool(parameters[2].ParameterType)
				&& IsAction(parameters[3].ParameterType),
			prefixName,
			postfixName);
	}

	private static int PatchByShape(Harmony h, ManualLogSource log, string typeName, string shapeName, Func<ParameterInfo[], bool> matches, string prefixName = null, string postfixName = null)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				var parameters = method.GetParameters();
				if (matches(parameters))
				{
					selected = method;
					break;
				}
			}

			if (selected == null)
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: method shape not found: " + typeName + "(" + shapeName + ")");
				LogCandidates(type, log);
				return 0;
			}

			var probeType = typeof(ReleaseCustomGameUiProbe);
			var prefixMethod = prefixName == null ? null : probeType.GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
			var postfixMethod = postfixName == null ? null : probeType.GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, prefixMethod, out var prefixReason))
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: refusing incompatible shape prefix for " + FormatMethod(selected) + ": " + prefixReason);
				return 0;
			}
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfixMethod, out var postfixReason))
			{
				log?.LogWarning("ReleaseCustomGameUiProbe: refusing incompatible shape postfix for " + FormatMethod(selected) + ": " + postfixReason);
				return 0;
			}
			var prefix = prefixMethod == null ? null : new HarmonyMethod(prefixMethod);
			var postfix = postfixMethod == null ? null : new HarmonyMethod(postfixMethod);
			h.Patch(selected, prefix: prefix, postfix: postfix);
			log?.LogInfo("ReleaseCustomGameUiProbe: patched " + FormatMethod(selected) + " by shape " + shapeName + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("ReleaseCustomGameUiProbe: failed to patch shape " + typeName + "(" + shapeName + "): " + ex.Message);
			return 0;
		}
	}

	private static bool IsString(Type type)
	{
		return type == typeof(string) || string.Equals(type?.FullName, "System.String", StringComparison.Ordinal);
	}

	private static bool IsBool(Type type)
	{
		return type == typeof(bool) || string.Equals(type?.FullName, "System.Boolean", StringComparison.Ordinal);
	}

	private static bool IsSprite(Type type)
	{
		return type == typeof(Sprite) || string.Equals(type?.FullName, "UnityEngine.Sprite", StringComparison.Ordinal) || typeof(Sprite).IsAssignableFrom(type);
	}

	private static bool IsAction(Type type)
	{
		if (type == null)
			return false;
		return type.Name.StartsWith("Action`", StringComparison.Ordinal)
			|| (type.FullName != null && type.FullName.EndsWith(".Action`1", StringComparison.Ordinal));
	}

	private static void PostfixPickInit(object __instance)
	{
		if (_pickInitLogged >= 8)
			return;
		_pickInitLogged++;
		LogInfo("[RCG.Init #" + _pickInitLogged + "] " + SummarizePickView(__instance));
	}

	private static void PrefixPickStateChange(object __instance, object[] __args)
	{
		if (_stateLogged >= 80)
			return;
		var current = Arg(__args, 0);
		var previous = Arg(__args, 1);
		var signature = FormatUiState(previous) + " -> " + FormatUiState(current);
		if (!_stateSignatures.Add(signature))
			return;
		_stateLogged++;
		LogInfo("[RCG.State #" + _stateLogged + "] " + signature + " | " + SummarizePickView(__instance));
	}

	private static void PrefixFactionClick(object __instance, object[] __args)
	{
		if (_clickLogged >= 80)
			return;
		_clickLogged++;
		LogInfo("[RCG.FactionClick #" + _clickLogged + "] index=" + ArgString(__args, 0) + " | " + SummarizePickView(__instance));
	}

	private static void PrefixHeroClick(object __instance, object[] __args)
	{
		if (_clickLogged >= 80)
			return;
		_clickLogged++;
		LogInfo("[RCG.HeroClick #" + _clickLogged + "] index=" + ArgString(__args, 0) + " isBan=" + ArgString(__args, 1) + " | " + SummarizePickView(__instance));
	}

	private static void PrefixHeroHover(object __instance, object[] __args)
	{
		if (_clickLogged >= 80)
			return;
		_clickLogged++;
		LogInfo("[RCG.HeroHover #" + _clickLogged + "] index=" + ArgString(__args, 0) + " isBan=" + ArgString(__args, 1) + " | " + SummarizePickView(__instance));
	}

	private static void PrefixHeroGrid(object __instance, object[] __args)
	{
		if (_heroGridLogged >= 20)
			return;
		_heroGridLogged++;
		var heroes = Arg(__args, 3);
		LogInfo(
			"[RCG.HeroGrid #" + _heroGridLogged + "] isBan=" + ArgString(__args, 0)
			+ " heroes=" + FormatListSummary(heroes, 16)
			+ " | " + SummarizePickView(__instance));
	}

	private static void PrefixSummaryTransition(object __instance, object[] __args)
	{
		if (_summaryLogged >= 40)
			return;
		_summaryLogged++;
		LogInfo(
			"[RCG.SummaryTransition #" + _summaryLogged + "] showImmediate=" + ArgString(__args, 0)
			+ " delay=" + ArgString(__args, 1)
			+ " side=" + ArgString(__args, 2)
			+ " | " + SummarizePickView(__instance));
	}

	private static void PrefixHeroSelectButtonSetup(object[] __args)
	{
		if (_heroButtonLogged >= 120)
			return;
		_heroButtonLogged++;
		LogInfo("[RCG.HeroButtonSetup #" + _heroButtonLogged + "] hero=" + FormatConfig(Arg(__args, 0)));
	}

	private static void PrefixSummarySetup(object[] __args)
	{
		if (_summaryLogged >= 80)
			return;
		_summaryLogged++;
		LogInfo("[RCG.SummarySetup #" + _summaryLogged + "] hero=" + FormatConfig(Arg(__args, 0)) + " faction=" + ArgString(__args, 1));
	}

	private static void PrefixSummarySpinner(object[] __args)
	{
		if (_summaryLogged >= 80)
			return;
		_summaryLogged++;
		LogInfo("[RCG.SummarySpinner #" + _summaryLogged + "] side=" + ArgString(__args, 0) + " text=" + ArgString(__args, 1));
	}

	private static void PrefixSummaryHeroConfigInternal(object[] __args)
	{
		if (_summaryLogged >= 80)
			return;
		_summaryLogged++;
		LogInfo("[RCG.SummaryHeroInternal #" + _summaryLogged + "] hero=" + FormatConfig(Arg(__args, 0)));
	}

	private static void PrefixLobbyPopupOpen(object __instance, object[] __args)
	{
		LogLobby("PopupOpen", FormatType(__instance) + " param=" + FormatSimple(Arg(__args, 0)));
	}

	private static void PostfixLobbyFractionList(object __instance, object __result)
	{
		var statuses = new List<string>();
		foreach (var factionSid in Homm3CustomFactionRegistry.EnumerateReleaseUiPresentationFactionSids())
			statuses.Add(factionSid + "=" + TryInjectFactionOption(__result, factionSid));
		LogLobby("FractionList", FormatType(__instance) + " result=" + FormatListSummary(__result, 16) + " " + string.Join(" ", statuses));
	}

	private static void PrefixLobbyFractionCurrent(object __instance, object[] __args)
	{
		LogLobby(
			"FractionCurrent",
			"sid=" + ArgString(__args, 0)
			+ " interactable=" + ArgString(__args, 2)
			+ " locked=" + ArgString(__args, 3)
			+ " | " + SummarizeLobbySelection(__instance));
	}

	private static void PrefixLobbyFractionSelected(object __instance, ref string a)
	{
		var original = a;
		if (_translateDungeonSelectionToStronghold && string.Equals(a, "dungeon", StringComparison.OrdinalIgnoreCase))
			a = "homm3_stronghold";
		LogLobby("FractionSelected", "sid=" + original + " translated=" + a + " | " + SummarizeLobbySelection(__instance));
	}

	private static void PrefixLobbyFractionElement(object __instance, object[] __args)
	{
		LogLobby(
			"FractionElement",
			"sid=" + ArgString(__args, 0)
			+ " interactable=" + ArgString(__args, 2)
			+ " locked=" + ArgString(__args, 3)
			+ " | " + SummarizeLobbySelection(__instance));
	}

	private static void PostfixLobbyFractionElement(object __instance, object[] __args)
	{
		var factionSid = GetHomm3LobbyPopupFractionSid(__instance, __args);
		if (factionSid == null)
			return;

		ApplyHomm3LobbyPopupRowText(__instance, factionSid);
	}

	private static void PrefixStrongholdFractionButtonClick(object __instance, out string __state)
	{
		__state = null;
		var sid = FormatSimple(GetMemberValue(__instance, "fractionSid"));
		var translated = sid;
		if (!TranslateStrongholdFactionSid(ref translated, "button") || string.Equals(translated, sid, StringComparison.OrdinalIgnoreCase))
			return;

		if (SetMemberValue(__instance, translated, "fractionSid"))
		{
			__state = sid;
		}
		if (__state != null && _lobbyLogged < 180)
			LogLobby("FractionButtonTranslate", "sid=" + sid + " translated=" + translated + " | " + SummarizeLobbySelection(__instance));
	}

	private static void PostfixStrongholdFractionButtonClick(object __instance, string __state)
	{
		if (!string.IsNullOrEmpty(__state))
			SetMemberValue(__instance, __state, "fractionSid");
	}

	private static void PostfixStrongholdFractionAdditionalInfo(object __instance, object[] __args)
	{
		var fractionConfig = Arg(__args, 0);
		ApplyHomm3FactionAdditionalInfo(__instance, GetHomm3FactionSidFromConfig(fractionConfig));
	}

	private static void PostfixStrongholdLobbyPopupFractionElement(object __instance, object[] __args)
	{
		var factionSid = GetHomm3LobbyPopupFractionSid(__instance, __args);
		if (factionSid == null)
			return;

		ApplyHomm3FactionAdditionalInfo(GetMemberValue(__instance, "fractionAdditionalInfo"), factionSid);
		ApplyHomm3LobbyPopupRowText(__instance, factionSid);
		var fraction = GetMemberValue(__instance, "fraction");
		if (fraction != null && Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) && banner)
			ApplySpriteToFirstImage(fraction, banner);
	}

	private static void PostfixStrongholdPickFactionDetails(object __instance, object[] __args)
	{
		var factionSid = GetHomm3FactionSidFromConfig(Arg(__args, 0));
		if (factionSid == null)
		{
			LogPickUnitPortrait("BhFactionDetails skipped: unresolved faction config=" + FormatConfig(Arg(__args, 0)) + ".");
			ClearStrongholdSpriteOverride(GetMemberValue(__instance, "icon") as Image);
			ClearStrongholdSpriteOverride(GetMemberValue(__instance, "background") as Image);
			return;
		}

		ApplyHomm3FactionInfoText(__instance, factionSid, "nameText", "descriptionText");
		ApplyQuickPlayFactionDetailsPanelOffset(__instance, factionSid, "BhFactionDetails.bind");
		if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) && banner)
			ApplySpriteToImage(GetMemberValue(__instance, "icon") as Image, banner);
		ClearStrongholdSpriteOverride(GetMemberValue(__instance, "background") as Image);
		ApplyHomm3PickFactionDetailUnitSlots(__instance, factionSid);
	}

	private static void PostfixStrongholdPickFactionDetailsRefresh(object __instance, MethodBase __originalMethod)
	{
		var factionConfig = GetMemberValue(__instance, GameSymbols.CustomGame.FactionDetailsConfigFields);
		var factionSid = GetHomm3FactionSidFromConfig(factionConfig);
		if (factionSid == null)
		{
			LogPickUnitPortrait(
				"BhFactionDetails refresh skipped source='" + FormatMethod(__originalMethod as MethodInfo)
				+ "' storedFaction=" + FormatConfig(factionConfig) + ".");
			return;
		}

		LogPickUnitPortrait(
			"BhFactionDetails refresh source='" + FormatMethod(__originalMethod as MethodInfo)
			+ "' faction='" + factionSid + "'.");
		ApplyQuickPlayFactionDetailsPanelOffset(__instance, factionSid, "BhFactionDetails." + (__originalMethod?.Name ?? "?"));
		ApplyHomm3PickFactionDetailUnitSlots(__instance, factionSid);
	}

	private static void PostfixStrongholdPickFactionButton(object __instance, object[] __args)
	{
		var factionSid = GetHomm3FactionSidFromConfig(Arg(__args, 0));
		if (factionSid == null)
			return;

		ApplyHomm3PickFactionButtonText(__instance, factionSid);
		if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) && banner)
			ApplySpriteToImage(GetMemberValue(__instance, "icon") as Image, banner);
		ApplyHomm3PickFactionButtonBackground(__instance, factionSid);
		CompactHomm3PickFactionButton(__instance);
		CompactHomm3PickFactionGrid(__instance);
		LogQuickPlayFactionButtonLayout(__instance, factionSid, "BhFactionSelectButton.bind");
	}

	private static void PostfixHomm3PickFactionButtonRefresh(object __instance)
	{
		CompactHomm3PickFactionGrid(__instance);
	}

	private static void PostfixScQuickStartRectLayout(object __instance, object[] __args, MethodBase __originalMethod)
	{
		CompactHomm3QuickStartFactionGrid(__instance, "ScQuickStart." + (__originalMethod?.Name ?? "?"));
	}

	private static void PostfixHomm3PickHeroButton(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var heroSid = GetHomm3HeroSidFromConfig(Arg(__args, 0));
		if (heroSid == null)
			return;

		ApplyHomm3HeroPortraitToRow(
			__instance,
			heroSid,
			"BhHeroSelectButton." + (__originalMethod?.Name ?? "?"));
		ApplyHomm3HeroDisplayNameText(__instance, heroSid, "BhHeroSelectButton." + (__originalMethod?.Name ?? "?"));
	}

	private static void PostfixHomm3PickHeroDetails(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var heroSid = GetHomm3HeroSidFromConfig(Arg(__args, 0));
		if (heroSid == null)
			return;

		ApplyHomm3HeroPortraitToSurface(
			__instance,
			heroSid,
			"BhHeroDetails." + (__originalMethod?.Name ?? "?"),
			new[] { "portrait" },
			new[] { "randomPortrait" },
			allowDescendantFallback: false);
		ApplyHomm3PickHeroDetailsSpecializationIcon(
			__instance,
			Arg(__args, 0),
			heroSid,
			"BhHeroDetails." + (__originalMethod?.Name ?? "?"));
		ApplyHomm3HeroDisplayNameText(__instance, heroSid, "BhHeroDetails." + (__originalMethod?.Name ?? "?"));
	}

	private static void ApplyHomm3HeroDisplayNameText(object instance, string heroSid, string source)
	{
		if (instance is not Component component || !component || string.IsNullOrWhiteSpace(heroSid))
			return;
		if (!Homm3CustomFactionRegistry.TryGetHeroDisplayName(heroSid, out var displayName) || string.IsNullOrWhiteSpace(displayName))
			return;

		var changed = 0;
		var tmpTexts = component.GetComponentsInChildren<TMPro.TMP_Text>(true);
		for (var i = 0; i < tmpTexts.Length; i++)
		{
			var text = tmpTexts[i];
			if (!text || !LooksLikeCustomHeroTokenLabel(text.text, heroSid))
				continue;
			text.text = displayName;
			changed++;
		}

		var unityTexts = component.GetComponentsInChildren<Text>(true);
		for (var i = 0; i < unityTexts.Length; i++)
		{
			var text = unityTexts[i];
			if (!text || !LooksLikeCustomHeroTokenLabel(text.text, heroSid))
				continue;
			text.text = displayName;
			changed++;
		}

		if (changed > 0 && _quickPlayHeroTextLogged < 40)
		{
			_quickPlayHeroTextLogged++;
			Homm3UiCardDiagnostics.Log(
				"quickplay-hero-button-labels",
				"hero-label-localized",
				"source='" + (source ?? "?") + "' sid='" + heroSid + "' text='" + displayName + "' changed=" + changed + " view='" + DescribeComponent(component) + "'",
				limit: 40);
		}
	}

	private static bool LooksLikeCustomHeroTokenLabel(string text, string heroSid)
	{
		if (string.IsNullOrWhiteSpace(text))
			return false;
		var value = UnwrapLocalizationToken(text.Trim());
		if (string.Equals(value, heroSid, StringComparison.OrdinalIgnoreCase)
			|| string.Equals(value, heroSid + "_name", StringComparison.OrdinalIgnoreCase))
			return true;
		if (Homm3CustomFactionRegistry.TryReverseHeroPortraitKey(heroSid, out var iconKey)
			&& string.Equals(value, iconKey, StringComparison.OrdinalIgnoreCase))
			return true;
		if (Homm3CustomFactionRegistry.TryGetHeroSidFromDisplayLabel(value, out var displayHeroSid)
		    && string.Equals(displayHeroSid, heroSid, StringComparison.OrdinalIgnoreCase))
			return true;
		return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(value, out var normalized)
		       && string.Equals(normalized, heroSid, StringComparison.OrdinalIgnoreCase);
	}

	private static string UnwrapLocalizationToken(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return value;
		const string prefix = "LOC_[";
		return value.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) && value.EndsWith("]", StringComparison.Ordinal)
			? value.Substring(prefix.Length, value.Length - prefix.Length - 1).Trim()
			: value;
	}

	private static void PostfixStrongholdPickUnitSlot(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var sid = ArgString(__args, 1);
		LogPickUnitPortrait(
			"BhUnitSlot binder hit source='" + FormatMethod(__originalMethod as MethodInfo)
			+ "' slot='" + FormatType(__instance)
			+ "' sid='" + sid
			+ "' arg0='" + ArgString(__args, 0)
			+ "' arg2='" + ArgString(__args, 2)
			+ "' image=" + FormatImage(GetMemberValue(__instance, "portrait") as Image) + ".");
		ApplyHomm3PickUnitSlotPortrait(__instance, sid);
	}

	private static void ApplyHomm3PickFactionDetailUnitSlots(object details, string factionSid)
	{
		var unitSlots = GetMemberValue(details, "unitSlots");
		var unitSids = Homm3CustomFactionRegistry.GetRecruitmentBaseSids(factionSid);
		if (unitSlots == null || unitSids == null || unitSids.Length == 0)
		{
			LogPickUnitPortrait("BhFactionDetails unit slot repaint skipped faction='" + factionSid + "' unitSlots="
				+ FormatType(unitSlots) + " unitSids=" + (unitSids == null ? "null" : unitSids.Length.ToString()) + ".");
			return;
		}

		var count = GetCount(unitSlots);
		if (count <= 0)
			count = unitSids.Length;
		LogPickUnitPortrait("BhFactionDetails repaint faction='" + factionSid + "' slotCount=" + count + " unitSids=" + unitSids.Length + ".");
		for (var i = 0; i < count && i < unitSids.Length; i++)
		{
			var slot = GetIndexedValue(unitSlots, i);
			if (slot == null)
			{
				LogPickUnitPortrait("BhFactionDetails slot " + i + " is null for faction='" + factionSid + "'.");
				continue;
			}
			ApplyHomm3PickUnitSlotPortrait(slot, unitSids[i]);
		}
	}

	private static void ApplyHomm3PickUnitSlotPortrait(object slot, string sid)
	{
		var image = GetMemberValue(slot, "portrait") as Image;
		if (!IsHomm3UnitSid(sid))
		{
			LogPickUnitPortrait("BhUnitSlot portrait clear sid='" + sid + "' image=" + FormatImage(image) + ".");
			ClearHomm3PortraitSpriteOverride(image);
			return;
		}

		if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out var sprite) || !sprite)
		{
			LogPickUnitPortrait("BhUnitSlot portrait missing sprite sid='" + sid + "' image=" + FormatImage(image) + ".");
			return;
		}

		ApplySpriteToImage(image, sprite);
		HidePickUnitSlotPlaceholderOverlays(slot);
		LogPickUnitPortrait("BhUnitSlot portrait applied sid='" + sid + "' sprite='" + sprite.name + "' image=" + FormatImage(image) + ".");
	}

	private static void HidePickUnitSlotPlaceholderOverlays(object slot)
	{
		if (slot == null)
			return;
		DisableGraphic(GetMemberValue(slot, "random"));
		DisableGraphic(GetMemberValue(slot, "randomIcon"));
		DisableGraphic(GetMemberValue(slot, "shadow"));
	}

	private static void DisableGraphic(object candidate)
	{
		if (candidate is Graphic graphic)
		{
			graphic.enabled = false;
			return;
		}
		if (candidate is Component component)
			graphic = component.GetComponent<Graphic>();
		else if (candidate is GameObject gameObject)
			graphic = gameObject.GetComponent<Graphic>();
		else
			return;
		if (graphic)
			graphic.enabled = false;
	}

	private static string GetHomm3LobbyPopupFractionSid(object instance, object[] args)
	{
		var sid = ArgString(args, 0);
		if (IsHomm3LobbyFactionSid(sid))
			return sid.Trim();

		sid = FormatSimple(GetMemberValue(instance, "bwvc", "fractionSid", "sid"));
		return IsHomm3LobbyFactionSid(sid) ? sid.Trim() : null;
	}

	private static void ApplyHomm3FactionAdditionalInfo(object instance, string factionSid)
	{
		if (instance == null)
			return;

		var image = GetMemberValue(instance, "icon") as Image;
		if (image == null)
			image = (instance as Component)?.GetComponentInChildren<Image>(true);
		if (image == null)
			return;

		if (factionSid == null)
		{
			if (Homm3StrongholdFactionBannerSpriteCache.IsHomm3FactionSprite(image.overrideSprite))
				image.overrideSprite = null;
			return;
		}

		ApplyHomm3FactionInfoText(instance, factionSid);

		if (!Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) || !banner)
			return;

		ApplySpriteToImage(image, banner);
	}

	private static void ApplyStrongholdFactionInfoText(object instance)
	{
		ApplyHomm3FactionInfoText(instance, "homm3_stronghold", "fractionName", "description");
	}

	private static void ApplyHomm3FactionInfoText(object instance, string factionSid)
	{
		ApplyHomm3FactionInfoText(instance, factionSid, "fractionName", "description");
	}

	private static void ApplyHomm3FactionInfoText(object instance, string factionSid, string nameMember, string descriptionMember)
	{
		SetTextComponent(GetMemberValue(instance, nameMember), GetHomm3FactionName(factionSid));
		SetTextComponent(GetMemberValue(instance, descriptionMember), GetHomm3FactionDescription(factionSid));
	}

	private static void ApplyHomm3LobbyPopupRowText(object instance, string factionSid)
	{
		if (instance == null || string.IsNullOrWhiteSpace(factionSid))
			return;

		var name = GetHomm3FactionName(factionSid);
		SetTextComponent(GetMemberValue(instance, "name", "title", "fractionName", "label", "text"), name);
		if (instance is not Component component || !component)
			return;

		var tmpTexts = component.GetComponentsInChildren<TMPro.TextMeshProUGUI>(true);
		for (var i = 0; i < tmpTexts.Length; i++)
		{
			var text = tmpTexts[i];
			if (!text || !LooksLikeFactionLabel(text.text))
				continue;
			text.text = name;
			text.enabled = true;
			text.gameObject.SetActive(true);
		}

		var unityTexts = component.GetComponentsInChildren<Text>(true);
		for (var i = 0; i < unityTexts.Length; i++)
		{
			var text = unityTexts[i];
			if (!text || !LooksLikeFactionLabel(text.text))
				continue;
			text.text = name;
			text.enabled = true;
			text.gameObject.SetActive(true);
		}
	}

	private static void ApplyHomm3PickFactionButtonText(object instance, string factionSid)
	{
		if (instance == null || string.IsNullOrWhiteSpace(factionSid))
			return;

		var name = GetHomm3FactionName(factionSid);
		var title = GetMemberValue(instance, "title");
		EnsureHomm3PickFactionButtonTileLabel(instance, title, factionSid);
		LogQuickPlayFactionButtonText(instance, title, factionSid, name);
	}

	private static void ApplyHomm3PickFactionButtonBackground(object instance, string factionSid)
	{
		if (instance == null || string.IsNullOrWhiteSpace(factionSid))
			return;
		var background = GetMemberValue(instance, "background") as Image;
		if (!background)
		{
			LogQuickPlayFactionButtonBackground(instance, factionSid, null, "missing-background-field");
			return;
		}
		if (!Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateCardSpriteForFaction(factionSid, out var card) || !card)
		{
			LogQuickPlayFactionButtonBackground(instance, factionSid, background, "missing-card-sprite");
			return;
		}
		ApplySpriteToImagePreservingColor(background, card);
		background.preserveAspect = false;
		LogQuickPlayFactionButtonBackground(instance, factionSid, background, "applied");
	}

	private static void EnsureHomm3PickFactionButtonTileLabel(object instance, object title, string factionSid)
	{
		if (instance is not Component component || !component)
			return;

		var labelText = GetHomm3FactionTileName(factionSid);
		if (string.IsNullOrWhiteSpace(labelText))
			return;

		var labelParent = GetMemberValue(instance, "moveRoot") as RectTransform;
		if (!labelParent)
			labelParent = component.GetComponent<RectTransform>();
		if (!labelParent)
			return;

		var source = GetMemberValue(title, "textElement_") as TMPro.TMP_Text;
		if (!source)
			source = (title as Component)?.GetComponentInChildren<TMPro.TMP_Text>(true);
		if (!source)
			source = FindFirstNonSyntheticText(component);
		if (!source || !source.GetComponent<RectTransform>())
		{
			Homm3UiCardDiagnostics.Log(
				"quickplay-faction-button-labels",
				"native-label-source-missing",
				"faction='" + factionSid + "' button='" + DescribeComponent(component) + "' title='" + DescribeComponent(title as Component) + "'",
				limit: 20);
			return;
		}

		var labelTransform = labelParent.Find("HOMM3 QuickPlay Faction Label");
		TMPro.TextMeshProUGUI label = null;
		if (labelTransform)
			label = labelTransform.GetComponent<TMPro.TextMeshProUGUI>();
		if (!label)
		{
			var existingLabels = component.GetComponentsInChildren<TMPro.TextMeshProUGUI>(true);
			for (var i = 0; i < existingLabels.Length; i++)
			{
				var existing = existingLabels[i];
				if (!IsSyntheticQuickPlayFactionLabel(existing))
					continue;
				label = existing;
				label.transform.SetParent(labelParent, false);
				break;
			}
		}

		if (!label)
		{
			var labelObject = new GameObject("HOMM3 QuickPlay Faction Label");
			labelObject.layer = component.gameObject.layer;
			labelObject.transform.SetParent(labelParent, false);
			labelObject.AddComponent<RectTransform>();
			label = labelObject.AddComponent<TMPro.TextMeshProUGUI>();
		}

		if (source)
		{
			label.font = source.font;
			label.fontSharedMaterial = source.fontSharedMaterial;
		}

		label.text = labelText;
		ConfigureQuickPlayFactionTileLabel(label, source);
		label.transform.SetAsLastSibling();
		ApplyQuickPlayFactionTileLabelRect(label, source);
		HideQuickPlayNativeFactionLabelSource(source, label);
	}

	private static void ConfigureQuickPlayFactionTileLabel(TMPro.TMP_Text label, TMPro.TMP_Text source)
	{
		if (!label)
			return;
		label.enabled = true;
		label.gameObject.SetActive(true);
		label.color = source ? source.color : Color.white;
		label.alignment = source ? source.alignment : TMPro.TextAlignmentOptions.Center;
		label.enableWordWrapping = source ? source.enableWordWrapping : false;
		label.overflowMode = source ? source.overflowMode : TMPro.TextOverflowModes.Ellipsis;
		label.fontStyle = source ? source.fontStyle : label.fontStyle;
		label.characterSpacing = source ? source.characterSpacing : label.characterSpacing;
		label.lineSpacing = source ? source.lineSpacing : label.lineSpacing;
		var sourceSize = source && source.fontSize > 0f ? source.fontSize : 24f;
		label.fontSize = Mathf.Max(sourceSize * QuickPlayFactionTileLabelFontScale, 24f);
		label.raycastTarget = false;
	}

	private static void ApplyQuickPlayFactionTileLabelRect(TMPro.TMP_Text label, TMPro.TMP_Text source)
	{
		if (!label)
			return;
		var rect = label.GetComponent<RectTransform>();
		if (!rect)
			return;
		var sourceRect = source ? source.GetComponent<RectTransform>() : null;
		if (!sourceRect)
			return;
		var sourceParent = sourceRect.transform.parent ? sourceRect.transform.parent.GetComponent<RectTransform>() : null;
		if (sourceParent && rect.transform.parent != sourceParent.transform)
			rect.transform.SetParent(sourceParent, false);
		rect.anchorMin = sourceRect.anchorMin;
		rect.anchorMax = sourceRect.anchorMax;
		rect.pivot = sourceRect.pivot;
		rect.anchoredPosition = sourceRect.anchoredPosition;
		rect.sizeDelta = new Vector2(
			Mathf.Max(sourceRect.sizeDelta.x * QuickPlayFactionTileLabelFontScale, 344f * QuickPlayFactionTileLabelFontScale),
			Mathf.Max(sourceRect.sizeDelta.y * QuickPlayFactionTileLabelFontScale, 32f));
		rect.localScale = sourceRect.localScale;
	}

	private static void HideQuickPlayNativeFactionLabelSource(TMPro.TMP_Text source, TMPro.TMP_Text synthetic)
	{
		if (!source || !synthetic || source == synthetic || IsSyntheticQuickPlayFactionLabel(source))
			return;
		source.enabled = false;
		source.gameObject.SetActive(false);
	}

	private static void ApplyFactionLabelToChildTexts(object instance, string name)
	{
		ApplyTextUnderComponent(instance, name, requireLabelLike: true);
	}

	private static void ApplyTextUnderComponent(object instance, string name, bool requireLabelLike)
	{
		if (string.IsNullOrWhiteSpace(name) || instance is not Component component || !component)
			return;

		var tmpTexts = component.GetComponentsInChildren<TMPro.TMP_Text>(true);
		for (var i = 0; i < tmpTexts.Length; i++)
		{
			var text = tmpTexts[i];
			if (!text || (requireLabelLike && !LooksLikeFactionLabel(text.text)))
				continue;
			if (IsSyntheticQuickPlayFactionLabel(text))
				continue;
			text.text = name;
			text.enabled = true;
			text.color = Color.white;
			text.gameObject.SetActive(true);
		}

		var unityTexts = component.GetComponentsInChildren<Text>(true);
		for (var i = 0; i < unityTexts.Length; i++)
		{
			var text = unityTexts[i];
			if (!text || (requireLabelLike && !LooksLikeFactionLabel(text.text)))
				continue;
			if (IsSyntheticQuickPlayFactionLabel(text))
				continue;
			text.text = name;
			text.enabled = true;
			text.color = Color.white;
			text.gameObject.SetActive(true);
		}
	}

	private static TMPro.TMP_Text FindFirstNonSyntheticText(Component root)
	{
		if (!root)
			return null;
		var texts = root.GetComponentsInChildren<TMPro.TMP_Text>(true);
		for (var i = 0; i < texts.Length; i++)
		{
			var text = texts[i];
			if (text && !IsSyntheticQuickPlayFactionLabel(text))
				return text;
		}
		return null;
	}

	private static bool IsSyntheticQuickPlayFactionLabel(Component component)
	{
		return component && component.transform && string.Equals(component.transform.name, "HOMM3 QuickPlay Faction Label", StringComparison.Ordinal);
	}

	private static bool IsChildOfComponent(Component child, Component parent)
	{
		if (!child || !parent)
			return false;
		var current = child.transform;
		var root = parent.transform;
		while (current)
		{
			if (current == root)
				return true;
			current = current.parent;
		}
		return false;
	}

	private static bool LooksLikeFactionLabel(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return true;
		var s = text.Trim();
		return string.Equals(s, "Temple", StringComparison.OrdinalIgnoreCase)
		       || Homm3CustomFactionRegistry.LooksLikeCustomFactionLabel(s)
		       || string.Equals(s, "human_name", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(s, "temple_name", StringComparison.OrdinalIgnoreCase);
	}

	private static void SetTextComponent(object textComponent, string text)
	{
		if (textComponent == null || string.IsNullOrEmpty(text))
			return;

		if (!InvokeStringMethod(textComponent, text, "HardSetText", "SetText", "ewd", "sth", "dod", "gcw", "kkz"))
		{
			SetMemberValue(textComponent, text, "text");
			var textElement = GetMemberValue(textComponent, "textElement_") as TMPro.TextMeshProUGUI;
			if (textElement != null)
				textElement.text = text;
		}
		if (textComponent is Behaviour behaviour)
			behaviour.enabled = true;
		if (textComponent is Component component && component.gameObject != null)
			component.gameObject.SetActive(true);
	}

	private static bool InvokeStringMethod(object value, string argument, params string[] names)
	{
		if (value == null || string.IsNullOrEmpty(argument))
			return false;

		var type = value.GetType();
		foreach (var name in names)
		{
			var method = type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, new[] { typeof(string) }, null);
			if (method == null)
				continue;
			try
			{
				method.Invoke(value, new object[] { argument });
				return true;
			}
			catch { }
		}
		return false;
	}

	private static void ApplySpriteToFirstImage(object owner, Sprite sprite)
	{
		if (owner == null || !sprite)
			return;

		var image = GetMemberValue(owner, "icon") as Image;
		if (image == null)
			image = (owner as Component)?.GetComponentInChildren<Image>(true);
		ApplySpriteToImage(image, sprite);
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
		if (image.gameObject != null)
			image.gameObject.SetActive(true);
	}

	private static void ApplySpriteToImagePreservingColor(Image image, Sprite sprite)
	{
		if (image == null || !sprite)
			return;

		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.enabled = true;
		if (image.gameObject != null)
			image.gameObject.SetActive(true);
	}

	private static bool TrySetBhIconSprite(object icon, Sprite sprite, out string reason)
	{
		reason = null;
		if (icon == null)
		{
			reason = "skillIcon=null";
			return false;
		}
		if (!sprite)
		{
			reason = "sprite=null";
			return false;
		}

		var type = icon.GetType();
		foreach (var name in GameSymbols.CustomGame.BhIconSetSprite.NameHints)
		{
			var method = type.GetMethod(
				name,
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
				null,
				new[] { typeof(Sprite) },
				null);
			if (method == null)
				continue;
			try
			{
				method.Invoke(icon, new object[] { sprite });
				return true;
			}
			catch (Exception ex)
			{
				reason = "setter '" + name + "' failed: " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}

		reason = "missing BhIcon sprite setter on " + FormatType(icon);
		return false;
	}

	private static void CompactHomm3PickFactionButton(object button)
	{
		if (button is not Component component || !component)
			return;

		var rect = component.GetComponent<RectTransform>();
		if (rect)
		{
			rect.localScale = new Vector3(0.84f, 0.84f, 1f);
			if (rect.sizeDelta.x > 120f)
				rect.sizeDelta = new Vector2(Mathf.Min(rect.sizeDelta.x, 120f), rect.sizeDelta.y);
		}

		var layout = component.GetComponent<LayoutElement>();
		if (layout)
		{
			if (layout.preferredWidth > 0f)
				layout.preferredWidth = Mathf.Min(layout.preferredWidth, 120f);
			if (layout.minWidth > 0f)
				layout.minWidth = Mathf.Min(layout.minWidth, 100f);
			if (layout.flexibleWidth == 0f)
				layout.flexibleWidth = 1f;
		}

		var parent = component.transform?.parent;
		if (parent == null)
			return;

		var horizontal = parent.GetComponent<HorizontalLayoutGroup>();
		if (horizontal)
		{
			horizontal.spacing = Mathf.Min(horizontal.spacing, 4f);
			horizontal.childForceExpandWidth = false;
		}

		var grid = parent.GetComponent<GridLayoutGroup>();
		if (grid)
		{
			grid.spacing = new Vector2(Mathf.Min(grid.spacing.x, 4f), Mathf.Min(grid.spacing.y, 4f));
			if (grid.cellSize.x > 120f)
				grid.cellSize = new Vector2(120f, grid.cellSize.y);
		}
	}

	private static void CompactHomm3PickFactionGrid(object button)
	{
		if (button is not Component component || !component)
			return;
		var parent = component.transform?.parent ? component.transform.parent.GetComponent<RectTransform>() : null;
		if (!parent)
			return;

		var quickStart = FindAncestorComponentByTypeName(component.transform, "ScQuickStart", 12);
		CompactHomm3FactionButtonRoot(parent, "BhFactionSelectButton.parent", quickStart);
	}

	private static void CompactHomm3QuickStartFactionGrid(object quickStart, string source)
	{
		var root = GetMemberValue(quickStart, "factionsRoot") as RectTransform;
		if (!root)
			return;
		CompactHomm3FactionButtonRoot(root, source, quickStart as Component);
	}

	private static void CompactHomm3FactionButtonRoot(RectTransform parent, string source, Component quickStart)
	{
		if (!parent)
			return;

		var buttons = GetQuickPlayFactionButtons(parent, quickStart);
		if (buttons.Count <= 8)
			return;

		const float width = 120f;
		const float height = 150f;
		const float footprintWidth = 344f * QuickPlayFactionTileLabelFontScale;
		const float footprintHeight = 210f;
		ResolveQuickPlayFactionGridLayout(parent, quickStart, buttons.Count, footprintWidth, footprintHeight, out var columns, out var rows, out var step);
		var xStep = step.x;
		var yStep = step.y;
		var totalWidth = (columns - 1) * xStep;
		var totalHeight = (rows - 1) * yStep;
		var centerX = Mathf.Clamp(parent.rect.width * QuickPlayFactionGridCenterXRatio, -640f, 0f);

		for (var i = 0; i < buttons.Count; i++)
		{
			var rect = buttons[i];
			var column = i % columns;
			var row = i / columns;
			rect.anchorMin = new Vector2(0.5f, 0.5f);
			rect.anchorMax = new Vector2(0.5f, 0.5f);
			rect.pivot = new Vector2(0.5f, 0.5f);
			rect.sizeDelta = new Vector2(width, height);
			rect.localScale = new Vector3(0.84f, 0.84f, 1f);
			rect.anchoredPosition = new Vector2(centerX + column * xStep - totalWidth * 0.5f, totalHeight * 0.5f - row * yStep);
			NormalizeQuickPlayFactionTileLabels(GetBhFactionSelectButtonComponent(rect));
		}
		LogQuickPlayActiveFactionGrid(parent, buttons.Count, source);
	}

	private static List<RectTransform> GetQuickPlayFactionButtons(RectTransform parent, Component quickStart)
	{
		var nativeButtons = TryGetNativeQuickPlayFactionButtons(parent, quickStart, out var nativeCount);
		if (nativeButtons.Count == nativeCount && nativeCount > 0)
			return nativeButtons;
		if (nativeCount > 0)
			LogQuickPlayFactionNativeListFallback(parent, quickStart, nativeCount, nativeButtons.Count);

		var buttons = new List<RectTransform>();
		for (var i = 0; i < parent.childCount; i++)
		{
			var child = parent.GetChild(i)?.GetComponent<RectTransform>();
			if (!child || !HasComponentTypeName(child, "BhFactionSelectButton"))
				continue;
			if (!child.gameObject.activeSelf)
				continue;
			buttons.Add(child);
		}
		return buttons;
	}

	private static List<RectTransform> TryGetNativeQuickPlayFactionButtons(RectTransform parent, Component quickStart, out int nativeCount)
	{
		var buttons = new List<RectTransform>();
		nativeCount = -1;
		if (!parent || !quickStart)
			return buttons;
		var nativeButtons = GetMemberValue(quickStart, "bslq");
		nativeCount = GetCount(nativeButtons);
		if (nativeCount <= 0)
			return buttons;
		var seen = new HashSet<int>();
		for (var i = 0; i < nativeCount; i++)
		{
			var button = GetIndexedValue(nativeButtons, i);
			var rect = GetRectTransformForQuickPlayFactionButton(button);
			if (!rect || rect.parent != parent || !HasComponentTypeName(rect, "BhFactionSelectButton"))
				continue;
			if (!seen.Add(rect.GetInstanceID()))
				continue;
			buttons.Add(rect);
		}
		return buttons;
	}

	private static RectTransform GetRectTransformForQuickPlayFactionButton(object button)
	{
		if (button is RectTransform rect)
			return rect;
		if (button is Component component)
			return component.GetComponent<RectTransform>();
		if (button is GameObject gameObject)
			return gameObject.GetComponent<RectTransform>();
		var transform = GetMemberValue(button, "transform") as Transform;
		return transform ? transform.GetComponent<RectTransform>() : null;
	}

	private static void ApplyQuickPlayFactionDetailsPanelOffset(object instance, string factionSid, string source)
	{
		if (instance is not Component component || !component)
			return;
		var rect = component.GetComponent<RectTransform>();
		if (!rect)
			return;
		var id = rect.GetInstanceID();
		if (!_quickPlayFactionDetailsOriginalPositions.TryGetValue(id, out var original))
		{
			original = rect.anchoredPosition;
			_quickPlayFactionDetailsOriginalPositions[id] = original;
		}
		var offsetX = Mathf.Clamp((rect.parent as RectTransform)?.rect.width * QuickPlayFactionGridCenterXRatio ?? -460f, -640f, 0f);
		rect.anchoredPosition = new Vector2(original.x + offsetX, original.y);
		LogQuickPlayFactionDetailsLayout(rect, factionSid, source, original, offsetX);
	}

	private static void ResolveQuickPlayFactionGridLayout(RectTransform parent, Component quickStart, int count, float footprintWidth, float footprintHeight, out int columns, out int rows, out Vector2 step)
	{
		var xStep = 720f;
		var yStep = 800f;
		var spacing = GetMemberValue(quickStart, "factionButtonSpacing");
		if (spacing is Vector2 vector)
		{
			if (vector.x > 0f)
				xStep = vector.x;
			if (vector.y > 0f)
				yStep = vector.y;
		}
		var nativeYStep = yStep;
		var compactYStep = Mathf.Max(1f, nativeYStep * QuickPlayFactionVerticalSpacingScale);

		var parentWidth = parent.rect.width;
		var parentHeight = parent.rect.height;
		var maxColumnsAtDesired = 1;
		if (parentWidth > footprintWidth && xStep > 0f)
			maxColumnsAtDesired = Mathf.FloorToInt((parentWidth - footprintWidth) / xStep) + 1;
		maxColumnsAtDesired = Mathf.Clamp(maxColumnsAtDesired, 1, count);

		var maxRowsAtDesired = 1;
		if (parentHeight > footprintHeight && nativeYStep > 0f)
			maxRowsAtDesired = Mathf.FloorToInt((parentHeight - footprintHeight) / nativeYStep) + 1;
		maxRowsAtDesired = Mathf.Max(maxRowsAtDesired, 1);

		var columnsNeededForDesiredRows = Mathf.CeilToInt(count / (float)maxRowsAtDesired);
		columns = Mathf.Clamp(columnsNeededForDesiredRows, 1, maxColumnsAtDesired);
		rows = Mathf.CeilToInt(count / (float)columns);

		var minXStep = Mathf.Min(300f, xStep);
		if (parentWidth > footprintWidth && columns > 1)
		{
			var maxFitStep = (parentWidth - footprintWidth) / (columns - 1);
			xStep = Mathf.Min(Mathf.Max(xStep, minXStep), maxFitStep);
		}
		else
		{
			xStep = Mathf.Max(xStep, minXStep);
		}
		yStep = compactYStep;
		var minYStep = Mathf.Min(360f, yStep);
		if (parentHeight > footprintHeight && rows > 1)
		{
			var maxFitStep = (parentHeight - footprintHeight) / (rows - 1);
			yStep = Mathf.Min(Mathf.Max(yStep, minYStep), maxFitStep);
		}
		else
		{
			yStep = Mathf.Max(yStep, minYStep);
		}
		step = new Vector2(xStep, yStep);
	}

	private static void LogQuickPlayActiveFactionGrid(RectTransform root, int buttonCount, string source)
	{
		if (_quickPlayFactionActiveLayoutLogged >= 40 || !root)
			return;
		_quickPlayFactionActiveLayoutLogged++;
		Homm3UiCardDiagnostics.Log(
			"quickplay-faction-grid-layout",
			"active-faction-grid-compacted",
			"source='" + (source ?? "?")
			+ "' root='" + DescribeRect(root)
			+ "' buttons=" + buttonCount
			+ " children=" + root.childCount
			+ " sample='" + SummarizeQuickPlayFactionGrid(root, 5) + "'",
			limit: 60);
	}

	private static string SummarizeQuickPlayFactionGrid(RectTransform root, int max)
	{
		if (!root)
			return "none";
		var parts = new List<string>();
		for (var i = 0; i < root.childCount && parts.Count < max; i++)
		{
			var child = root.GetChild(i)?.GetComponent<RectTransform>();
			if (!child || !HasComponentTypeName(child, "BhFactionSelectButton"))
				continue;
			if (!child.gameObject.activeSelf)
				continue;
			var button = GetBhFactionSelectButtonComponent(child);
			var moveRoot = GetMemberValue(button, "moveRoot") as RectTransform;
			TMPro.TMP_Text label = null;
			var texts = child.GetComponentsInChildren<TMPro.TMP_Text>(true);
			for (var j = 0; j < texts.Length; j++)
			{
				if (!IsSyntheticQuickPlayFactionLabel(texts[j]))
					continue;
				label = texts[j];
				break;
			}
			parts.Add(DescribeRect(child) + " moveRoot=" + DescribeRect(moveRoot) + " label=" + DescribeRect(label ? label.GetComponent<RectTransform>() : null));
		}
		return parts.Count == 0 ? "none" : string.Join(" || ", parts);
	}

	private static Component GetBhFactionSelectButtonComponent(Component owner)
	{
		if (!owner)
			return null;
		var components = owner.GetComponents<Component>();
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component)
				continue;
			var name = component.GetType().Name;
			var fullName = component.GetType().FullName ?? name;
			if (string.Equals(name, "BhFactionSelectButton", StringComparison.Ordinal) || fullName.EndsWith(".BhFactionSelectButton", StringComparison.Ordinal))
				return component;
		}
		return null;
	}

	private static void NormalizeQuickPlayFactionTileLabels(Component button)
	{
		if (!button)
			return;

		var texts = button.GetComponentsInChildren<TMPro.TMP_Text>(true);
		for (var i = 0; i < texts.Length; i++)
		{
			var text = texts[i];
			if (!text)
				continue;
			if (!IsSyntheticQuickPlayFactionLabel(text))
				continue;
			var source = FindFirstNonSyntheticText(button);
			if (!source || !source.GetComponent<RectTransform>())
			{
				text.enabled = false;
				text.gameObject.SetActive(false);
				Homm3UiCardDiagnostics.Log(
					"quickplay-faction-button-labels",
					"native-label-source-missing",
					"button='" + DescribeComponent(button) + "'",
					limit: 20);
				continue;
			}
			if (source)
			{
				text.font = source.font;
				text.fontSharedMaterial = source.fontSharedMaterial;
			}
			ConfigureQuickPlayFactionTileLabel(text, source);
			var parent = GetMemberValue(button, "moveRoot") as RectTransform;
			if (!parent)
				parent = button.transform as RectTransform;
			text.transform.SetParent(parent, false);
			text.transform.SetAsLastSibling();

			ApplyQuickPlayFactionTileLabelRect(text, source);
			HideQuickPlayNativeFactionLabelSource(source, text);
		}
	}

	private static void LogQuickPlayFactionButtonText(object instance, object title, string factionSid, string expectedName)
	{
		if (_quickPlayFactionTextLogged >= 80)
			return;
		_quickPlayFactionTextLogged++;
		var component = instance as Component;
		var titleComponent = title as Component;
		Homm3UiCardDiagnostics.Log(
			"quickplay-faction-button-labels",
			"faction-button-text",
			"faction='" + (factionSid ?? "?")
			+ "' expected='" + (expectedName ?? "?")
			+ "' button='" + DescribeComponent(component)
			+ "' title='" + DescribeComponent(titleComponent)
			+ "' titleTexts='" + SummarizeTextComponents(titleComponent, 6)
			+ "' buttonTexts='" + SummarizeTextComponents(component, 10)
			+ "'",
			limit: 100);
	}

	private static void LogQuickPlayFactionButtonBackground(object instance, string factionSid, Image background, string result)
	{
		if (_quickPlayFactionBackgroundLogged >= 40)
			return;
		_quickPlayFactionBackgroundLogged++;
		Homm3UiCardDiagnostics.Log(
			"quickplay-faction-button-backgrounds",
			"faction-button-background",
			"result='" + (result ?? "?")
			+ "' faction='" + (factionSid ?? "?")
			+ "' button='" + DescribeComponent(instance as Component)
			+ "' background=" + FormatImage(background),
			limit: 60);
	}

	private static void LogQuickPlayFactionDetailsLayout(RectTransform rect, string factionSid, string source, Vector2 original, float offsetX)
	{
		if (_quickPlayFactionDetailsLayoutLogged >= 40 || !rect)
			return;
		_quickPlayFactionDetailsLayoutLogged++;
		Homm3UiCardDiagnostics.Log(
			"quickplay-faction-details-layout",
			"details-panel-offset",
			"source='" + (source ?? "?")
			+ "' faction='" + (factionSid ?? "?")
			+ "' original=" + original
			+ " offsetX=" + offsetX.ToString("0.##")
			+ " rect='" + DescribeRect(rect)
			+ "' parent='" + DescribeRect(rect.parent as RectTransform)
			+ "'",
			limit: 60);
	}

	private static void LogQuickPlayFactionNativeListFallback(RectTransform parent, Component quickStart, int nativeCount, int resolvedCount)
	{
		if (_quickPlayFactionNativeListLogged >= 20)
			return;
		_quickPlayFactionNativeListLogged++;
		Homm3UiCardDiagnostics.Log(
			"quickplay-faction-grid-layout",
			"native-button-list-partial",
			"nativeCount=" + nativeCount
			+ " resolvedCount=" + resolvedCount
			+ " root='" + DescribeRect(parent)
			+ "' quickStart='" + DescribeQuickStartLayout(quickStart)
			+ "'",
			limit: 30);
	}

	private static void LogQuickPlayFactionButtonLayout(object instance, string factionSid, string source)
	{
		if (_quickPlayFactionLayoutLogged >= 80)
			return;
		if (instance is not Component component || !component)
			return;
		_quickPlayFactionLayoutLogged++;
		var rect = component.GetComponent<RectTransform>();
		var parent = rect && rect.parent ? rect.parent.GetComponent<RectTransform>() : null;
		var quickStart = FindAncestorComponentByTypeName(component.transform, "ScQuickStart", 12);
		Homm3UiCardDiagnostics.Log(
			"quickplay-faction-grid-layout",
			"faction-button-layout",
			"source='" + (source ?? "?")
			+ "' faction='" + (factionSid ?? "?")
			+ "' button='" + DescribeRect(rect)
			+ "' parent='" + DescribeRect(parent)
			+ "' parentLayout='" + DescribeLayout(parent)
			+ "' quickStart='" + DescribeQuickStartLayout(quickStart)
			+ "' ancestors='" + DescribeAncestors(component.transform, 7)
			+ "'",
			limit: 100);
	}

	private static string SummarizeTextComponents(Component root, int max)
	{
		if (!root)
			return "none";
		var parts = new List<string>();
		var tmpTexts = root.GetComponentsInChildren<TMPro.TMP_Text>(true);
		for (var i = 0; i < tmpTexts.Length && parts.Count < max; i++)
		{
			var text = tmpTexts[i];
			if (!text)
				continue;
			parts.Add(DescribeText(text));
		}
		var unityTexts = root.GetComponentsInChildren<Text>(true);
		for (var i = 0; i < unityTexts.Length && parts.Count < max; i++)
		{
			var text = unityTexts[i];
			if (!text)
				continue;
			parts.Add(DescribeText(text));
		}
		return parts.Count == 0 ? "none" : string.Join(" | ", parts);
	}

	private static string DescribeText(Component text)
	{
		if (!text)
			return "(null)";
		var value = text is TMPro.TMP_Text tmp
			? tmp.text
			: text is Text unityText ? unityText.text : "?";
		var graphic = text as Graphic;
		var rect = text.GetComponent<RectTransform>();
		return GetTransformPath(text.transform, null)
			+ ":text='" + (value ?? "")
			+ "' active=" + text.gameObject.activeInHierarchy
			+ " enabled=" + (graphic ? graphic.enabled.ToString() : "?")
			+ " color=" + (graphic ? graphic.color.ToString() : "?")
			+ " rect=" + DescribeRect(rect);
	}

	private static Component FindAncestorComponentByTypeName(Transform start, string typeName, int maxDepth)
	{
		var current = start;
		for (var depth = 0; current && depth <= maxDepth; depth++, current = current.parent)
		{
			var components = current.GetComponents<Component>();
			for (var i = 0; i < components.Length; i++)
			{
				var component = components[i];
				if (!component)
					continue;
				var name = component.GetType().Name;
				var fullName = component.GetType().FullName ?? name;
				if (string.Equals(name, typeName, StringComparison.Ordinal) || fullName.EndsWith("." + typeName, StringComparison.Ordinal))
					return component;
			}
		}
		return null;
	}

	private static bool HasComponentTypeName(Transform transform, string typeName)
	{
		if (!transform || string.IsNullOrEmpty(typeName))
			return false;
		var components = transform.GetComponents<Component>();
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component)
				continue;
			var name = component.GetType().Name;
			var fullName = component.GetType().FullName ?? name;
			if (string.Equals(name, typeName, StringComparison.Ordinal) || fullName.EndsWith("." + typeName, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static string DescribeQuickStartLayout(Component quickStart)
	{
		if (!quickStart)
			return "none";
		var root = GetMemberValue(quickStart, "factionsRoot") as RectTransform;
		var buttons = GetMemberValue(quickStart, "bslq");
		var spacing = GetMemberValue(quickStart, "factionButtonSpacing");
		var layoutMap = GetMemberValue(quickStart, "bsly");
		return DescribeComponent(quickStart)
			+ " factionsRoot=" + DescribeRect(root)
			+ " spacing=" + FormatSimple(spacing)
			+ " buttons=" + GetCount(buttons)
			+ " layoutMap=" + GetCount(layoutMap);
	}

	private static string DescribeLayout(RectTransform rect)
	{
		if (!rect)
			return "none";
		var horizontal = rect.GetComponent<HorizontalLayoutGroup>();
		if (horizontal)
			return "Horizontal spacing=" + horizontal.spacing
				+ " childExpandW=" + horizontal.childForceExpandWidth
				+ " childControlW=" + horizontal.childControlWidth;
		var grid = rect.GetComponent<GridLayoutGroup>();
		if (grid)
			return "Grid cell=" + grid.cellSize
				+ " spacing=" + grid.spacing
				+ " constraint=" + grid.constraint
				+ " count=" + grid.constraintCount;
		var vertical = rect.GetComponent<VerticalLayoutGroup>();
		if (vertical)
			return "Vertical spacing=" + vertical.spacing
				+ " childExpandH=" + vertical.childForceExpandHeight
				+ " childControlH=" + vertical.childControlHeight;
		var layout = rect.GetComponent<LayoutElement>();
		return layout ? "LayoutElement preferred=" + layout.preferredWidth + "x" + layout.preferredHeight : "none";
	}

	private static string DescribeRect(RectTransform rect)
	{
		if (!rect)
			return "null";
		return GetTransformPath(rect, null)
			+ " rect=" + rect.rect.width.ToString("0.##") + "x" + rect.rect.height.ToString("0.##")
			+ " sizeDelta=" + rect.sizeDelta
			+ " anchored=" + rect.anchoredPosition
			+ " localScale=" + rect.localScale
			+ " active=" + rect.gameObject.activeInHierarchy
			+ " sibling=" + rect.GetSiblingIndex() + "/" + (rect.parent ? rect.parent.childCount.ToString() : "?");
	}

	private static string DescribeAncestors(Transform start, int maxDepth)
	{
		if (!start)
			return "none";
		var parts = new List<string>();
		var current = start;
		for (var depth = 0; current && depth < maxDepth; depth++, current = current.parent)
			parts.Add(current.name + "{" + DescribeLayout(current as RectTransform) + "}");
		return string.Join(" <- ", parts);
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

	private static string DescribeComponent(Component component)
	{
		return component ? (component.name ?? "?") + "/" + (component.GetType().FullName ?? component.GetType().Name) : "null";
	}

	private static void ClearStrongholdSpriteOverride(Image image)
	{
		if (image == null)
			return;
		if (Homm3StrongholdFactionBannerSpriteCache.IsHomm3FactionSprite(image.overrideSprite))
			image.overrideSprite = null;
		if (Homm3StrongholdFactionBannerSpriteCache.IsHomm3FactionSprite(image.sprite))
			image.sprite = null;
	}

	private static void ClearHomm3PortraitSpriteOverride(Image image)
	{
		if (image == null)
			return;
		if (Homm3ImportPortraitSpriteCache.IsHomm3PortraitSprite(image.overrideSprite))
			image.overrideSprite = null;
		if (Homm3ImportPortraitSpriteCache.IsHomm3PortraitSprite(image.sprite))
			image.sprite = null;
	}

	private static bool IsHomm3UnitSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid) && sid.Trim().StartsWith("h3_", StringComparison.OrdinalIgnoreCase);
	}

	private static void PrefixStrongholdFractionElement(ref string a, ref Sprite b)
	{
		var factionSid = IsHomm3LobbyFactionSid(a) ? a : null;
		if (factionSid == null && _translateDungeonSelectionToStronghold && string.Equals(a, "dungeon", StringComparison.OrdinalIgnoreCase))
			factionSid = "homm3_stronghold";
		if (factionSid == null)
			return;
		if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) && banner)
			b = banner;
	}

	private static void PostfixStrongholdHeroElement(object __instance, object[] __args)
	{
		var sid = ArgString(__args, 0);
		if (!IsCustomHeroSid(sid))
			return;

		ApplyHomm3HeroPortraitToRow(__instance, sid, "BhHero");
	}

	private static void ApplyHomm3HeroPortraitToRow(object row, string heroSid, string source)
	{
		ApplyHomm3HeroPortraitToSurface(
			row,
			heroSid,
			source,
			new[] { "icon", "portrait" },
			new[] { "randomIcon", "random", "shadow" },
			allowDescendantFallback: true);
	}

	private static void ApplyHomm3PickHeroDetailsSpecializationIcon(object details, object heroConfig, string heroSid, string source)
	{
		try
		{
			Homm3HeroSpecializationIconUi.TryApplyForHeroConfig(
				heroConfig,
				heroSid,
				details,
				"quickplay-hero-specialization-icon");
		}
		catch (Exception ex)
		{
			Homm3UiCardDiagnostics.Log(
				"quickplay-hero-specialization-icon",
				"details-specialization-icon-failed",
				"source='" + (source ?? "?") + "' error='" + ex.GetType().Name + ": " + ex.Message + "'",
				limit: 24);
		}
	}

	private static int PatchSummaryCardHeroBinds(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		foreach (var methodName in GameSymbols.ImportVisuals.SummaryCardHeroBind.NameHints)
		{
			patched += PatchByAnyName(
				h,
				log,
				"Hex.Pick.BhSummaryCard",
				new[] { methodName },
				1,
				postfixName: nameof(PostfixSummaryCardHeroBind));
			patched += PatchByAnyName(
				h,
				log,
				"Hex.Pick.BhSummaryCard",
				new[] { methodName },
				2,
				postfixName: nameof(PostfixSummaryCardHeroBind));
		}
		return patched;
	}

	private static void PostfixSummaryCardHeroBind(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var heroConfig = Arg(__args, 0);
		var heroSid = GetHomm3HeroSidFromConfig(heroConfig);
		if (heroSid == null)
			return;
		ApplyHomm3HeroDisplayNameText(__instance, heroSid, "BhSummaryCard." + (__originalMethod?.Name ?? "?"));
		Homm3HeroSpecializationIconUi.TryApplyForHeroConfigTree(
			heroConfig,
			heroSid,
			__instance,
			"quickplay-summary-specialization-icon");
	}

	private static void PostfixHomm3PickSkillView(object __instance, object[] __args, MethodBase __originalMethod)
	{
		var skillParameter = Arg(__args, 0);
		var iconKey = FormatSimple(GetMemberValue(skillParameter, GameSymbols.CustomGame.SkillParameterIconFields));
		if (!Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(iconKey))
			return;
		if (!Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(iconKey, out var sprite) || !sprite)
		{
			LogPickSkillIcon("no-sprite", iconKey, __originalMethod, "sprite cache miss");
			return;
		}

		var icon = GetMemberValue(__instance, GameSymbols.CustomGame.SkillViewSkillIconFields);
		if (!TrySetBhIconSprite(icon, sprite, out var reason))
		{
			LogPickSkillIcon("no-sprite-surface", iconKey, __originalMethod, reason);
			return;
		}

		LogPickSkillIcon("applied", iconKey, __originalMethod, "sprite='" + sprite.name + "'");
	}

	private static Image FindFirstImageByName(Component root, string imageName)
	{
		if (!root || string.IsNullOrWhiteSpace(imageName))
			return null;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image && image.gameObject && string.Equals(image.gameObject.name, imageName, StringComparison.OrdinalIgnoreCase))
				return image;
		}
		return null;
	}

	private static void ApplyHomm3HeroPortraitToSurface(object row, string heroSid, string source, string[] imageFields, string[] overlayFields, bool allowDescendantFallback)
	{
		try
		{
			if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(heroSid, out var sprite) || !sprite)
				return;

			Image image = null;
			if (imageFields != null)
			{
				for (var i = 0; i < imageFields.Length && image == null; i++)
					image = GetMemberValue(row, imageFields[i]) as Image;
			}
			if (image == null && allowDescendantFallback && row is Component component)
				image = component.GetComponentInChildren<Image>(true);
			if (image == null && allowDescendantFallback && row is GameObject gameObject)
				image = gameObject.GetComponentInChildren<Image>(true);
			if (image == null)
				return;

			ApplySpriteToImage(image, sprite);
			if (overlayFields != null)
			{
				for (var i = 0; i < overlayFields.Length; i++)
					DisableGraphic(GetMemberValue(row, overlayFields[i]));
			}

			if (_strongholdHeroIconLogged < 24)
			{
				_strongholdHeroIconLogged++;
				LogInfo("ReleaseCustomGameUiProbe: applied HoMM3 picker hero icon source=" + source + " sid=" + heroSid + " image=" + image.name + " sprite=" + sprite.name + ".");
			}
		}
		catch (Exception ex)
		{
			if (_strongholdHeroIconLogged < 24)
			{
				_strongholdHeroIconLogged++;
				LogInfo("ReleaseCustomGameUiProbe: failed HoMM3 picker hero icon source=" + source + " sid=" + heroSid + ": " + ex.Message);
			}
		}
	}

	private static void PrefixLobbyHeroCurrent(object __instance, object[] __args)
	{
		LogLobby(
			"HeroCurrent",
			"sid=" + ArgString(__args, 0)
			+ " interactable=" + ArgString(__args, 1)
			+ " locked=" + ArgString(__args, 2)
			+ " | " + SummarizeLobbySelection(__instance));
	}

	private static void PrefixLobbyHeroSelected(object __instance, object[] __args)
	{
		LogLobby("HeroSelected", "sid=" + ArgString(__args, 0) + " | " + SummarizeLobbySelection(__instance));
	}

	private static void PrefixLobbyHeroElement(object __instance, object[] __args)
	{
		LogLobby(
			"HeroElement",
			"sid=" + ArgString(__args, 0)
			+ " interactable=" + ArgString(__args, 1)
			+ " locked=" + ArgString(__args, 2)
			+ " | " + SummarizeLobbySelection(__instance));
	}

	private static bool IsCustomHeroSid(string sid)
	{
		return Homm3CustomFactionRegistry.IsCustomHeroSid(sid);
	}

	private static void PrefixLobbyElementClick(object __instance)
	{
		LogLobby("ElementClick", SummarizeLobbySelection(__instance));
	}

	private static void LogLobby(string tag, string message)
	{
		if (_lobbyLogged >= 180)
			return;
		_lobbyLogged++;
		LogInfo("[RCG.Lobby." + tag + " #" + _lobbyLogged + "] " + message);
	}

	private static string TryInjectFactionOption(object result, string factionSid)
	{
		try
		{
			var list = result as Il2CppSystem.Collections.Generic.List<FractionLobbyAsset>;
			if (list == null)
				return "skip:list-type=" + FormatType(result);

			FractionLobbyAsset dungeon = null;
			for (var i = 0; i < list.Count; i++)
			{
				var asset = list[i];
				if (asset == null)
					continue;
				if (string.Equals(DeobfInteropCompat.GetFractionLobbyAssetSid(asset), factionSid, StringComparison.OrdinalIgnoreCase))
				{
					var repaired = ApplyHomm3FactionAssetArt(asset, factionSid);
					return "present:repaired=" + repaired;
				}
				if (string.Equals(DeobfInteropCompat.GetFractionLobbyAssetSid(asset), "dungeon", StringComparison.OrdinalIgnoreCase))
					dungeon = asset;
			}

			if (dungeon == null)
				return "skip:no-dungeon-asset";

			var clone = new FractionLobbyAsset
			{
				icon = dungeon.icon,
				slotFon = dungeon.slotFon,
				statisticFon = dungeon.statisticFon,
				versusFon = dungeon.versusFon,
				bigIcon = dungeon.bigIcon
			};
			DeobfInteropCompat.SetFractionLobbyAssetSid(clone, factionSid);
			var donorCard = DeobfInteropCompat.GetFractionLobbyAssetCard(dungeon);
			if (donorCard)
				DeobfInteropCompat.SetFractionLobbyAssetCard(clone, donorCard);

			var customBanner = false;
			customBanner = ApplyHomm3FactionAssetArt(clone, factionSid);

			list.Add(clone);
			_translateDungeonSelectionToStronghold = false;
			if (_loggedFactionInjected.Add(factionSid))
			{
				LogInfo("ReleaseCustomGameUiProbe: appended " + factionSid + " to ScFractionSelect.qvl() using Dungeon layout assets and custom banner.");
			}
			return "added:customBanner=" + customBanner + ":translateSelection=False";
		}
		catch (Exception ex)
		{
			return "error:" + ex.Message;
		}
	}

	private static bool ApplyHomm3FactionAssetArt(FractionLobbyAsset asset, string factionSid)
	{
		if (asset == null)
			return false;
		var applied = false;
		if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) && banner)
		{
			asset.icon = banner;
			asset.bigIcon = banner;
			applied = true;
		}
		if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateCardSpriteForFaction(factionSid, out var card) && card)
		{
			DeobfInteropCompat.SetFractionLobbyAssetCard(asset, card);
			asset.slotFon = card;
			asset.statisticFon = card;
			asset.versusFon = card;
			applied = true;
		}
		return applied;
	}

	private static bool IsStrongholdFractionConfig(object fractionConfig)
	{
		return string.Equals(GetHomm3FactionSidFromConfig(fractionConfig), "homm3_stronghold", StringComparison.OrdinalIgnoreCase);
	}

	private static string GetHomm3FactionSidFromConfig(object fractionConfig)
	{
		if (fractionConfig == null)
			return null;

		var sid = FirstNonEmpty(fractionConfig, "id", "sid", "fractionSid", "name", "title");
		if (Homm3CustomFactionRegistry.IsCustomFactionNameToken(sid, out var factionSid)
			&& IsHomm3LobbyFactionSid(factionSid))
			return factionSid;

		var icon = FirstNonEmpty(fractionConfig, "icon", "smallIcon", "bigIcon", "card");
		if (Homm3CustomFactionRegistry.TryGetFactionSidForCityIconKey(icon, out var iconFactionSid)
			&& IsHomm3LobbyFactionSid(iconFactionSid))
			return iconFactionSid;
		if (Homm3CustomFactionRegistry.TryGetFactionSpriteAssetByKey(icon, out var spriteFactionSid, out _)
			&& IsHomm3LobbyFactionSid(spriteFactionSid))
			return spriteFactionSid;
		return null;
	}

	private static string GetHomm3HeroSidFromConfig(object heroConfig)
	{
		if (heroConfig == null)
			return null;

		var sid = FirstNonEmpty(heroConfig, "id", "sid", "heroSid", "configSid", "name", "title", "icon", "portrait");
		if (Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(sid, out var portraitKey))
			return portraitKey;
		if (Homm3CustomFactionRegistry.TryGetHeroSidFromDisplayLabel(sid, out var displayHeroSid))
			return displayHeroSid;

		var config = GetMemberValue(heroConfig, "config", "heroConfig");
		if (config != null && !ReferenceEquals(config, heroConfig))
			return GetHomm3HeroSidFromConfig(config);

		return null;
	}

	private static bool IsHomm3LobbyFactionSid(string sid)
	{
		return Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(sid);
	}

	private static string GetHomm3FactionName(string factionSid)
	{
		return Homm3CustomFactionRegistry.TryGetFactionDisplayText(factionSid, out var name, out _) ? name : null;
	}

	private static string GetHomm3FactionTileName(string factionSid)
	{
		var name = GetHomm3FactionName(factionSid);
		if (string.IsNullOrWhiteSpace(name))
			return null;
		const string suffix = " (HoMM3)";
		return name.EndsWith(suffix, StringComparison.Ordinal) ? name[..^suffix.Length] : name;
	}

	private static string GetHomm3FactionDescription(string factionSid)
	{
		return Homm3CustomFactionRegistry.TryGetFactionDisplayText(factionSid, out _, out var description) ? description : null;
	}

	private static bool TranslateStrongholdFactionSid(ref string sid, string source)
	{
		if (!_translateDungeonSelectionToStronghold || !string.Equals(sid, "dungeon", StringComparison.OrdinalIgnoreCase))
			return false;

		sid = "homm3_stronghold";
		if (_lobbyLogged < 180)
			LogLobby("FractionTranslate", "source=" + source + " dungeon->homm3_stronghold");
		return true;
	}

	private static string SummarizeLobbySelection(object instance)
	{
		if (instance == null)
			return "selection=null";

		var currentFraction = GetMemberValue(instance, "currentFraction");
		var currentHero = GetMemberValue(instance, "currentHero");
		return "type=" + FormatType(instance)
			+ " fractionSid=" + FormatSimple(GetMemberValue(instance, "fractionSid"))
			+ " heroSid=" + FormatSimple(GetMemberValue(instance, "cmxe", "bwum", "heroSid"))
			+ " currentFraction=" + FormatSimple(GetMemberValue(currentFraction, "fractionSid"))
			+ " currentHero=" + FormatSimple(GetMemberValue(currentHero, "cmxe", "bwum", "heroSid"));
	}

	private static string SummarizePickView(object instance)
	{
		try
		{
			if (instance == null)
				return "view=null";

			var logic = GetMemberValue(instance, "bsxj", "bskj", "logic");
			if (logic == null)
				return "logic=null state=" + FormatUiState(GetMemberValue(instance, "bsxn", "bskn", "lastState"));

			var factions = GetMemberValue(logic, "Factions");
			var heroes = GetMemberValue(logic, "Heroes");
			var choices = GetMemberValue(logic, "Choices");
			var startInfo = GetMemberValue(logic, "StartInfo");
			var currentStage = GetMemberValue(logic, "CurrentStage");
			var state = GetMemberValue(instance, "bsxn", "bskn", "lastState");
			var mySide = GetMemberValue(startInfo, "mySide");
			return "state=" + FormatUiState(state)
				+ " stage=" + FormatSimple(currentStage)
				+ " mySide=" + FormatSimple(mySide)
				+ " selectedMap=" + FormatSimple(GetMemberValue(logic, "SelectedMap"))
				+ " factions=" + FormatListSummary(factions, 12)
				+ " heroBuckets=" + FormatHeroBuckets(heroes)
				+ " choices=" + FormatChoices(choices);
		}
		catch (Exception ex)
		{
			return "summarize-failed:" + ex.Message;
		}
	}

	private static string FormatUiState(object state)
	{
		if (state == null)
			return "null";
		return "type=" + FormatSimple(GetMemberValue(state, "type"))
			+ ",isBan=" + FormatSimple(GetMemberValue(state, "isBan"))
			+ ",prompt=" + FormatSimple(GetMemberValue(state, "prompt"))
			+ ",progress=" + FormatSimple(GetMemberValue(state, "progressLineIndex"))
			+ ",count=" + FormatSimple(GetMemberValue(state, "promptNum")) + "/" + FormatSimple(GetMemberValue(state, "promptDenum"));
	}

	private static string FormatChoices(object choices)
	{
		var count = GetCount(choices);
		if (count <= 0)
			return "count=" + count;

		var parts = new List<string>();
		for (var i = 0; i < count && i < 4; i++)
		{
			var choice = GetIndexedValue(choices, i);
			parts.Add(
				i + ":{map=" + FormatSimple(GetMemberValue(choice, "mapPick"))
				+ ",faction=" + FormatSimple(GetMemberValue(choice, "factionPick"))
				+ ",hero=" + FormatSimple(GetMemberValue(choice, "heroPick")) + "}");
		}
		return "[" + string.Join(",", parts) + "]";
	}

	private static string FormatHeroBuckets(object buckets)
	{
		var count = GetCount(buckets);
		if (count <= 0)
			return "count=" + count;

		var parts = new List<string>();
		for (var i = 0; i < count && i < 12; i++)
		{
			var list = GetIndexedValue(buckets, i);
			parts.Add(i + ":" + GetCount(list));
		}
		if (count > 12)
			parts.Add("+" + (count - 12));
		return "[" + string.Join(",", parts) + "]";
	}

	private static string FormatListSummary(object list, int maxItems)
	{
		var count = GetCount(list);
		if (count < 0)
			return "count=" + count + " type=" + FormatType(list);

		var parts = new List<string>();
		for (var i = 0; i < count && i < maxItems; i++)
		{
			parts.Add(FormatConfigOrInfo(GetIndexedValue(list, i)));
		}
		if (count > maxItems)
			parts.Add("+" + (count - maxItems));
		return "count=" + count + " [" + string.Join(",", parts) + "]";
	}

	private static string FormatConfigOrInfo(object value)
	{
		if (value == null)
			return "null";

		var config = GetMemberValue(value, "config");
		if (config != null)
			return FormatConfig(config) + "/available=" + FormatSimple(GetMemberValue(value, "isAvailable"));

		return FormatConfig(value);
	}

	private static string FormatConfig(object config)
	{
		if (config == null)
			return "null";

		var sid = FirstNonEmpty(config, "sid", "id", "name", "title");
		var icon = FirstNonEmpty(config, "icon", "smallIcon", "portrait", "bigIcon");
		var type = FormatType(config);
		if (string.IsNullOrEmpty(icon))
			return sid + "(" + type + ")";
		return sid + "(" + type + ",icon=" + icon + ")";
	}

	private static string FirstNonEmpty(object value, params string[] names)
	{
		foreach (var name in names)
		{
			var member = GetMemberValue(value, name);
			var s = FormatSimple(member);
			if (!string.IsNullOrEmpty(s) && s != "?")
				return s;
		}
		return "?";
	}

	private static object GetMemberValue(object value, params string[] names)
	{
		if (value == null)
			return null;

		var type = value.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;

			var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (prop != null && prop.GetIndexParameters().Length == 0)
			{
				try { return prop.GetValue(value); }
				catch { }
			}

			var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (field != null)
			{
				try { return field.GetValue(value); }
				catch { }
			}

			var getter = type.GetMethod("get_" + name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, Type.EmptyTypes, null);
			if (getter != null)
			{
				try { return getter.Invoke(value, Array.Empty<object>()); }
				catch { }
			}
		}

		return null;
	}

	private static bool SetMemberValue(object value, object newValue, params string[] names)
	{
		if (value == null)
			return false;

		var type = value.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;

			var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (prop != null && prop.GetIndexParameters().Length == 0 && prop.CanWrite)
			{
				try
				{
					prop.SetValue(value, newValue);
					return true;
				}
				catch { }
			}

			var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static);
			if (field != null)
			{
				try
				{
					field.SetValue(value, newValue);
					return true;
				}
				catch { }
			}

			var setter = type.GetMethod("set_" + name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static, null, new[] { newValue?.GetType() ?? typeof(object) }, null);
			if (setter != null)
			{
				try
				{
					setter.Invoke(value, new[] { newValue });
					return true;
				}
				catch { }
			}
		}

		return false;
	}

	private static int GetCount(object value)
	{
		if (value == null)
			return -1;
		if (value is Array array)
			return array.Length;
		if (value is ICollection collection)
			return collection.Count;

		var count = GetMemberValue(value, "Count", "Length");
		if (count is int i)
			return i;
		if (count != null && int.TryParse(Convert.ToString(count), out var parsed))
			return parsed;
		return -1;
	}

	private static object GetIndexedValue(object value, int index)
	{
		if (value == null)
			return null;
		if (value is Array array)
			return index >= 0 && index < array.Length ? array.GetValue(index) : null;
		if (value is IList list)
			return index >= 0 && index < list.Count ? list[index] : null;

		var type = value.GetType();
		var getItem = type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, new[] { typeof(int) }, null);
		if (getItem != null)
		{
			try { return getItem.Invoke(value, new object[] { index }); }
			catch { }
		}

		foreach (var prop in type.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			var parameters = prop.GetIndexParameters();
			if (parameters.Length == 1 && parameters[0].ParameterType == typeof(int))
			{
				try { return prop.GetValue(value, new object[] { index }); }
				catch { }
			}
		}

		return null;
	}

	private static object Arg(object[] args, int index)
	{
		return args != null && index >= 0 && index < args.Length ? args[index] : null;
	}

	private static string ArgString(object[] args, int index)
	{
		return FormatSimple(Arg(args, index));
	}

	private static string FormatSimple(object value)
	{
		if (value == null)
			return "?";
		try
		{
			return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "?";
		}
		catch
		{
			return value.ToString() ?? "?";
		}
	}

	private static string FormatType(object value)
	{
		return value == null ? "null" : (value.GetType().FullName ?? value.GetType().Name);
	}

	private static string FormatImage(Image image)
	{
		if (image == null)
			return "null";
		var sprite = image.sprite ? image.sprite.name : "null";
		var overrideSprite = image.overrideSprite ? image.overrideSprite.name : "null";
		var name = image.gameObject ? image.gameObject.name : "?";
		return "'" + name + "' sprite='" + sprite + "' override='" + overrideSprite + "' enabled=" + image.enabled;
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

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "?";
		var parameters = method.GetParameters();
		var parts = new string[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
			parts[i] = parameters[i].ParameterType.Name + " " + parameters[i].Name;
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name + "(" + string.Join(", ", parts) + ")";
	}

	private static void LogCandidates(Type type, ManualLogSource log)
	{
		if (type == null || log == null)
			return;

		try
		{
			var logged = 0;
			var methods = new List<MethodInfo>(type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly));
			methods.Sort((a, b) => string.CompareOrdinal(a?.Name, b?.Name));
			foreach (var method in methods)
			{
				if (method == null || method.Name.StartsWith("get_", StringComparison.Ordinal) || method.Name.StartsWith("set_", StringComparison.Ordinal))
					continue;
				if (logged >= 35)
					break;
				logged++;
				log.LogInfo("ReleaseCustomGameUiProbe diag: candidate " + FormatMethod(method) + " returns " + (method.ReturnType?.FullName ?? "?") + ".");
			}
			log.LogInfo("ReleaseCustomGameUiProbe diag: type " + (type.FullName ?? type.Name) + " methodCount logged=" + logged + ".");
		}
		catch (Exception ex)
		{
			log.LogWarning("ReleaseCustomGameUiProbe diag: candidate dump failed: " + ex.Message);
		}
	}

	private static void LogInfo(string line)
	{
		_log?.LogInfo(line);
	}

	private static void LogPickSkillIcon(string evt, string iconKey, MethodBase method, string detail)
	{
		Homm3UiCardDiagnostics.Log(
			"custom-game-skill-icon",
			evt,
			"source='" + (method?.DeclaringType?.FullName ?? "?") + "." + (method?.Name ?? "?") + "' icon='" + (iconKey ?? "?") + "' " + (detail ?? string.Empty),
			limit: 48);
		if (_pickSkillIconLogged >= 24 || !string.Equals(evt, "no-sprite-surface", StringComparison.Ordinal))
			return;
		_pickSkillIconLogged++;
		LogInfo("ReleaseCustomGameUiProbe: custom skill icon failed source=" + (method?.Name ?? "?") + " icon=" + (iconKey ?? "?") + " reason=" + (detail ?? "?") + ".");
	}

	private static void LogPickUnitPortrait(string line)
	{
		Homm3UiCardDiagnostics.Log("custom-game-faction-hover-unit-card-portraits", "pick-unit-portrait", line);
		if (_pickUnitPortraitLogged >= 80)
			return;
		_pickUnitPortraitLogged++;
		LogInfo("ReleaseCustomGameUiProbe pick portrait: " + line);
	}
}
