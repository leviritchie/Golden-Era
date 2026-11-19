using System;
using System.Collections.Generic;
using System.Globalization;
using Il2CppInterop.Runtime;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using R = OfflineUnlockMod.Homm3CoveTreasureRuntime;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting central popups (approved mockup v3, 2026-11-17): a parchment sheet in the middle of the
/// screen for a collected map piece, the marked site, a dug-up treasure and an empty hole. The map dims, input to the
/// game is blocked, and the sheet closes on its button, Enter, Space or Esc. Pages queue, one at a time.
/// Art is baked by tools/cove_treasure/build_popup_art.py; body text uses the game's own font.
/// Ticked by <see cref="Homm3CoveTreasureMarkersHost"/>.
/// </summary>
internal static class Homm3CoveTreasurePopup
{
	internal sealed class Page
	{
		/// <summary>piece, spot, treasure or hole: picks the baked title art popup_title_&lt;kind&gt;.</summary>
		internal string Kind;
		internal string Flavor;
		internal readonly List<(string Text, bool Red)> Facts = new();
		internal string Button = "OK";
	}

	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_COVE_TREASURE_POPUP";
	private const float Width = 600f;
	private const float TextWidth = 470f;
	private const float TitleHeight = 62f;
	private const float FlavorSize = 20f;
	private const float FactSize = 19f;
	private const float FlavorLine = 27f;
	private const float FactLine = 26f;
	private const float ButtonWidth = 170f;
	private const float ButtonHeight = 46f;
	private const float DimAlpha = 0.45f;
	private static readonly Color Ink = new(0.23f, 0.15f, 0.09f, 1f);
	private static readonly Color FactInk = new(0.17f, 0.12f, 0.07f, 1f);
	private static readonly Color Blood = new(0.59f, 0.10f, 0.08f, 1f);
	private static readonly Color ButtonText = new(0.94f, 0.82f, 0.51f, 1f);

	private static readonly Queue<Page> Pending = new();
	private static GameObject _canvasObject;
	private static Image _button;
	private static int _openedFrame;

	internal static bool IsOpen => _canvasObject != null;

	internal static void Show(Page page)
	{
		if (page == null)
			return;
		Pending.Enqueue(page);
		Homm3CoveTreasureMarkers.EnsureHost();
	}

	internal static void Tick()
	{
		if (_canvasObject == null)
		{
			if (Pending.Count == 0)
				return;
			var page = Pending.Dequeue();
			try
			{
				Open(page);
			}
			catch (Exception ex)
			{
				Warn("popup failed to open (" + ex.GetBaseException().Message + "); shown as a banner instead.");
				Close();
				try { Homm3DungeonWarCaptivesWindow.ShowBanner(Fallback(page), 2); } catch { }
			}
			return;
		}
		try
		{
			Homm3TowerArtificingPickerInputBlock.Hold();
			var mouse = (Vector2)Input.mousePosition;
			var over = _button != null && RectTransformUtility.RectangleContainsScreenPoint(_button.rectTransform, mouse, null);
			var sprite = Homm3CoveTreasureMarkers.Art(over ? "popup_button_hover" : "popup_button");
			if (_button != null && sprite != null && _button.sprite != sprite)
				_button.sprite = sprite;
			// The click or key that caused the popup must not also close it.
			if (Time.frameCount <= _openedFrame + 1)
				return;
			if ((over && Input.GetMouseButtonDown(0)) || Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter)
				|| Input.GetKeyDown(KeyCode.Space) || Input.GetKeyDown(KeyCode.Escape))
				Close();
		}
		catch (Exception ex)
		{
			Warn("popup input failed (" + ex.GetBaseException().Message + "); closed.");
			Close();
		}
	}

	private static string Fallback(Page page)
	{
		var parts = new List<string>();
		foreach (var (text, _) in page.Facts)
			parts.Add(text);
		return string.Join(" ", parts);
	}

	private static void Open(Page page)
	{
		var go = new GameObject(CanvasObjectName, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		_canvasObject = go;
		var canvas = go.GetComponent<Canvas>();
		var scaler = go.GetComponent<CanvasScaler>();
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = P.SortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= P.ReferenceWidth / P.ReferenceHeight ? 1f : 0f;
		var canvasRect = go.GetComponent<RectTransform>();

		var dim = A.NewImage("Dim", canvasRect, null, new Color(0f, 0f, 0f, DimAlpha));
		A.Stretch(dim.rectTransform);
		dim.raycastTarget = true;

		// Heights from line estimates (the sheet has generous margins, so a line more or less still fits).
		var flavorLines = Lines(page.Flavor, 50);
		var factLines = 0;
		foreach (var (text, _) in page.Facts)
			factLines += Lines(text, 48);
		var flavorHeight = flavorLines * FlavorLine;
		var top = 46f;
		var height = top + TitleHeight + 26f + flavorHeight + 16f + factLines * FactLine + 30f + ButtonHeight + 52f;

		var window = A.NewRect("Window", canvasRect);
		window.anchorMin = window.anchorMax = window.pivot = new Vector2(0.5f, 0.5f);
		window.anchoredPosition = new Vector2(0f, 40f);
		window.sizeDelta = new Vector2(Width, height);

		var paper = Homm3CoveTreasureMarkers.Art("popup_paper");
		var sheet = A.NewImage("Paper", window, paper, new Color(0.87f, 0.78f, 0.59f, 1f));
		sheet.color = Color.white;
		A.Stretch(sheet.rectTransform);

		var y = top;
		var title = Homm3CoveTreasureMarkers.Art("popup_title_" + page.Kind);
		if (title != null)
		{
			var image = A.NewImage("Title", window, title, Color.white);
			image.color = Color.white;
			var w = TitleHeight * title.rect.width / Mathf.Max(1f, title.rect.height);
			Place(image.rectTransform, y, w, TitleHeight);
		}
		y += TitleHeight + 8f;
		var rule = A.NewImage("Rule", window, null, new Color(0.47f, 0.34f, 0.19f, 0.9f));
		Place(rule.rectTransform, y, TextWidth - 20f, 2f);
		y += 18f;

		var flavor = A.AddText(window, P.FontMedium, FlavorSize, page.Flavor ?? string.Empty, 0f, 0f, TextWidth, flavorHeight, Ink, TextAlignmentOptions.Top, true);
		if (flavor != null)
		{
			flavor.fontStyle = FontStyles.Italic;
			flavor.overflowMode = TextOverflowModes.Overflow;
			Place(flavor.rectTransform, y, TextWidth, flavorHeight);
		}
		y += flavorHeight + 16f;
		foreach (var (text, red) in page.Facts)
		{
			var h = Lines(text, 48) * FactLine;
			var fact = A.AddText(window, P.FontMedium, FactSize, text, 0f, 0f, TextWidth, h, red ? Blood : FactInk, TextAlignmentOptions.Top, true);
			if (fact != null)
			{
				fact.fontStyle = FontStyles.Bold;
				fact.overflowMode = TextOverflowModes.Overflow;
				Place(fact.rectTransform, y, TextWidth, h);
			}
			y += h;
		}
		y += 30f;
		_button = A.NewImage("Button", window, Homm3CoveTreasureMarkers.Art("popup_button"), new Color(0.2f, 0.13f, 0.08f, 1f));
		_button.color = Color.white;
		Place(_button.rectTransform, y, ButtonWidth, ButtonHeight);
		var label = A.AddText(_button.rectTransform, P.FontMedium, 20f, page.Button ?? "OK", 0f, 0f, ButtonWidth, ButtonHeight, ButtonText, TextAlignmentOptions.Center);
		if (label != null)
		{
			var rt = label.rectTransform;
			rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
			rt.anchoredPosition = Vector2.zero;
			rt.sizeDelta = new Vector2(ButtonWidth, ButtonHeight);
		}
		_openedFrame = Time.frameCount;
		Homm3TowerArtificingPickerInputBlock.Begin();
	}

	/// <summary>Top-centre placement inside the window: y is the distance from the sheet's top edge.</summary>
	private static void Place(RectTransform rt, float y, float w, float h)
	{
		rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 1f);
		rt.anchoredPosition = new Vector2(0f, -y);
		rt.sizeDelta = new Vector2(w, h);
	}

	private static int Lines(string text, int charsPerLine)
	{
		if (string.IsNullOrEmpty(text))
			return 0;
		// Word wrap estimate: count lines by filling words greedily.
		var lines = 1;
		var used = 0;
		foreach (var word in text.Split(' '))
		{
			var need = word.Length + (used > 0 ? 1 : 0);
			if (used + need > charsPerLine && used > 0)
			{
				lines++;
				used = word.Length;
			}
			else
				used += need;
		}
		return lines;
	}

	private static void Close()
	{
		var go = _canvasObject;
		_canvasObject = null;
		_button = null;
		try { Homm3TowerArtificingPickerInputBlock.End(); } catch { }
		if (go == null)
			return;
		try { UnityObject.Destroy(go); } catch { }
	}

	private static void Warn(string message)
	{
		try { Plugin.LogSource?.LogWarning(Homm3CoveTreasureRuntime.LogPrefix + "popup: " + message); } catch { }
	}

	// ---------------------------------------------------------------- pages

	private static string N(long value) => value.ToString("N0", CultureInfo.InvariantCulture);

	private static readonly string[] PieceFlavor =
	{
		"Among the spoils lies a torn scrap of sea-stained parchment. Whoever drew it took great pains to hide what it points to.",
		"A strip of oiled sailcloth, inked in a cramped hand and torn along two edges. The rest of it cannot be far.",
		"Your quartermaster turns the scrap over twice and whistles. Old ink, good vellum: somebody meant to come back for this.",
	};

	/// <summary>A local player's hero took a map piece: <paramref name="pieces"/> of <paramref name="total"/> held now.</summary>
	internal static void ShowPiece(int areaId, int pieces, int total, int leads, bool archivist = false)
	{
		Page page;
		// With an Archivist bonus piece the site can be pinned down by any piece, and a side can hold more than the
		// region's own pieces.
		var marksTheSpot = leads <= 1 && R.LeadCount(pieces - 1) != 1;
		var count = archivist ? "Bonus map piece from your Archivist." : "Map piece " + N(Math.Min(pieces, total)) + " of " + N(total) + " for this region.";
		if (marksTheSpot)
		{
			page = new Page
			{
				Kind = "spot",
				Flavor = "The last tear fits. Faded ink joins into a single bold cross, and your navigator grins from ear to ear.",
			};
			page.Facts.Add((count, false));
			page.Facts.Add(("The treasure site is marked on the map.", false));
			page.Facts.Add(("Digging needs two thirds of a day's movement.", true));
		}
		else
		{
			page = new Page
			{
				Kind = "piece",
				Flavor = archivist
					? "Your archivist knows this coast from an old ledger, and sketches in what the charts leave out."
					: PieceFlavor[Math.Abs(areaId * 7 + pieces) % PieceFlavor.Length],
			};
			page.Facts.Add((count, false));
			page.Facts.Add((leads <= 1
				? "It shows nothing new: the treasure site is already marked."
				: N(leads) + " possible sites are marked on the map. Each further piece rules one out.", false));
		}
		Show(page);
	}

	internal static void ShowTreasure(List<string> found, bool movementSpent = true)
	{
		var page = new Page
		{
			Kind = "treasure",
			Flavor = "A spade rings on iron. The crew hauls a brine-crusted chest out of the pit and its rotten lock gives way to a single blow.",
			Button = "Take it",
		};
		if (found == null || found.Count == 0)
			page.Facts.Add(("The chest is empty. Someone got here first.", false));
		else
			foreach (var line in found)
				page.Facts.Add((line, false));
		if (movementSpent)
			page.Facts.Add(("The hero's movement is spent for today.", true));
		Show(page);
	}

	internal static void ShowHole(bool wasLead, bool movementSpent = true)
	{
		var page = new Page
		{
			Kind = "hole",
			Flavor = "Your men dig until their backs give out and find only worms and wet sand. The map lied, or you read it wrong.",
		};
		page.Facts.Add((wasLead ? "An empty hole is left. This lead is struck from the map." : "An empty hole is left.", false));
		if (movementSpent)
			page.Facts.Add(("The hero's movement is spent for today.", true));
		Show(page);
	}
}
