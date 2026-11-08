using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text.RegularExpressions;

namespace OfflineLauncher;

internal sealed class GameCatalog
{
	public List<DifficultyOption> Difficulties { get; } = new();
	public List<string> MapTemplates { get; } = new();
	public Dictionary<string, string> MapModesByTemplate { get; } = new(StringComparer.OrdinalIgnoreCase);
	public List<string> Fractions { get; } = new();
	public Dictionary<string, List<string>> HeroesByFraction { get; } = new(StringComparer.OrdinalIgnoreCase);
}

internal sealed class DifficultyOption
{
	public int Index { get; init; }
	public int Economy { get; init; }
	public int Neutrals { get; init; }
	public int Ai { get; init; }

	public override string ToString()
	{
		return $"Preset {Index + 1} (economy {Economy}, neutrals {Neutrals}, AI {Ai})";
	}
}

internal sealed class LauncherConfig
{
	public string MatchMode { get; set; } = "SinglePlayer";
	public string MapTemplate { get; set; } = "Jebus Outcast";
	public int DifficultyIndex { get; set; }
	public string PlayerOneFaction { get; set; } = "random";
	public string PlayerOneHero { get; set; } = "random";
	public string PlayerTwoFaction { get; set; } = "random";
	public string PlayerTwoHero { get; set; } = "random";
	public bool AutoLaunchOnMenu { get; set; }
}

internal static class GameCatalogLoader
{
	internal const string ConfigFileName = "OfflineLauncherConfig.json";

	internal static GameCatalog Load(string gameRoot)
	{
		var streamingAssets = Path.Combine(gameRoot, "HeroesOE_Data", "StreamingAssets");
		var coreZipPath = Path.Combine(streamingAssets, "Core.zip");
		if (!File.Exists(coreZipPath))
		{
			throw new FileNotFoundException("Could not find Core.zip in the selected game folder.", coreZipPath);
		}

		var catalog = new GameCatalog();
		using var archive = ZipFile.OpenRead(coreZipPath);

		var quickStartJson = ReadZipText(archive, "DB/quickStart.json");
		var dataJson = ReadZipText(archive, "DB/data.json");
		ParseDifficulties(quickStartJson, catalog);
		LoadMapTemplates(streamingAssets, catalog);
		LoadHeroesByFraction(archive, catalog);
		LoadFractions(dataJson, catalog);
		SortCatalog(catalog);
		return catalog;
	}

	internal static string GetConfigPath(string gameRoot)
	{
		return Path.Combine(gameRoot, ConfigFileName);
	}

	private static void ParseDifficulties(string json, GameCatalog catalog)
	{
		var difficultiesBlock = ReadArrayBlock(json, "difficulties");
		var matches = Regex.Matches(
			difficultiesBlock,
			"\"economy\"\\s*:\\s*(\\d+).*?\"neutrals\"\\s*:\\s*(\\d+).*?\"ai\"\\s*:\\s*(\\d+)",
			RegexOptions.Singleline);

		for (var i = 0; i < matches.Count; i++)
		{
			catalog.Difficulties.Add(new DifficultyOption
			{
				Index = i,
				Economy = ReadInt(matches[i].Groups[1].Value, 0),
				Neutrals = ReadInt(matches[i].Groups[2].Value, 0),
				Ai = ReadInt(matches[i].Groups[3].Value, 0)
			});
		}
	}

	private static void LoadMapTemplates(string streamingAssets, GameCatalog catalog)
	{
		var templateDirectory = Path.Combine(streamingAssets, "map_templates");
		if (!Directory.Exists(templateDirectory))
		{
			return;
		}

		foreach (var path in Directory.GetFiles(templateDirectory, "*.rmg.json"))
		{
			var templateName = Path.GetFileNameWithoutExtension(Path.GetFileNameWithoutExtension(path));
			var templateJson = File.ReadAllText(path);
			catalog.MapTemplates.Add(templateName);
			catalog.MapModesByTemplate[templateName] = ReadQuotedValue(templateJson, "gameMode", "Classic");
		}
	}

	private static void LoadFractions(string dataJson, GameCatalog catalog)
	{
		var fractionsBlock = ReadArrayBlock(dataJson, "availableFractions");
		var matches = Regex.Matches(fractionsBlock, "\"([^\"]+)\"");
		for (var i = 0; i < matches.Count; i++)
		{
			var fraction = matches[i].Groups[1].Value;
			if (string.IsNullOrWhiteSpace(fraction))
			{
				continue;
			}

			if (catalog.HeroesByFraction.TryGetValue(fraction, out var heroes) && heroes.Count > 0)
			{
				catalog.Fractions.Add(fraction);
			}
		}

		if (catalog.Fractions.Count > 0)
		{
			return;
		}

		foreach (var pair in catalog.HeroesByFraction)
		{
			if (pair.Value.Count > 0)
			{
				catalog.Fractions.Add(pair.Key);
			}
		}
	}

	private static void LoadHeroesByFraction(ZipArchive archive, GameCatalog catalog)
	{
		foreach (var entry in archive.Entries)
		{
			if (!entry.FullName.StartsWith("DB/heroes/", StringComparison.OrdinalIgnoreCase) ||
				!entry.FullName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
			{
				continue;
			}

			var text = ReadZipText(entry);
			var ids = Regex.Matches(text, "\"id\"\\s*:\\s*\"([^\"]+)\"");
			var fractions = Regex.Matches(text, "\"fraction\"\\s*:\\s*\"([^\"]+)\"");
			var count = Math.Min(ids.Count, fractions.Count);
			for (var i = 0; i < count; i++)
			{
				var heroId = ids[i].Groups[1].Value;
				var fraction = fractions[i].Groups[1].Value;
				if (string.IsNullOrWhiteSpace(heroId) ||
					string.IsNullOrWhiteSpace(fraction) ||
					heroId.StartsWith("tutorial_", StringComparison.OrdinalIgnoreCase) ||
					heroId.StartsWith("campaign_", StringComparison.OrdinalIgnoreCase))
				{
					continue;
				}

				if (!catalog.HeroesByFraction.TryGetValue(fraction, out var heroes))
				{
					heroes = new List<string>();
					catalog.HeroesByFraction[fraction] = heroes;
				}

				if (!heroes.Contains(heroId, StringComparer.OrdinalIgnoreCase))
				{
					heroes.Add(heroId);
				}
			}
		}
	}

	private static void SortCatalog(GameCatalog catalog)
	{
		catalog.MapTemplates.Sort(StringComparer.OrdinalIgnoreCase);
		catalog.Fractions.Sort(StringComparer.OrdinalIgnoreCase);
		foreach (var pair in catalog.HeroesByFraction)
		{
			pair.Value.Sort(StringComparer.OrdinalIgnoreCase);
		}
	}

	private static string ReadArrayBlock(string json, string key)
	{
		var match = Regex.Match(json, $"\"{Regex.Escape(key)}\"\\s*:\\s*\\[(.*?)\\]", RegexOptions.Singleline);
		return match.Success ? match.Groups[1].Value : string.Empty;
	}

	private static string ReadQuotedValue(string json, string key, string fallback)
	{
		var match = Regex.Match(json, $"\"{Regex.Escape(key)}\"\\s*:\\s*\"([^\"]+)\"", RegexOptions.Singleline);
		return match.Success ? match.Groups[1].Value : fallback;
	}

	private static int ReadInt(string text, int fallback)
	{
		return int.TryParse(text, out var value) ? value : fallback;
	}

	private static string ReadZipText(ZipArchive archive, string entryPath)
	{
		var entry = archive.GetEntry(entryPath) ?? throw new FileNotFoundException($"Missing '{entryPath}' in Core.zip.");
		return ReadZipText(entry);
	}

	private static string ReadZipText(ZipArchiveEntry entry)
	{
		using var stream = entry.Open();
		using var reader = new StreamReader(stream);
		return reader.ReadToEnd();
	}
}
