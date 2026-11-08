using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

internal static class Homm3UiCardDiagnostics
{
	internal const string GrepKey = "HOMM3_UI_CARD_DIAG";
	private const int DefaultLimit = 120;
	private static readonly Dictionary<string, int> Counts = new(StringComparer.Ordinal);

	internal static void Log(string surface, string evt, string detail, int limit = DefaultLimit)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_ui_icon_diag.flag"))
			return;
		if (string.IsNullOrWhiteSpace(surface))
			surface = "unknown";
		if (string.IsNullOrWhiteSpace(evt))
			evt = "event";
		var key = surface + ":" + evt;
		Counts.TryGetValue(key, out var count);
		if (count >= limit)
			return;
		Counts[key] = count + 1;
		Plugin.LogSource?.LogInfo(
			GrepKey
			+ " surface="
			+ Clean(surface)
			+ " event="
			+ Clean(evt)
			+ " "
			+ Clean(detail));
	}

	private static string Clean(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "?";
		return value.Replace('\r', ' ').Replace('\n', ' ').Trim();
	}
}
