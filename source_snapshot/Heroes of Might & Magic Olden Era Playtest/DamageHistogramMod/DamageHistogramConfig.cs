using System;
using System.IO;
using BepInEx;

namespace OfflineUnlockMod;

internal sealed class LauncherConfig
{
	public bool DamageHistograms = true;
	public int DamageHistogramConvolutionMaxUnits = 120;
	public int DamageHistogramChartWidthPx = 275;
	public int DamageHistogramChartHeightPx = 144;
	public int DamageHistogramGapPx = 12;
	public bool DamageHistogramUseNativeFrameSprite = false;
	public bool DamageHistogramPanelUgui = false;
	public int DamageHistogramPanelUguiLayoutPercent = 120;
	public int DamageHistogramPanelUguiEdgeFeatherPx = 40;
	public int DamageHistogramFontScalePercent = 100;
	public int DamageHistogramMinBars = 0;
}

internal static class LauncherConfigReader
{
	private const string ModFolderName = "DamageHistogramMod";
	private const string ModSettingsFileName = "config.json";

	private static LauncherConfig s_cached;
	private static DateTime s_cachedWriteUtc;
	private static string s_cachedPath;
	private static int s_loadGeneration;

	internal static int LoadGeneration => s_loadGeneration;
	internal static string LastResolvedModSettingsPath => s_cachedPath;

	internal static LauncherConfig TryLoad()
	{
		var path = GetCanonicalModSettingsPath();
		try
		{
			var writeUtc = File.Exists(path) ? File.GetLastWriteTimeUtc(path) : DateTime.MinValue;
			if (s_cached != null && string.Equals(s_cachedPath, path, StringComparison.OrdinalIgnoreCase) && writeUtc == s_cachedWriteUtc)
			{
				return s_cached;
			}

			LauncherConfig cfg;
			if (File.Exists(path))
			{
				cfg = ParseConfig(File.ReadAllText(path));
			}
			else
			{
				cfg = new LauncherConfig();
				WriteDefaultConfig(path, cfg);
				writeUtc = File.GetLastWriteTimeUtc(path);
			}

			s_cached = cfg;
			s_cachedPath = path;
			s_cachedWriteUtc = writeUtc;
			s_loadGeneration++;
			return s_cached;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Damage histogram config load failed: " + ex.Message);
			s_cached = new LauncherConfig();
			s_cachedPath = path;
			s_cachedWriteUtc = DateTime.MinValue;
			s_loadGeneration++;
			return s_cached;
		}
	}

	internal static void InvalidateCache()
	{
		s_cached = null;
		s_cachedWriteUtc = DateTime.MinValue;
		s_loadGeneration++;
	}

	internal static string GetCanonicalModSettingsPath()
	{
		var pluginPath = Paths.PluginPath;
		if (string.IsNullOrEmpty(pluginPath))
		{
			pluginPath = Path.Combine(Paths.BepInExRootPath, "plugins");
		}
		return Path.GetFullPath(Path.Combine(pluginPath, ModFolderName, ModSettingsFileName));
	}

	private static void WriteDefaultConfig(string path, LauncherConfig cfg)
	{
		var dir = Path.GetDirectoryName(path);
		if (!string.IsNullOrEmpty(dir))
		{
			Directory.CreateDirectory(dir);
		}

		File.WriteAllText(path,
			"{\n"
			+ "  \"DamageHistograms\": " + (cfg.DamageHistograms ? "true" : "false") + ",\n"
			+ "  \"DamageHistogramConvolutionMaxUnits\": " + cfg.DamageHistogramConvolutionMaxUnits + ",\n"
			+ "  \"DamageHistogramChartWidthPx\": " + cfg.DamageHistogramChartWidthPx + ",\n"
			+ "  \"DamageHistogramChartHeightPx\": " + cfg.DamageHistogramChartHeightPx + ",\n"
			+ "  \"DamageHistogramGapPx\": " + cfg.DamageHistogramGapPx + ",\n"
			+ "  \"DamageHistogramUseNativeFrameSprite\": " + (cfg.DamageHistogramUseNativeFrameSprite ? "true" : "false") + ",\n"
			+ "  \"DamageHistogramPanelUgui\": " + (cfg.DamageHistogramPanelUgui ? "true" : "false") + ",\n"
			+ "  \"DamageHistogramPanelUguiLayoutPercent\": " + cfg.DamageHistogramPanelUguiLayoutPercent + ",\n"
			+ "  \"DamageHistogramPanelUguiEdgeFeatherPx\": " + cfg.DamageHistogramPanelUguiEdgeFeatherPx + ",\n"
			+ "  \"DamageHistogramFontScalePercent\": " + cfg.DamageHistogramFontScalePercent + ",\n"
			+ "  \"DamageHistogramMinBars\": " + cfg.DamageHistogramMinBars + "\n"
			+ "}\n");
	}

	private static LauncherConfig ParseConfig(string text)
	{
		var cfg = new LauncherConfig();
		if (string.IsNullOrEmpty(text))
		{
			return cfg;
		}

		cfg.DamageHistograms = ReadBool(text, "DamageHistograms", ReadBool(text, "damageHistograms", cfg.DamageHistograms));
		cfg.DamageHistogramConvolutionMaxUnits = ReadInt(text, "DamageHistogramConvolutionMaxUnits", ReadInt(text, "damageHistogramConvolutionMaxUnits", cfg.DamageHistogramConvolutionMaxUnits));
		cfg.DamageHistogramChartWidthPx = ReadInt(text, "DamageHistogramChartWidthPx", ReadInt(text, "damageHistogramChartWidthPx", cfg.DamageHistogramChartWidthPx));
		cfg.DamageHistogramChartHeightPx = ReadInt(text, "DamageHistogramChartHeightPx", ReadInt(text, "damageHistogramChartHeightPx", cfg.DamageHistogramChartHeightPx));
		cfg.DamageHistogramGapPx = ReadInt(text, "DamageHistogramGapPx", ReadInt(text, "damageHistogramGapPx", cfg.DamageHistogramGapPx));
		cfg.DamageHistogramUseNativeFrameSprite = ReadBool(text, "DamageHistogramUseNativeFrameSprite", ReadBool(text, "damageHistogramUseNativeFrameSprite", cfg.DamageHistogramUseNativeFrameSprite));
		cfg.DamageHistogramPanelUgui = ReadBool(text, "DamageHistogramPanelUgui", ReadBool(text, "damageHistogramPanelUgui", cfg.DamageHistogramPanelUgui));
		cfg.DamageHistogramPanelUguiLayoutPercent = ReadInt(text, "DamageHistogramPanelUguiLayoutPercent", ReadInt(text, "damageHistogramPanelUguiLayoutPercent", cfg.DamageHistogramPanelUguiLayoutPercent));
		cfg.DamageHistogramPanelUguiEdgeFeatherPx = ReadInt(text, "DamageHistogramPanelUguiEdgeFeatherPx", ReadInt(text, "damageHistogramPanelUguiEdgeFeatherPx", cfg.DamageHistogramPanelUguiEdgeFeatherPx));
		cfg.DamageHistogramFontScalePercent = ReadInt(text, "DamageHistogramFontScalePercent", ReadInt(text, "damageHistogramFontScalePercent", cfg.DamageHistogramFontScalePercent));
		cfg.DamageHistogramMinBars = ReadInt(text, "DamageHistogramMinBars", ReadInt(text, "damageHistogramMinBars", cfg.DamageHistogramMinBars));
		return cfg;
	}

	private static bool ReadBool(string text, string key, bool fallback)
	{
		var raw = ReadRawValue(text, key);
		if (raw == null)
		{
			return fallback;
		}
		return raw.Equals("true", StringComparison.OrdinalIgnoreCase)
		       || raw.Equals("1", StringComparison.OrdinalIgnoreCase)
		       || raw.Equals("yes", StringComparison.OrdinalIgnoreCase)
		       || raw.Equals("on", StringComparison.OrdinalIgnoreCase);
	}

	private static int ReadInt(string text, string key, int fallback)
	{
		var raw = ReadRawValue(text, key);
		return raw != null && int.TryParse(raw, out var value) ? value : fallback;
	}

	private static string ReadRawValue(string text, string key)
	{
		var quoted = "\"" + key + "\"";
		var idx = text.IndexOf(quoted, StringComparison.OrdinalIgnoreCase);
		if (idx < 0)
		{
			return null;
		}
		idx = text.IndexOf(':', idx + quoted.Length);
		if (idx < 0)
		{
			return null;
		}
		idx++;
		while (idx < text.Length && char.IsWhiteSpace(text[idx]))
		{
			idx++;
		}
		if (idx >= text.Length)
		{
			return null;
		}

		var quotedValue = text[idx] == '"';
		if (quotedValue)
		{
			idx++;
		}
		var end = idx;
		while (end < text.Length)
		{
			var c = text[end];
			if (quotedValue ? c == '"' : c == ',' || c == '}' || char.IsWhiteSpace(c))
			{
				break;
			}
			end++;
		}
		return end > idx ? text.Substring(idx, end - idx).Trim() : null;
	}
}
