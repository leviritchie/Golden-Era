using System;
using System.Collections.Generic;
using System.Text;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using L = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using P = OfflineUnlockMod.Homm3TowerArtificingPicker;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Post-battle "schematic learned" notice for Tower Artificing observation. User direction 2026-11-13: the text
/// "Through careful observation, your hero has added the secrets of [Ability Name in colour] ([essence cost]) to their
/// schematic book!", drawn in the Artificing picker's own style (parchment scroll with rollers, Schematic Book rows
/// with the law cell + Frame_Law_Price pill, the picker's button) instead of the HoMM3 dialog the necromancy notice
/// uses. Modal: a full-screen raycast shield owns every pointer event while it is open (the old IMGUI OK button let the
/// click fall through to the post-battle level-up choices), the game's input gates are held through
/// <see cref="Homm3TowerArtificingPickerInputBlock"/>, and it closes on button release so the press and release both
/// land on the shield. Shown only for the local player's hero; the essence figure is the cheapest graft (onto the
/// tier-1 line) at the schematic's source tier.
/// </summary>
internal static class Homm3TowerArtificingLearnNotification
{
	private const string LogPrefix = "HoMM3 Tower Artificing learn notice: ";
	private const string CanvasObjectName = "Homm3TowerArtificingLearnNotice";
	private const int SortingOrder = L.SortingOrder + 10;
	private const string AbilityColor = "#8C4A0E";

	// Notice-local layout (reference 1920x1080, top-left origin, y down).
	private const float Width = 820f;
	private const float Top = 110f;
	private const float PaperInset = 34f;
	private const float ContentInset = 70f;
	private const float TitleHeight = 30f;
	private const float RowPitch = 64f;
	private const float RowHeight = L.BookRowHeight;
	private const float ButtonWidth = 220f;
	private const int MaxRows = 6;

	private static readonly List<Learned> Pending = new();
	private static GameObject _canvasObject;
	private static RectTransform _window;
	private static UnityImage _button;
	private static bool _typeRegistered;
	private static bool _typeFailed;
	private static bool _blocking;

	internal readonly struct Learned
	{
		internal Learned(int schematic, int tier, bool refined)
		{
			Schematic = schematic;
			Tier = tier;
			Refined = refined;
		}

		internal int Schematic { get; }
		internal int Tier { get; }
		/// <summary>Already in the book at a higher source tier; now cheaper.</summary>
		internal bool Refined { get; }
	}

	internal static void Show(IReadOnlyList<Learned> learned)
	{
		if (learned == null || learned.Count == 0)
			return;
		try
		{
			// A second battle before the notice is dismissed adds to it instead of replacing it.
			foreach (var item in learned)
			{
				Pending.RemoveAll(existing => existing.Schematic == item.Schematic);
				Pending.Add(item);
			}
			if (!EnsureCanvas())
				return;
			Rebuild();
			if (!_blocking && !P.IsOpen)
			{
				Homm3TowerArtificingPickerInputBlock.Begin();
				_blocking = true;
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(LogPrefix + "show failed: " + ex.GetBaseException().Message);
			Close();
		}
	}

	internal static void Tick()
	{
		if (_canvasObject == null)
			return;
		try
		{
			if (_blocking)
				Homm3TowerArtificingPickerInputBlock.Hold();
			var mouse = (Vector2)Input.mousePosition;
			var over = _button != null && RectTransformUtility.RectangleContainsScreenPoint(_button.rectTransform, mouse, null);
			if (_button != null)
			{
				var sprite = P.NativeSprite(over ? L.SpriteButtonHover : L.SpriteButton);
				if (sprite != null && _button.sprite != sprite)
					_button.sprite = sprite;
			}
			// Release, not press: the press already landed on the shield, so nothing behind can receive the click.
			if (over && Input.GetMouseButtonUp(0)
			    || Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter)
			    || Input.GetKeyDown(KeyCode.Escape) || Input.GetKeyDown(KeyCode.Space))
				Close();
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(LogPrefix + "input failed; closing: " + ex.GetBaseException().Message);
			Close();
		}
	}

	private static void Close()
	{
		Pending.Clear();
		_button = null;
		_window = null;
		if (_canvasObject != null)
		{
			// Deactivate first so the shield stops raycasting this frame, then destroy.
			_canvasObject.SetActive(false);
			UnityObject.Destroy(_canvasObject);
			_canvasObject = null;
		}
		if (_blocking)
		{
			_blocking = false;
			if (!P.IsOpen)
				Homm3TowerArtificingPickerInputBlock.End();
		}
	}

	// ---------------------------------------------------------------- view

	private static bool EnsureCanvas()
	{
		if (_canvasObject != null)
			return true;
		if (_typeFailed)
			return false;
		if (!_typeRegistered)
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3TowerArtificingLearnNotificationHost>();
				_typeRegistered = true;
			}
			catch (Exception ex)
			{
				_typeFailed = true;
				Plugin.LogSource?.LogError(LogPrefix + "host type failed: " + ex.GetType().Name + ": " + ex.Message);
				return false;
			}
		}
		P.ResolveNativeSprites();

		var go = new GameObject(CanvasObjectName, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
			Il2CppType.Of<GraphicRaycaster>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		_canvasObject = go;
		var canvas = go.GetComponent<Canvas>();
		var scaler = go.GetComponent<CanvasScaler>();
		if (canvas == null || scaler == null || go.GetComponent<GraphicRaycaster>() == null)
		{
			Plugin.LogSource?.LogError(LogPrefix + "canvas could not be created");
			Close();
			return false;
		}
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = SortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(L.ReferenceWidth, L.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= L.ReferenceWidth / L.ReferenceHeight ? 1f : 0f;
		var canvasRect = go.GetComponent<RectTransform>();

		// Raycast shield: owns every pointer event under and around the notice.
		var shield = P.NewImage("Shield", canvasRect, null, new Color(0f, 0f, 0f, 0.35f));
		P.Stretch(shield.rectTransform);
		shield.raycastTarget = true;

		_window = P.NewRect("Notice", canvasRect);
		_window.anchorMin = _window.anchorMax = _window.pivot = new Vector2(0.5f, 1f);
		_window.anchoredPosition = new Vector2(0f, -Top);

		if (go.AddComponent<Homm3TowerArtificingLearnNotificationHost>() == null)
		{
			Plugin.LogSource?.LogError(LogPrefix + "host component could not be added");
			Close();
			return false;
		}
		return true;
	}

	private static void Rebuild()
	{
		if (_window == null)
			return;
		for (var i = _window.childCount - 1; i >= 0; i--)
			UnityObject.Destroy(_window.GetChild(i).gameObject);
		_button = null;
		var content = P.NewRect("Content", _window);
		P.Stretch(content);

		var paperX = PaperInset;
		var paperW = Width - 2f * PaperInset;
		var cx = ContentInset;
		var cw = Width - 2f * ContentInset;

		var y = PaperInset + 30f;
		var title = Pending.Count == 1 ? "New Schematic" : "New Schematics";
		P.AddText(content, L.FontRegular, L.SizeHeaderBig, title, cx, y, cw, TitleHeight, L.Ink, TextAlignmentOptions.Midline);
		y += TitleHeight + 12f;

		var body = P.AddText(content, L.FontMedium, L.SizeSubHeader, "", cx, y, cw, 200f, L.Ink, TextAlignmentOptions.Top, true);
		if (body != null)
		{
			body.richText = true;
			body.text = BuildBody(Pending);
		}
		var bodyHeight = P.MeasureHeight(body, cw, 200f);
		if (body != null)
			P.Place(body.rectTransform, cx, y, cw, bodyHeight + 4f);
		y += bodyHeight + 18f;

		var shown = Math.Min(Pending.Count, MaxRows);
		for (var i = 0; i < shown; i++)
		{
			AddRow(content, Pending[i], cx, y + (RowPitch - RowHeight) / 2f, cw);
			y += RowPitch;
		}
		if (Pending.Count > shown)
		{
			P.AddText(content, L.FontMedium, L.SizeSmall, "and " + (Pending.Count - shown) + " more in the Schematic Book", cx, y, cw, 24f, L.InkMuted, TextAlignmentOptions.Midline);
			y += 28f;
		}
		y += 16f;

		var bx = (Width - ButtonWidth) / 2f;
		_button = P.AddSliced(content, L.SpriteButton, bx, y, ButtonWidth, L.ButtonHeight, L.ButtonSliceMultiplier, new Color(0.35f, 0.26f, 0.15f, 1f));
		P.AddText(content, L.FontRegular, L.SizeMain, "OK", bx, y, ButtonWidth, L.ButtonHeight, L.ButtonText, TextAlignmentOptions.Midline);
		y += L.ButtonHeight + 34f;

		var height = y + PaperInset;
		_window.sizeDelta = new Vector2(Width, height);

		// Parchment behind everything (first siblings); rollers keep the picker's aspect so the end caps are not squashed.
		var paper = P.AddImage(_window, L.SpritePaper, paperX, PaperInset, paperW, height - 2f * PaperInset, new Color(0.78f, 0.72f, 0.6f, 1f));
		var rollerW = L.RollerWidth * height / L.RollerHeight;
		var left = P.AddImage(_window, L.SpriteRollerLeft, paperX - rollerW * (L.PaperX - L.RollerLeftX) / L.RollerWidth, 0f, rollerW, height, new Color(0.55f, 0.45f, 0.3f, 1f));
		var right = P.AddImage(_window, L.SpriteRollerRight, paperX + paperW - rollerW * (L.PaperX + L.PaperWidth - L.RollerRightX) / L.RollerWidth, 0f, rollerW, height, new Color(0.55f, 0.45f, 0.3f, 1f));
		paper.transform.SetSiblingIndex(0);
		left.transform.SetSiblingIndex(1);
		right.transform.SetSiblingIndex(2);
	}

	/// <summary>One Schematic Book row as the picker draws it: row frame, law cell + passive icon, name, tier, price pill.</summary>
	private static void AddRow(Transform parent, Learned item, float x, float y, float w)
	{
		var cy = y + RowHeight / 2f;
		P.AddSliced(parent, L.SpriteRowSelected, x, y, w, RowHeight, L.RowSliceMultiplier, new Color(0.8f, 0.68f, 0.4f, 0.35f));
		var iconCx = x + (L.BookIconCenterX - L.BookX);
		P.AddCentered(parent, L.SpriteCellBack, iconCx, cy, L.BookCellBack, L.BookCellBack, new Color(0.35f, 0.3f, 0.25f, 1f));
		if (P.PassiveIcon(item.Schematic) is { } icon)
		{
			var image = P.AddSpriteImage(parent, "Icon", icon, iconCx - L.BookCellIcon / 2f, cy - L.BookCellIcon / 2f, L.BookCellIcon, L.BookCellIcon);
			image.preserveAspect = true;
		}
		P.AddCentered(parent, L.SpriteCellFrame, iconCx, cy, L.BookCellFrame, L.BookCellFrame, new Color(0.7f, 0.58f, 0.3f, 0.6f));

		var textX = x + (L.BookTextX - L.BookX);
		var priceX = x + w - L.PriceWidth - 14f;
		var textW = priceX - textX - 12f;
		P.AddText(parent, L.FontRegular, L.SizeMain, P.Name(item.Schematic), textX, cy - 23f, textW, 24f, L.Ink, TextAlignmentOptions.MidlineLeft);
		P.AddText(parent, L.FontMedium, L.SizeSmall, "Tier " + item.Tier + " schematic" + (item.Refined ? " (refined, now cheaper)" : ""),
			textX, cy + 1f, textW, 20f, L.InkMuted, TextAlignmentOptions.MidlineLeft);

		var cost = MinCost(item.Tier);
		P.AddImage(parent, L.SpritePrice, priceX, cy - L.PriceHeight / 2f, L.PriceWidth, L.PriceHeight, new Color(0.1f, 0.07f, 0.05f, 1f));
		P.AddCentered(parent, L.SpriteEssence, priceX + 4f, cy, L.PriceIconSize, L.PriceIconSize, L.EssenceTint);
		P.AddText(parent, L.FontRegular, L.SizeMain, cost.ToString(), priceX + 18f, cy - L.PriceHeight / 2f, L.PriceWidth - 26f, L.PriceHeight,
			L.CostOk, TextAlignmentOptions.MidlineRight);
	}

	internal static string BuildBody(IReadOnlyList<Learned> learned)
	{
		var added = new List<string>();
		var refined = new List<string>();
		foreach (var item in learned)
			(item.Refined ? refined : added).Add(Colored(P.Name(item.Schematic)) + " (" + MinCost(item.Tier) + " essence)");

		var text = new StringBuilder();
		if (added.Count > 0)
			text.Append("Through careful observation, your hero has added the secrets of ").Append(JoinList(added)).Append(" to their schematic book!");
		if (refined.Count > 0)
		{
			if (text.Length > 0)
				text.Append(' ');
			text.Append(added.Count > 0 ? "They have also refined " : "Through careful observation, your hero has refined ")
				.Append(JoinList(refined))
				.Append(refined.Count == 1 ? ", a schematic now cheaper to graft!" : ", schematics now cheaper to graft!");
		}
		return text.ToString();
	}

	private static string Colored(string text)
	{
		return "<color=" + AbilityColor + ">" + text + "</color>";
	}

	private static string JoinList(List<string> items)
	{
		if (items.Count == 1)
			return items[0];
		if (items.Count == 2)
			return items[0] + " and " + items[1];
		return string.Join(", ", items.GetRange(0, items.Count - 1)) + " and " + items[items.Count - 1];
	}

	/// <summary>Cheapest graft of a schematic at this source tier: onto the tier-1 Tower line.</summary>
	private static int MinCost(int sourceTier)
	{
		var cost = P.Cost(sourceTier, 1);
		return cost == int.MaxValue ? 0 : cost;
	}
}

public sealed class Homm3TowerArtificingLearnNotificationHost : MonoBehaviour
{
	public Homm3TowerArtificingLearnNotificationHost(IntPtr ptr) : base(ptr) { }

	private void Update()
	{
		Homm3TowerArtificingLearnNotification.Tick();
	}
}
