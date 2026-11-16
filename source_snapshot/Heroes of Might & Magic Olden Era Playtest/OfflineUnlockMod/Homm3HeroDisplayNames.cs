using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using Newtonsoft.Json.Linq;

namespace OfflineUnlockMod;

/// <summary>
/// Hero display names for mod UI: Hex.Session.Data.Hero carries no name, only configSid, and the game's hero name is the
/// Lang/&lt;language&gt;/texts/heroes.json token whose sid is that configSid. Read once from Core.zip (English; the mod's
/// custom hero names are English in every language folder). Falls back to the sid.
/// </summary>
internal static class Homm3HeroDisplayNames
{
	private static readonly Homm3LangTokenFile Heroes = new("Lang/english/texts/heroes.json", "hero display names");

	internal static string Resolve(string heroSid)
	{
		if (string.IsNullOrWhiteSpace(heroSid))
			return "Hero";
		var sid = heroSid.Trim();
		return Heroes.TryGet(sid + "_name", out var name) || Heroes.TryGet(sid, out name) ? name : sid;
	}
}

/// <summary>Unit display names for mod UI: the Lang/english/texts/units.json token "&lt;unitSid&gt;_name" from Core.zip; falls back to the sid.</summary>
internal static class Homm3UnitDisplayNames
{
	private static readonly Homm3LangTokenFile Units = new("Lang/english/texts/units.json", "unit display names");

	internal static string Resolve(string unitSid)
	{
		if (string.IsNullOrWhiteSpace(unitSid))
			return "Unit";
		var sid = unitSid.Trim();
		return Units.TryGet(sid + "_name", out var name) ? name : sid;
	}
}

/// <summary>One Core.zip Lang token file (sid -> text), read once on first use.</summary>
internal sealed class Homm3LangTokenFile
{
	private readonly string _path;
	private readonly string _label;
	private Dictionary<string, string> _texts;
	private bool _loadFailed;

	internal Homm3LangTokenFile(string path, string label)
	{
		_path = path;
		_label = label;
	}

	internal bool TryGet(string sid, out string text)
	{
		text = null;
		return EnsureLoaded() && _texts.TryGetValue(sid, out text) && !string.IsNullOrWhiteSpace(text);
	}

	private bool EnsureLoaded()
	{
		if (_texts != null)
			return true;
		if (_loadFailed)
			return false;
		try
		{
			var coreZipPath = LauncherConfigReader.GetCoreZipPath();
			using var archive = ZipFile.OpenRead(coreZipPath);
			var entry = archive.GetEntry(_path) ?? throw new FileNotFoundException(_path + " not in Core.zip");
			using var reader = new StreamReader(entry.Open());
			var texts = new Dictionary<string, string>(StringComparer.Ordinal);
			// `is JArray` on the indexer result is false in game (the in-game load came back empty and every name fell
			// back to the sid); re-parse the token text like Homm3HeroSpecializationIconSpriteCache does.
			var tokensToken = JObject.Parse(reader.ReadToEnd())["tokens"];
			if (tokensToken != null && tokensToken.Type == JTokenType.Array)
			{
				var tokens = JArray.Parse(tokensToken.ToString());
				for (var i = 0; i < tokens.Count; i++)
				{
					var token = tokens[i];
					var sid = (string)token["sid"];
					var value = (string)token["text"];
					if (!string.IsNullOrWhiteSpace(sid) && !string.IsNullOrWhiteSpace(value))
						texts[sid] = value;
				}
			}
			_texts = texts;
			Plugin.LogSource?.LogInfo("HoMM3 " + _label + ": loaded " + texts.Count + " token(s) from Core.zip " + _path + ".");
			return true;
		}
		catch (Exception ex)
		{
			_loadFailed = true;
			Plugin.LogSource?.LogWarning("HoMM3 " + _label + ": load failed; using sids: " + ex.GetBaseException().Message);
			return false;
		}
	}
}
