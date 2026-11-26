using System;
using System.Collections.Generic;
using System.Globalization;
using TMPro;
using UnityEngine;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using K = OfflineUnlockMod.Homm3TownBuildingWindowKit;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using R = OfflineUnlockMod.Homm3ConfluxMagicUniversityRuntime;
using DataObjCity = Hex.Session.Data.ObjCity;
using UnityImage = UnityEngine.UI.Image;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22: the Magic University window (War Captives look). Opened from the "Magic University"
/// town-screen button in a Conflux town with Build_Magic_University built. One tab per hero in town, then one row per
/// school: click an available row to learn it for 2500 Gold. Greyed rows say why. Esc or Close shuts it.
/// </summary>
internal static class Homm3ConfluxMagicUniversityWindow
{
	private const float Width = 720f;
	private const float TabHeight = 44f;
	private static readonly K.TownButton Button = new("OFFLINE_UNLOCK_MOD_CONFLUX_MAGIC_UNIVERSITY_BUTTON", "Magic University");
	private static readonly K.Modal Modal = new("OFFLINE_UNLOCK_MOD_CONFLUX_MAGIC_UNIVERSITY");

	private static DataObjCity _city;
	private static int _tab;
	private static string _status;
	private static bool _statusGood;
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
			var shown = !Homm3DungeonWarCaptivesWindow.IsOpen && !Homm3StrongholdFreelancersGuildWindow.IsOpen
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
			K.LogWarning("Magic University tick failed: " + ex.GetBaseException().Message);
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
			Homm3DungeonWarCaptivesWindow.ShowBanner("The Magic University could not open: " + fail);
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
		var heroes = K.HeroesInTown(_city);
		if (_tab >= heroes.Count)
			_tab = 0;
		var hero = heroes.Count > 0 ? heroes[_tab] : null;
		var side = _city.ownerSide;
		var height = K.HeaderHeight + 16f + TabHeight + 16f + R.Schools.Length * (K.RowHeight + K.RowGap) + 30f + K.SmallButtonHeight + 20f + K.FooterHeight;
		K.Chrome(w, Width, height, "skill_faction_homm3_conflux", "Magic University",
			"Learn a school of magic for " + R.GoldCost.ToString("N0", CultureInfo.InvariantCulture) + " Gold");

		var y = K.HeaderHeight + 16f;
		if (heroes.Count == 0)
		{
			A.AddText(w, P.FontMedium, P.SizeMain, "No hero is in this town.", K.Pad, y, Width - 2f * K.Pad, TabHeight, P.TipBody, TextAlignmentOptions.MidlineLeft);
		}
		var x = K.Pad;
		for (var t = 0; t < heroes.Count; t++)
		{
			var tab = t;
			var tw = (Width - 2f * K.Pad - (heroes.Count - 1) * 10f) / heroes.Count;
			Add(K.Button(w, heroes[t].Name + (heroes[t].Visitor ? " (visiting)" : " (garrison)"), x, y, tw, TabHeight, true, t == _tab),
				() => { _tab = tab; _status = null; Build(); });
			x += tw + 10f;
		}
		y += TabHeight + 16f;
		foreach (var (sid, name) in R.Schools)
		{
			var s = sid;
			var n = name;
			var blocked = R.Blocked(hero, side, sid);
			var enabled = blocked == null;
			var plate = A.AddSliced(w, P.SpriteButton, K.Pad, y, Width - 2f * K.Pad, K.RowHeight, 1.4f, enabled ? K.RowColor : K.RowDisabled);
			if (plate != null && plate.sprite != null && !enabled)
				plate.color = K.DisabledTint;
			A.AddText(w, P.FontBook, P.SizeSubHeader, name, K.Pad + K.RowTextInset, y + 6f, 300f, 28f, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.MidlineLeft);
			A.AddText(w, P.FontMedium, P.SizeSmall, enabled ? "Learn for " + R.GoldCost.ToString("N0", CultureInfo.InvariantCulture) + " gold" : blocked,
				K.Pad + K.RowTextInset, y + 34f, Width - 2f * K.Pad - 2f * K.RowTextInset, 22f, enabled ? P.TipNote : P.TipWarn, TextAlignmentOptions.MidlineLeft);
			if (enabled)
				Add(plate, () => DoLearn(hero, s, n));
			y += K.RowHeight + K.RowGap;
		}
		A.AddText(w, P.FontMedium, P.SizeSmall, _status ?? "", K.Pad, y, Width - 2f * K.Pad, 26f, _statusGood ? P.TipBody : P.CostBad, TextAlignmentOptions.MidlineLeft, true);
		y += 30f;
		Add(K.Button(w, "Close", (Width - 170f) / 2f, y, 170f, K.SmallButtonHeight, true), Close);
	}

	private static void DoLearn(K.TownHero hero, string sid, string name)
	{
		_statusGood = R.Learn(hero, _city.ownerSide, sid, name, out var result);
		_status = result;
		Build();
	}
}
