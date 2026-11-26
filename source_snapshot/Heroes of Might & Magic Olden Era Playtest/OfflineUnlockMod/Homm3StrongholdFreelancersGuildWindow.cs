using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using K = OfflineUnlockMod.Homm3TownBuildingWindowKit;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using R = OfflineUnlockMod.Homm3StrongholdFreelancersGuildRuntime;
using DataObjCity = Hex.Session.Data.ObjCity;
using UnityImage = UnityEngine.UI.Image;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22: the Freelancer's Guild window (War Captives look). Opened from the "Freelancer's Guild"
/// town-screen button in a Stronghold town with Build_Resource_Depot_level_2 built. Layout: one tab per army (garrison,
/// garrison hero, visiting hero), a pay-in row (gold or one resource), then one row per stack with Sell 1 / Half / All.
/// Esc or Close shuts it.
/// </summary>
internal static class Homm3StrongholdFreelancersGuildWindow
{
	private const float Width = 880f;
	private const float TabHeight = 44f;
	private const float RowH = 56f;
	private static readonly K.TownButton Button = new("OFFLINE_UNLOCK_MOD_STRONGHOLD_FREELANCERS_GUILD_BUTTON", "Freelancer's Guild");
	private static readonly K.Modal Modal = new("OFFLINE_UNLOCK_MOD_STRONGHOLD_FREELANCERS_GUILD");

	private static DataObjCity _city;
	private static int _tab;
	private static string _resource = "gold";
	private static string _status;
	private static readonly List<UnityImage> Plates = new();
	private static readonly List<Action> Actions = new();

	internal static bool IsOpen => Modal.IsOpen;

	internal static void Tick()
	{
		try
		{
			if (Modal.IsOpen)
			{
				TickWindow();
				return;
			}
			var shown = !Homm3DungeonWarCaptivesWindow.IsOpen && !Homm3ConfluxMagicUniversityWindow.IsOpen
			            && K.TryCurrentTownWith(R.FactionSid, R.BuildingSid, out _);
			if (Button.Update(shown))
			{
				Button.HandOff();
				Button.Hide();
				Open();
			}
		}
		catch (Exception ex)
		{
			K.LogWarning("Freelancer's Guild tick failed: " + ex.GetBaseException().Message);
			Close();
		}
	}

	private static void Open()
	{
		if (!K.TryCurrentTownWith(R.FactionSid, R.BuildingSid, out var city))
			return;
		_city = city;
		_tab = 0;
		_status = null;
		if (!Modal.Open(Width, out var fail))
		{
			Homm3DungeonWarCaptivesWindow.ShowBanner("The Freelancer's Guild could not open: " + fail);
			return;
		}
		Build();
	}

	private static void Close()
	{
		Plates.Clear();
		Actions.Clear();
		_city = null;
		Modal.Close();
	}

	private static void TickWindow()
	{
		Homm3TowerArtificingPickerInputBlock.Hold();
		if (Input.GetKeyDown(KeyCode.Escape) || K.CurrentCity(out _) == null)
		{
			Close();
			return;
		}
		var i = K.HoverAndClick(Plates);
		if (i >= 0 && i < Actions.Count)
			Actions[i]();
	}

	private static void Add(UnityImage plate, Action act)
	{
		if (plate == null)
			return;
		Plates.Add(plate);
		Actions.Add(act);
	}

	private static void Build()
	{
		Plates.Clear();
		Actions.Clear();
		Modal.Clear();
		var w = Modal.Window;
		if (w == null || _city == null)
			return;
		var sources = R.ReadSources(_city);
		R.Rates rates = null;
		string rateFail = null;
		if (!R.TryRates(_city.ownerSide, out rates, out rateFail))
			rates = null;
		if (_tab >= sources.Count)
			_tab = 0;
		var source = sources.Count > 0 ? sources[_tab] : null;
		var rows = source?.Sid == null ? 0 : source.Stacks;
		var height = K.HeaderHeight + 16f + TabHeight + 12f + TabHeight + 16f + Math.Max(1, rows) * (RowH + K.RowGap) + 30f + K.SmallButtonHeight + 20f + K.FooterHeight;
		K.Chrome(w, Width, height, "skill_faction_homm3_stronghold", "Freelancer's Guild",
			rates == null ? "Sell creatures for gold or resources" : "Sell creatures for gold or resources (" + R.N(rates.Markets) + (rates.Markets == 1 ? " Marketplace" : " Marketplaces") + ")");

		var y = K.HeaderHeight + 16f;
		// Army tabs.
		var x = K.Pad;
		if (sources.Count == 0)
		{
			A.AddText(w, P.FontMedium, P.SizeMain, "There are no creatures in this town to sell.", K.Pad, y, Width - 2f * K.Pad, TabHeight, P.TipBody, TextAlignmentOptions.MidlineLeft);
		}
		for (var t = 0; t < sources.Count; t++)
		{
			var tab = t;
			var tw = (Width - 2f * K.Pad - (sources.Count - 1) * 10f) / sources.Count;
			Add(K.Button(w, sources[t].Label, x, y, tw, TabHeight, true, t == _tab), () => { _tab = tab; _status = null; Build(); });
			x += tw + 10f;
		}
		y += TabHeight + 12f;
		// Pay-in row.
		A.AddText(w, P.FontMedium, P.SizeMain, "Pay in:", K.Pad, y, 90f, TabHeight, P.TipBody, TextAlignmentOptions.MidlineLeft);
		x = K.Pad + 96f;
		var rw = (Width - x - K.Pad - (R.PayResources.Length - 1) * 8f) / R.PayResources.Length;
		foreach (var res in R.PayResources)
		{
			var r = res;
			Add(K.Button(w, Cap(res), x, y, rw, TabHeight, true, res == _resource), () => { _resource = r; Build(); });
			x += rw + 8f;
		}
		y += TabHeight + 16f;
		// Stack rows.
		if (source != null && source.Fail != null)
		{
			A.AddText(w, P.FontMedium, P.SizeMain, "This army cannot be read: " + source.Fail, K.Pad, y, Width - 2f * K.Pad, RowH, P.TipWarn, TextAlignmentOptions.MidlineLeft, true);
			y += RowH + K.RowGap;
		}
		else if (source != null && rates == null)
		{
			A.AddText(w, P.FontMedium, P.SizeMain, "Market rates are unavailable: " + rateFail, K.Pad, y, Width - 2f * K.Pad, RowH, P.TipWarn, TextAlignmentOptions.MidlineLeft, true);
			y += RowH + K.RowGap;
		}
		else if (source != null)
		{
			var label = source.Label;
			for (var slot = 0; slot < source.Sid.Length; slot++)
			{
				var sid = source.Sid[slot];
				if (sid == null || source.Count[slot] <= 0)
					continue;
				var s = slot;
				var count = source.Count[slot];
				var max = R.MaxSell(source, slot);
				var worth = R.WorthGold(sid, rates);
				A.AddSliced(w, P.SpriteButton, K.Pad, y, Width - 2f * K.Pad, RowH, 1.4f, K.RowColor);
				var name = Homm3UnitDisplayNames.Resolve(sid) + " x" + R.N(count);
				A.AddText(w, P.FontBook, P.SizeMain, name, K.Pad + K.RowTextInset, y + 4f, 330f, 26f, P.ButtonText, TextAlignmentOptions.MidlineLeft);
				var each = worth <= 0 ? "value unreadable" : "each: " + R.Describe(R.Convert((long)Math.Floor(worth), _resource, rates), _resource);
				A.AddText(w, P.FontMedium, P.SizeSmall, max < count && max == 0 ? each + " (a hero keeps one creature)" : each, K.Pad + K.RowTextInset, y + 30f, 400f, 22f, P.TipNote, TextAlignmentOptions.MidlineLeft);
				var bx = Width - K.Pad - 12f - 3f * K.SmallButtonWidth - 2f * 8f;
				var by = y + (RowH - K.SmallButtonHeight) / 2f;
				var ok = worth > 0;
				Add(K.Button(w, "1", bx, by, K.SmallButtonWidth, K.SmallButtonHeight, ok && max >= 1), () => DoSell(label, s, 1));
				Add(K.Button(w, "Half", bx + K.SmallButtonWidth + 8f, by, K.SmallButtonWidth, K.SmallButtonHeight, ok && max >= 2), () => DoSell(label, s, Math.Max(1, count / 2)));
				Add(K.Button(w, "All", bx + 2f * (K.SmallButtonWidth + 8f), by, K.SmallButtonWidth, K.SmallButtonHeight, ok && max >= 1), () => DoSell(label, s, max));
				y += RowH + K.RowGap;
			}
			if (source.Stacks == 0)
			{
				A.AddText(w, P.FontMedium, P.SizeMain, "No creatures here.", K.Pad, y, Width - 2f * K.Pad, RowH, P.TipBody, TextAlignmentOptions.MidlineLeft);
				y += RowH + K.RowGap;
			}
		}
		A.AddText(w, P.FontMedium, P.SizeSmall, _status ?? "", K.Pad, y, Width - 2f * K.Pad, 26f, _status != null && _status.StartsWith("Sold", StringComparison.Ordinal) ? P.TipBody : P.CostBad, TextAlignmentOptions.MidlineLeft, true);
		y += 30f;
		Add(K.Button(w, "Close", (Width - 170f) / 2f, y, 170f, K.SmallButtonHeight, true), Close);
	}

	private static void DoSell(string label, int slot, int count)
	{
		R.Sell(_city, label, slot, count, _resource, out var result);
		_status = result;
		Build();
	}

	private static string Cap(string s) => string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s.Substring(1);
}
