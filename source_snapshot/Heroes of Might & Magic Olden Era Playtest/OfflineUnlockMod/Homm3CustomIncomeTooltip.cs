using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Hud;
using Hex.UI.Tooltips;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Adds the mod's custom daily gold (Swashbucklers, War Captives enslaved gold, Tower Artificing grafts; anything
/// registered through <see cref="Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroForecast"/>) to the adventure-map
/// gold hover on the adventure-map resource bar. That hover is Hex.Session.Hud.BhResElement.OnPointerEnter, which hands
/// the resource's text to BhTooltips' string tooltip; the string-tooltip body that fills BhTooltipIncomeRes.main is
/// inlined there (Ghidra 26615913: BhTooltips$$wcg repeats BhTooltipIncomeRes$$wah), so patching BhTooltipIncomeRes's
/// own methods never fired. The postfix runs after OnPointerEnter, appends a marked block to BhTooltips.incomeRes.main
/// when the hovered element is gold, and rebuilds the tooltip layout before its deferred snap. The first hovers are
/// logged (icon sprite + text) until the in-game shape is proven.
/// </summary>
internal static class Homm3CustomIncomeTooltip
{
	private const string LogPrefix = "HoMM3 custom income tooltip: ";
	// Zero-width marker so a re-run postfix replaces its own block instead of stacking a second one.
	private const string BlockMarker = "​‌";
	private const int ProbeLogLimit = 12;

	private static ManualLogSource _log;
	private static bool _registered;
	private static int _probeLogs;
	private static int _failLogs;

	internal static bool IsRegistered => _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		_log = log;
		if (_registered || harmony == null)
			return;
		try
		{
			var method = typeof(BhResElement).GetMethod(nameof(BhResElement.OnPointerEnter), BindingFlags.Public | BindingFlags.Instance, null, new[] { typeof(PointerEventData) }, null);
			if (method == null)
			{
				_log?.LogWarning(LogPrefix + "NOT registered: BhResElement.OnPointerEnter(PointerEventData) not found.");
				return;
			}
			harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3CustomIncomeTooltip), nameof(Postfix)));
			_registered = true;
			_log?.LogInfo(LogPrefix + "registered on BhResElement.OnPointerEnter (resource-bar hover).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "NOT registered: " + ex.GetBaseException().Message);
		}
	}

	private static void Postfix(BhResElement __instance)
	{
		try
		{
			var tooltip = BhTooltips.field_Private_Static_BhTooltips_0?.incomeRes;
			var main = tooltip?.main;
			if (__instance == null || main == null)
				return;
			var text = StripBlock(main.text ?? "");
			var icon = SafeSpriteName(__instance);
			var aboutGold = icon.IndexOf("gold", StringComparison.OrdinalIgnoreCase) >= 0
			                || text.IndexOf("gold", StringComparison.OrdinalIgnoreCase) >= 0;
			if (_probeLogs < ProbeLogLimit)
			{
				_probeLogs++;
				_log?.LogInfo(LogPrefix + "probe hover icon='" + icon + "' gold=" + aboutGold + " main='" + Flatten(text) + "'.");
			}
			if (!aboutGold)
				return;
			string block = null;
			if (Homm3SwashbucklerGoldHook.TryForecastLocalCustomGold(out var lines, out var failure))
			{
				if (lines.Count > 0)
				{
					var total = 0L;
					foreach (var (_, gold) in lines)
						total += gold;
					var sb = new StringBuilder();
					sb.Append(BlockMarker).Append('\n').Append("Custom daily gold: +").Append(N(total));
					foreach (var (label, gold) in lines)
						sb.Append('\n').Append("  ").Append(label).Append(": +").Append(N(gold));
					block = sb.ToString();
				}
			}
			else if (_failLogs < 4)
			{
				_failLogs++;
				_log?.LogInfo(LogPrefix + "no forecast: " + failure + ".");
			}
			var updated = block == null ? text : text + block;
			if (!string.Equals(updated, main.text, StringComparison.Ordinal))
			{
				main.text = updated;
				var rect = tooltip.transform.TryCast<RectTransform>();
				if (rect != null)
					LayoutRebuilder.ForceRebuildLayoutImmediate(rect);
			}
		}
		catch (Exception ex)
		{
			if (_failLogs++ < 8)
				_log?.LogWarning(LogPrefix + "postfix failed: " + ex.GetBaseException().Message);
		}
	}

	private static string StripBlock(string text)
	{
		var at = text.IndexOf(BlockMarker, StringComparison.Ordinal);
		return at < 0 ? text : text.Substring(0, at);
	}

	private static string SafeSpriteName(BhResElement element)
	{
		try
		{
			var sprite = element.icon != null ? element.icon.sprite : null;
			return sprite != null ? sprite.name ?? "" : "";
		}
		catch
		{
			return "";
		}
	}

	private static string Flatten(string text)
	{
		if (string.IsNullOrEmpty(text))
			return "";
		var flat = text.Replace("\r", "").Replace("\n", " | ");
		return flat.Length <= 300 ? flat : flat.Substring(0, 300) + "...";
	}

	private static string N(long value) => value.ToString("N0", CultureInfo.InvariantCulture);
}
