using System;
using System.Collections.Generic;
using System.Globalization;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using W = OfflineUnlockMod.Homm3DungeonWarCaptivesWindowLayout;
using L = OfflineUnlockMod.Homm3ConfluxFusionPanelLayout;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// The Elemental Fusion panel, opened by <see cref="Homm3ConfluxFusionRuntime"/> when a local human casts the spell. It is
/// the War Captives recruit panel's shell (the native CanvasDiplomacyUnitsPanel sprites, fonts and colours) with only the
/// controls (user, 2026-11-15: "just the slots and a fusion button"): the hero's army row on top, the two fusion slots and
/// the fused result below ("A + B = fused"), and Cancel / Fuse. Stacks are dragged, as in the War Captives recruit panel
/// (same press / threshold / ghost, <see cref="Homm3DungeonWarCaptivesWindow.NewDragGhost"/>): army card onto a fusion
/// slot puts the stack in (replacing what was there), a fusion slot onto the other swaps them, a fusion slot dropped
/// anywhere else takes it out. Elementals the Conflux rank does not allow, and non-elementals, are greyed and cannot be
/// dragged; hovering one shows why on the status line, which otherwise only shows why a fusion is blocked.
/// Trim is always on (<see cref="Homm3ConfluxFusionRuntime.BuildTrimmedPlan"/>): the fusion slots show how many of each
/// stack go in, the army row keeps the surplus. When the army has no slot for the fused stack, the status line warns that
/// the weaker parent's leftover will be lost and Fuse turns the buttons into Cancel (back) / Confirm (user 2026-11-15).
/// Cancel and Esc close the panel and refund the cast. Fuse re-reads the
/// live army and writes it (see <see cref="Homm3ConfluxFusionRuntime.TryFuse"/>).
/// Modal: the Artificing picker's input gates hold the adventure map while it is open.
/// The "?" button opposite the skill icon opens <see cref="Homm3ConfluxFusionGlossary"/> on top; while it is open it gets
/// the input (its Esc closes only the glossary) and the panel is left as it was.
/// Result preview (user 2026-11-16, mockup design B "tooltip only"): hovering the result slot shows a tooltip with the
/// fused unit's name, count, stats and abilities from the glossary's entry (<see cref="Homm3ConfluxFusionGlossary.TryGetEntry"/>)
/// and the inputs of the plan Fuse will write; right-click on the result opens the glossary on that entry. The tooltip is
/// its own layer, built on the first hover of a plan and only shown / hidden after that (see <see cref="TickResultTip"/>).
/// Proof tier: source + build; the tooltip is runtime-unproven.
/// </summary>
internal static class Homm3ConfluxFusionPanel
{
	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_CONFLUX_ELEMENTAL_FUSION";

	private static bool _typeRegistered;
	private static bool _typeFailed;
	private static GameObject _canvasObject;
	private static RectTransform _window;
	private static Homm3ConfluxFusionRuntime.Session _session;
	private static int _openFrame;
	private static string[] _slotSid = new string[Homm3PartyArmyWriter.MaxArmySlots];
	private static int[] _slotCount = new int[Homm3PartyArmyWriter.MaxArmySlots];
	/// <summary>Army slot index in fusion slot A / B, or -1.</summary>
	private static readonly int[] _in = { -1, -1 };
	/// <summary>A refusal from the last Fuse, shown until the panel changes.</summary>
	private static string _status;
	/// <summary>Why the current plan is blocked (null when Fuse is enabled, or fewer than two stacks are in).</summary>
	private static string _blocked;
	/// <summary>The plan drops a leftover (army full) and the player pressed Fuse once: Cancel / Confirm now ask.</summary>
	private static bool _confirmLoss;
	/// <summary>The current plan's lost-leftover warning (army full), shown in the status line.</summary>
	private static string _lossWarning;
	private static TextMeshProUGUI _statusText;
	/// <summary>The result slot's hit box, and the plan whose fused unit it shows (null: empty result slot, no tooltip).</summary>
	private static RectTransform _resultRect;
	private static Homm3ConfluxFusionRuntime.Plan _tipPlan;
	/// <summary>The result tooltip layer for <see cref="_tipPlan"/>, built on the first hover; gone with every Build().</summary>
	private static RectTransform _tip;
	private static readonly List<(RectTransform Rect, int Index, UnityImage Hover, string Hint, bool Draggable)> Cards = new();
	private static readonly List<(RectTransform Rect, int Which, UnityImage Hover)> FusionSlots = new();
	private static readonly List<(UnityImage Image, Sprite Normal, Sprite Hover, Action Click)> Buttons = new();
	private static readonly Dictionary<string, Sprite> PanelSprites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissingSprites = new(StringComparer.Ordinal);

	// Drag, as Homm3DungeonWarCaptivesWindow.TickRecruit: press on a stack, move past RecruitDragThreshold to lift a ghost,
	// release over a slot. Fusion = false: the press is on army card Index; true: on fusion slot Index (0 = A, 1 = B).
	private static (bool Fusion, int Index)? _press;
	private static Vector2 _pressAt;
	private static bool _dragging;
	private static RectTransform _ghost;

	internal static bool IsOpen => _session != null;

	internal static bool Open(Homm3ConfluxFusionRuntime.Session session, out string failReason)
	{
		failReason = null;
		if (_session != null)
		{
			failReason = "panel already open";
			return false;
		}
		try
		{
			if (!Homm3PartyArmyWriter.TryReadArmy(session.LogicHero, session.DataHero, out var sids, out var counts, out _, out failReason))
				return false;
			if (!EnsureCanvas(out failReason))
				return false;
			_session = session;
			_openFrame = Time.frameCount;
			_slotSid = sids;
			_slotCount = counts;
			_in[0] = _in[1] = -1;
			_status = null;
			_confirmLoss = false;
			ResetDrag();
			ResolvePanelSprites();
			Homm3TowerArtificingPickerInputBlock.Begin();
			Build();
			return true;
		}
		catch (Exception ex)
		{
			failReason = "panel build failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			_session = null;
			Homm3TowerArtificingPickerInputBlock.End();
			DestroyCanvas();
			return false;
		}
	}

	private static bool Eligible(int i) => _slotSid[i] != null && Homm3ConfluxFusionRuntime.EligibilityBlock(_session.Config, _session.Rank, _slotSid[i]) == null;

	private static void ResetDrag()
	{
		_press = null;
		_dragging = false;
		_ghost = null;
	}

	private static void ClearState()
	{
		Cards.Clear();
		FusionSlots.Clear();
		Buttons.Clear();
		_statusText = null;
		_resultRect = null;
		_tipPlan = null;
		_tip = null;
		ResetDrag();
	}

	private static void Close(bool refund, string why)
	{
		var session = _session;
		_session = null;
		Homm3ConfluxFusionGlossary.Close();
		Homm3ConfluxFusionGlossary.ForgetOpenButton();
		ClearState();
		Homm3TowerArtificingPickerInputBlock.End();
		DestroyCanvas();
		if (refund)
			Homm3ConfluxFusionRuntime.Refund(session, why);
	}

	// ---------------------------------------------------------------- input (host Update)

	internal static void Tick()
	{
		if (_session == null || _canvasObject == null)
			return;
		try
		{
			Homm3TowerArtificingPickerInputBlock.Hold();
			if (Time.frameCount > _openFrame)
				Homm3ConfluxFusionRuntime.LogChargeObserved(_session);
			if (Homm3ConfluxFusionGlossary.IsOpen)
			{
				Homm3ConfluxFusionGlossary.Tick(Input.mousePosition);
				return;
			}
			if (Input.GetKeyDown(KeyCode.Escape))
			{
				// Esc first backs out of a pending lost-leftover confirm, then closes.
				if (_confirmLoss)
				{
					_confirmLoss = false;
					Build();
					return;
				}
				Close(true, "Esc");
				return;
			}
			var mouse = (Vector2)Input.mousePosition;
			TickHover(mouse);
			TickResultTip(mouse);
			if (_session == null || Homm3ConfluxFusionGlossary.IsOpen)
				return;
			TickDrag(mouse);
		}
		catch (Exception ex)
		{
			Homm3ConfluxFusionRuntime.LogWarning("panel input failed; closing with a refund: " + ex.GetBaseException().Message);
			Close(true, "panel error");
		}
	}

	private static void TickHover(Vector2 mouse)
	{
		foreach (var (image, normal, hover, _) in Buttons)
		{
			var sprite = !_dragging && Over(image ? image.rectTransform : null, mouse) ? hover : normal;
			if (sprite != null && image.sprite != sprite)
				image.sprite = sprite;
		}
		Homm3ConfluxFusionGlossary.TickOpenButton(mouse, _dragging);
		string hint = null;
		foreach (var card in Cards)
		{
			var on = Over(card.Rect, mouse);
			if (card.Hover != null)
				card.Hover.enabled = on && !_dragging && card.Draggable;
			if (on && !_dragging)
				hint = card.Hint;
		}
		// A fusion slot lights up as a drop target while dragging, and as a grab handle when it holds a stack.
		var target = FusionSlotAt(mouse);
		foreach (var slot in FusionSlots)
		{
			if (slot.Hover != null)
				slot.Hover.enabled = target == slot.Which && (_dragging || _in[slot.Which] >= 0);
		}
		if (_statusText != null)
		{
			var text = hint ?? _status ?? _blocked ?? _lossWarning ?? "";
			if (_statusText.text != text)
			{
				_statusText.text = text;
				_statusText.color = hint != null ? P.TipNote : P.TipWarn;
			}
		}
	}

	/// <summary>
	/// Result preview: the tooltip shows only while the mouse is on the result slot (never while dragging), so it cannot
	/// take a drop or flicker (the test is on the slot, not on the tooltip, and nothing here is a raycast target).
	/// Right-click on the result opens the glossary on that fusion. A tooltip fault drops the tooltip, never the panel.
	/// </summary>
	private static void TickResultTip(Vector2 mouse)
	{
		var plan = _tipPlan;
		var on = !_dragging && plan?.Pair != null && Over(_resultRect, mouse);
		if (on && _tip == null)
		{
			try
			{
				_tip = BuildResultTip(plan);
			}
			catch (Exception ex)
			{
				Homm3ConfluxFusionRuntime.LogWarning("result tooltip failed; no tooltip for this plan: " + ex.GetType().Name + ": " + ex.GetBaseException().Message);
			}
			if (_tip == null)
			{
				_tipPlan = null;
				return;
			}
		}
		if (_tip != null && _tip.gameObject.activeSelf != on)
			_tip.gameObject.SetActive(on);
		if (on && Input.GetMouseButtonDown(1))
			OpenGlossary(plan.Pair.Fused);
	}

	private static void TickDrag(Vector2 mouse)
	{
		if (Input.GetMouseButtonDown(0))
		{
			foreach (var (image, _, _, click) in Buttons)
			{
				if (Over(image ? image.rectTransform : null, mouse))
				{
					click();
					return;
				}
			}
			if (FusionSlotAt(mouse) is { } which && _in[which] >= 0)
			{
				_press = (true, which);
				_pressAt = mouse;
				_dragging = false;
				return;
			}
			foreach (var card in Cards)
			{
				if (card.Draggable && Over(card.Rect, mouse))
				{
					_press = (false, card.Index);
					_pressAt = mouse;
					_dragging = false;
					return;
				}
			}
			return;
		}

		if (_press is not { } src)
			return;
		if (Input.GetMouseButton(0))
		{
			if (!_dragging && (mouse - _pressAt).magnitude >= W.RecruitDragThreshold)
			{
				_dragging = true;
				var sid = _slotSid[src.Fusion ? _in[src.Index] : src.Index];
				_ghost = Homm3DungeonWarCaptivesWindow.NewDragGhost(_window, PanelSprite(W.SpriteRecruitCardSelected), sid);
			}
			if (_dragging && _ghost != null && RectTransformUtility.ScreenPointToLocalPointInRectangle(_window, mouse, null, out var local))
				_ghost.anchoredPosition = local;
			return;
		}

		// Released. A click (no drag) does nothing: stacks move by dragging only.
		var dragged = _dragging;
		ResetDrag();
		if (!dragged)
			return;
		Drop(src, FusionSlotAt(mouse));
	}

	/// <summary>
	/// Army card onto a fusion slot: that stack goes in (replacing the slot's stack). Fusion slot onto the other: swap.
	/// Fusion slot anywhere else: taken out. Everything else: nothing. Always rebuilds (the ghost goes with the old tree).
	/// </summary>
	private static void Drop((bool Fusion, int Index) src, int? onto)
	{
		if (!src.Fusion)
		{
			if (onto is { } t && Eligible(src.Index))
			{
				if (_in[1 - t] == src.Index)
					_in[1 - t] = _in[t];
				_in[t] = src.Index;
			}
		}
		else if (onto is { } t)
		{
			if (t != src.Index)
				(_in[0], _in[1]) = (_in[1], _in[0]);
		}
		else
		{
			_in[src.Index] = -1;
		}
		_status = null;
		_confirmLoss = false;
		Build();
	}

	private static int? FusionSlotAt(Vector2 mouse)
	{
		foreach (var slot in FusionSlots)
		{
			if (Over(slot.Rect, mouse))
				return slot.Which;
		}
		return null;
	}

	/// <summary>Fuse button: a plan that drops a leftover (army full) first asks for Confirm.</summary>
	private static void PressFuse()
	{
		var plan = CurrentPlan();
		if (plan != null && plan.Blocked == null && plan.LostCount > 0)
		{
			_confirmLoss = true;
			Build();
			return;
		}
		Fuse(false);
	}

	private static void Fuse(bool acceptLoss)
	{
		_confirmLoss = false;
		if (Homm3ConfluxFusionRuntime.TryFuse(_session, _in[0], _in[1], acceptLoss, out var message))
		{
			Close(false, "fused");
			return;
		}
		// Refused: the army may have changed under the panel; show the live one again.
		if (Homm3PartyArmyWriter.TryReadArmy(_session.LogicHero, _session.DataHero, out var sids, out var counts, out _, out _))
		{
			_slotSid = sids;
			_slotCount = counts;
			for (var k = 0; k < 2; k++)
			{
				if (_in[k] >= 0 && !Eligible(_in[k]))
					_in[k] = -1;
			}
		}
		_status = message;
		Build();
	}

	private static Homm3ConfluxFusionRuntime.Plan CurrentPlan()
	{
		if (_in[0] < 0 || _in[1] < 0)
			return null;
		return Homm3ConfluxFusionRuntime.BuildTrimmedPlan(_session.Config, _session.Rank, _slotSid, _slotCount, _in[0], _in[1]);
	}

	// ---------------------------------------------------------------- build

	private static void Build()
	{
		ClearState();
		foreach (var child in _window.GetComponentsInChildren<RectTransform>(true))
		{
			if (child != null && child != _window && child.parent == _window)
				UnityObject.Destroy(child.gameObject);
		}
		var w = W.RecruitWidth;
		var h = L.Height;
		_window.sizeDelta = new Vector2(w, h);
		var plate = new Color(0.08f, 0.1f, 0.15f, 0.98f);

		// Popup_full, as the War Captives recruit panel draws it.
		PImage(W.SpriteRecruitBack, 0f, 0f, w, h, plate);
		PSliced(W.SpriteRecruitGradient, 0f, 0f, w, h, 1f, Color.clear);
		PImage(W.SpriteRecruitLightBack, (w - W.RecruitBandWidth) / 2f, W.RecruitHeaderHeight / 2f, W.RecruitBandWidth, W.RecruitTopBandHeight, Color.clear);
		PImage(W.SpriteRecruitLightBack, (w - W.RecruitBandWidth) / 2f, h - W.RecruitBottomBandHeight - W.RecruitFrameInset, W.RecruitBandWidth, W.RecruitBottomBandHeight, Color.clear);
		PSliced(W.SpriteRecruitSeparator, (w - W.RecruitSeparatorWidth) / 2f, L.ButtonY - W.RecruitSeparatorHeight / 2f, W.RecruitSeparatorWidth, W.RecruitSeparatorHeight, 1f, Color.clear);
		PSliced(W.SpriteRecruitBackFrame, 0f, 0f, w, h, 1f, Color.clear);
		PSliced(W.SpriteRecruitFrame, 0f, 0f, w, h, 1f, new Color(0.55f, 0.47f, 0.3f, 0.6f));
		var c = W.RecruitCorner;
		PImage(W.SpriteRecruitCorner, 0f, 0f, c, c, Color.clear);
		Flip(PImage(W.SpriteRecruitCorner, w - c, 0f, c, c, Color.clear), true, false);
		Flip(PImage(W.SpriteRecruitCorner, 0f, h - c, c, c, Color.clear), false, true);
		Flip(PImage(W.SpriteRecruitCorner, w - c, h - c, c, c, Color.clear), true, true);
		PCentered(W.SpriteRecruitDecorFooter, w / 2f, h - W.RecruitDecorFooterHeight / 2f, W.RecruitDecorFooterWidth, W.RecruitDecorFooterHeight, Color.clear);
		PSliced(W.SpriteRecruitHeader, -W.RecruitHeaderOverhang / 2f, 0f, w + W.RecruitHeaderOverhang, W.RecruitHeaderHeight, 1f, plate);
		var hy = W.RecruitHeaderHeight / 2f;
		PCentered(W.SpriteRecruitHeaderOrnament, w / 2f + W.RecruitOrnamentX, hy, W.RecruitOrnamentWidth, W.RecruitOrnamentHeight, Color.clear);
		Flip(PCentered(W.SpriteRecruitHeaderOrnament, w / 2f - W.RecruitOrnamentX, hy, W.RecruitOrnamentWidth, W.RecruitOrnamentHeight, Color.clear), true, false);
		PCentered(W.SpriteRecruitHeaderMetal, w / 2f + W.RecruitMetalX, hy, W.RecruitMetalWidth, W.RecruitMetalHeight, Color.clear);
		Flip(PCentered(W.SpriteRecruitHeaderMetal, w / 2f - W.RecruitMetalX, hy, W.RecruitMetalWidth, W.RecruitMetalHeight, Color.clear), true, false);
		PCentered(W.SpriteRecruitDecorHeader, w / 2f, W.RecruitDecorHeaderHeight / 2f - W.RecruitFrameInset, W.RecruitDecorHeaderWidth, W.RecruitDecorHeaderHeight, Color.clear);
		A.AddText(_window, P.FontBook, P.SizeSubHeader, "Elemental Fusion", w / 2f - W.RecruitTitleWidth / 2f, 0f, W.RecruitTitleWidth, W.RecruitHeaderHeight, P.TipTitle, TextAlignmentOptions.Center);
		// The Conflux faction skill icon in the native ring, as a medallion on the header's left end.
		if (Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(L.SkillIconKey, out var icon) && icon)
		{
			var image = A.AddSpriteImage(_window, "SkillIcon", icon, L.IconCenterX - L.IconSize / 2f, hy - L.IconSize / 2f, L.IconSize, L.IconSize);
			image.preserveAspect = true;
		}
		A.AddCentered(_window, P.SpritePanelRing, L.IconCenterX, hy, L.IconRing, L.IconRing, P.TipTitle);
		// Fusion Glossary ("?" database button), mirrored opposite the skill icon.
		var glossary = Homm3ConfluxFusionGlossary.AddOpenButton(_window, w - L.IconCenterX - Homm3ConfluxFusionGlossaryLayout.OpenButtonInset, hy);
		Buttons.Add((glossary.Image, glossary.Normal, glossary.Hover, OpenGlossary));

		// The trimmed plan decides how many of each stack go in; until both slots hold a stack, a slot shows the whole stack.
		var plan = CurrentPlan();
		var ok = plan != null && plan.Blocked == null;
		_blocked = plan?.Blocked;
		_lossWarning = ok ? plan.LossWarning : null;
		if (_lossWarning == null)
			_confirmLoss = false;
		var taken = new int[2];
		for (var k = 0; k < 2; k++)
			taken[k] = _in[k] < 0 ? 0 : ok ? (k == 0 ? plan.InA : plan.InB) : _slotCount[_in[k]];

		// Army row: a stack in a fusion slot keeps only its surplus here (an empty slot when all of it goes in).
		for (var i = 0; i < Homm3PartyArmyWriter.MaxArmySlots; i++)
			BuildArmySlot(i, i == _in[0] ? taken[0] : i == _in[1] ? taken[1] : 0, i == _in[0] || i == _in[1]);

		// Fusion row: A + B = fused.
		BuildFusionSlot(0, L.RecipeAX, taken[0]);
		CenteredText("+", L.RecipePlusX, L.RecipeRowY, P.SizeBigNumbers, P.TipTitle);
		BuildFusionSlot(1, L.RecipeBX, taken[1]);
		CenteredText("=", L.RecipeEqualsX, L.RecipeRowY, P.SizeBigNumbers, P.TipTitle);
		var shown = plan != null && plan.Pair != null && plan.ValueF > 0;
		BuildResultSlot(shown ? plan.Pair.Fused : null, ok ? plan.Fused : 0);
		_tipPlan = shown ? plan : null;
		_tip = null;

		_statusText = A.AddText(_window, P.FontMedium, P.SizeSmall, _status ?? _blocked ?? _lossWarning ?? "", W.RecruitTextInset, L.StatusY, w - 2f * W.RecruitTextInset, W.RecruitLineHeight, P.TipWarn, TextAlignmentOptions.Center);

		// Cancel, the confirming Fuse.
		var bw = W.RecruitButtonWidth;
		var bx = (w - 2f * bw - W.RecruitButtonGap) / 2f;
		var by = L.ButtonY - W.RecruitButtonHeight / 2f;
		if (_confirmLoss)
		{
			// Army full: the warning names the leftover that will be lost; Cancel backs out, Confirm fuses anyway.
			AddButton("Cancel", bx, by, bw, W.SpriteRecruitButton, W.SpriteRecruitButtonHover, true, () =>
			{
				_confirmLoss = false;
				Build();
			});
			AddButton("Confirm", bx + bw + W.RecruitButtonGap, by, bw, W.SpriteRecruitButton, W.SpriteRecruitButtonHover, ok, () => Fuse(true));
		}
		else
		{
			AddButton("Cancel", bx, by, bw, W.SpriteRecruitButton, W.SpriteRecruitButtonHover, true, () => Close(true, "Cancel"));
			AddButton("Fuse", bx + bw + W.RecruitButtonGap, by, bw, W.SpriteRecruitButton, W.SpriteRecruitButtonHover, ok, PressFuse);
		}
	}

	private static void OpenGlossary() => OpenGlossary(null);

	/// <summary>Opens the glossary over the panel; on <paramref name="selectSid"/>'s entry when given (result right-click).</summary>
	private static void OpenGlossary(string selectSid)
	{
		ResetDrag();
		if (_tip != null)
			_tip.gameObject.SetActive(false);
		if (selectSid == null)
			Homm3ConfluxFusionGlossary.Open(_window.parent, _session.Config);
		else
			Homm3ConfluxFusionGlossary.Open(_window.parent, _session.Config, selectSid);
	}

	/// <summary>
	/// The result tooltip for a plan with a known pair, hidden; null when the glossary has no entry for the fused unit.
	/// Everything about the unit comes from the glossary entry, the counts from the plan. A blocked plan says what the
	/// pair would make and why it cannot be fused now (the plan's own reason), with no count and no inputs.
	/// Flat plates only (no looked-up sprites); placed beside the result slot, flipped / clamped to stay on the canvas.
	/// </summary>
	private static RectTransform BuildResultTip(Homm3ConfluxFusionRuntime.Plan plan)
	{
		var e = Homm3ConfluxFusionGlossary.TryGetEntry(_session.Config, plan.Pair.Fused);
		if (e == null || _window == null || _canvasObject == null)
			return null;
		var ok = plan.Blocked == null;
		var tw = L.TipWidth;
		var pad = L.TipPad;
		var iw = tw - 2f * pad;
		var tip = A.NewRect("ResultTip", _window);
		var back = A.NewImage("Back", tip, null, L.TipBack);
		var edges = new UnityImage[4];
		for (var i = 0; i < edges.Length; i++)
			edges[i] = A.NewImage("Edge", tip, null, L.TipEdge);

		var title = ok ? e.Name + "  \u00d7" + N(plan.Fused) : e.Name;
		A.AddText(tip, P.FontBook, P.SizeSubHeader, title, pad, 10f, iw, 28f, e.Stage == 2 ? Homm3ConfluxFusionGlossaryLayout.Stage2 : P.TipTitle, TextAlignmentOptions.Left);
		var traits = (e.Stage == 2 ? "Stage II fusion" : "Fusion") + " \u00b7 " + (e.Ranged ? "Ranged" : "Melee") + (e.Flying ? " \u00b7 Flying" : "")
		             + " \u00b7 needs " + Homm3ConfluxFusionRuntime.RankName(e.Rank) + " Conflux";
		A.AddText(tip, P.FontMedium, L.TipTextSmall, traits, pad, 40f, iw, 20f, P.TipNote, TextAlignmentOptions.Left);
		var stats = new[]
		{
			("Health", e.HasStats ? N(e.Hp) : "\u2013"), ("Attack", e.HasStats ? N(e.Attack) : "\u2013"), ("Defence", e.HasStats ? N(e.Defence) : "\u2013"),
			("Damage", e.HasStats ? N(e.DamageMin) + "\u2013" + N(e.DamageMax) : "\u2013"), ("Speed", e.HasStats ? N(e.Speed) : "\u2013"), ("Initiative", e.HasStats ? N(e.Initiative) : "\u2013"),
		};
		var colW = iw / 3f;
		for (var i = 0; i < stats.Length; i++)
		{
			var sx = pad + (i % 3) * colW;
			var sy = 70f + (i / 3) * L.TipStatPitch;
			A.AddText(tip, P.FontMedium, L.TipText, stats[i].Item1, sx, sy, L.TipStatLabel, 24f, P.TipNote, TextAlignmentOptions.Left);
			A.AddText(tip, P.FontBook, L.TipText, stats[i].Item2, sx + L.TipStatLabel, sy, colW - L.TipStatLabel, 24f, P.TipBody, TextAlignmentOptions.Left);
		}
		var y = 70f + 2f * L.TipStatPitch + 2f;
		if (ok)
		{
			var from = "From " + N(plan.InA) + " " + TipUnitName(plan.SidA) + " + " + N(plan.InB) + " " + TipUnitName(plan.SidB);
			A.AddText(tip, P.FontMedium, L.TipTextSmall, from, pad, y, iw, 20f, P.TipBody, TextAlignmentOptions.Left);
			y += 26f;
		}
		else
		{
			y += TipWrapped(tip, P.FontMedium, "Cannot be fused now: " + plan.Blocked, pad, y, iw, 3, P.TipWarn) + 8f;
		}
		var shown = 0;
		foreach (var card in e.Cards)
		{
			if (shown == L.TipMaxAbilities)
				break;
			var icon = Homm3ConfluxFusionGlossary.AbilityIcon(card.Icon);
			if (icon != null)
				A.AddSpriteImage(tip, "AbilityIcon", icon, pad, y + 2f, L.TipIcon, L.TipIcon).preserveAspect = true;
			A.AddText(tip, P.FontMedium, L.TipText, card.Name, pad + L.TipAbilityTextX, y, iw - L.TipAbilityTextX, 20f, P.TipTitle, TextAlignmentOptions.Left);
			var h = string.IsNullOrEmpty(card.Text) ? 0f : TipWrapped(tip, P.FontRegular, card.Text, pad + L.TipAbilityTextX, y + 21f, iw - L.TipAbilityTextX, 3, P.TipBody);
			y += Math.Max(21f + h, L.TipIcon + 2f) + 8f;
			shown++;
		}
		if (e.Cards.Count == 0)
		{
			A.AddText(tip, P.FontMedium, L.TipTextSmall, "No special abilities.", pad, y, iw, 20f, P.TipNote, TextAlignmentOptions.Left);
			y += 26f;
		}
		else if (shown < e.Cards.Count)
		{
			A.AddText(tip, P.FontMedium, L.TipTextSmall, "+" + (e.Cards.Count - shown) + " more", pad, y, iw, 20f, P.TipNote, TextAlignmentOptions.Left);
			y += 26f;
		}
		A.AddText(tip, P.FontMedium, L.TipTextSmall, "Right-click: open in the Fusion Glossary", pad, y + 2f, iw, 20f, P.TipNote, TextAlignmentOptions.Left);
		var th = y + 32f;

		// Beside the result slot, on its right; on its left when the right side would leave the canvas; then clamped.
		// Window space to canvas space: the window is centred on the canvas.
		var canvas = _canvasObject.GetComponent<RectTransform>().rect;
		var left = canvas.width / 2f - W.RecruitWidth / 2f;
		var top = canvas.height / 2f - L.Height / 2f;
		var x = L.RecipeFusedX + W.RecruitSlotBackWidth / 2f + L.TipGap;
		if (left + x + tw > canvas.width - L.TipMargin)
			x = L.RecipeFusedX - W.RecruitSlotBackWidth / 2f - L.TipGap - tw;
		x = Math.Max(L.TipMargin - left, Math.Min(x, canvas.width - L.TipMargin - tw - left));
		var ty = L.RecipeRowY - L.TipRise;
		ty = Math.Max(L.TipMargin - top, Math.Min(ty, canvas.height - L.TipMargin - th - top));
		A.Place(tip, x, ty, tw, th);
		A.Place(back.rectTransform, 0f, 0f, tw, th);
		A.Place(edges[0].rectTransform, 0f, 0f, tw, 1f);
		A.Place(edges[1].rectTransform, 0f, th - 1f, tw, 1f);
		A.Place(edges[2].rectTransform, 0f, 0f, 1f, th);
		A.Place(edges[3].rectTransform, tw - 1f, 0f, 1f, th);
		tip.gameObject.SetActive(false);
		return tip;
	}

	/// <summary>A parent's name as the glossary lists it (a stage I fusion by its fused name, an elemental by its unit name).</summary>
	private static string TipUnitName(string sid) => Homm3ConfluxFusionGlossary.TryGetEntry(_session.Config, sid)?.Name ?? Homm3UnitDisplayNames.Resolve(sid);

	/// <summary>Wrapped tooltip text of at most <paramref name="maxLines"/> lines, its box shrunk to the text; returns the height used.</summary>
	private static float TipWrapped(RectTransform tip, string font, string text, float x, float y, float w, int maxLines, Color color)
	{
		var room = maxLines * L.TipTextSmall * P.LineSpacing + 4f;
		var label = A.AddText(tip, font, L.TipTextSmall, text, x, y, w, room, color, TextAlignmentOptions.TopLeft, true);
		var h = Math.Min(room, A.MeasureHeight(label, w, room) + 2f);
		if (label != null)
			label.rectTransform.sizeDelta = new Vector2(w, h);
		return h;
	}

	private static void CenteredText(string text, float cx, float cy, float size, Color color)
	{
		A.AddText(_window, P.FontBook, size, text, cx - L.GlyphBox / 2f, cy - L.GlyphBox / 2f, L.GlyphBox, L.GlyphBox, color, TextAlignmentOptions.Center);
	}

	private static void BuildArmySlot(int i, int taken, bool inFusion)
	{
		var cx = W.RecruitSlotFirstX + i * W.RecruitSlotPitch;
		var cy = L.ArmyRowY;
		var hit = PCentered(W.SpriteRecruitSlotBack, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, new Color(0.06f, 0.08f, 0.12f, 1f));
		var sid = _slotSid[i];
		var left = sid == null ? 0 : _slotCount[i] - taken;
		if (left <= 0)
		{
			PCentered(W.SpriteRecruitSlotEmpty, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, Color.clear);
			return;
		}
		var block = Homm3ConfluxFusionRuntime.EligibilityBlock(_session.Config, _session.Rank, sid);
		// Ineligible stacks: the whole card (frame, portrait, count plate) multiplied grey, like a native disabled control,
		// so the card's own silhouette stays (no square overlay).
		Color? tint = block != null ? L.IneligibleTint : null;
		Tint(PCentered(W.SpriteRecruitCard, cx, cy, W.RecruitCardWidth, W.RecruitCardHeight, new Color(0.15f, 0.17f, 0.22f, 1f)), tint);
		AddPortrait(sid, cx, cy, tint);
		Tint(PCentered(W.SpriteRecruitCountOverlay, cx, cy + W.RecruitCountOffset, W.RecruitCountWidth, W.RecruitCountHeight, new Color(0f, 0f, 0f, 0.6f)), tint);
		A.AddText(_window, P.FontMedium, P.SizeMain, N(left), cx - W.RecruitSlotWidth / 2f, cy + W.RecruitAmountOffset - W.RecruitLineHeight / 2f, W.RecruitSlotWidth, W.RecruitLineHeight, block != null ? P.ButtonTextDisabled : P.TipTitle, TextAlignmentOptions.Center);
		var hover = PCentered(W.SpriteRecruitCardHover, cx, cy, W.RecruitCardWidth, W.RecruitCardHeight, Color.clear);
		hover.enabled = false;
		// A surplus left behind by the trim is not a separate stack: only whole stacks outside the fusion drag.
		Cards.Add((hit.rectTransform, i, hover, block != null ? Homm3UnitDisplayNames.Resolve(sid) + ": " + block : null, block == null && !inFusion));
	}

	/// <summary>Fusion slot A (0) or B (1): a drop target; when it holds a stack, the count that goes in, draggable out.</summary>
	private static void BuildFusionSlot(int which, float cx, int count)
	{
		var cy = L.RecipeRowY;
		var hit = PCentered(W.SpriteRecruitSlotBack, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, new Color(0.06f, 0.08f, 0.12f, 1f));
		var slot = _in[which];
		UnityImage hover;
		if (slot < 0)
		{
			PCentered(W.SpriteRecruitSlotEmpty, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, Color.clear);
			hover = PCentered(W.SpriteRecruitSlotEmptyHover, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, Color.clear);
		}
		else
		{
			var sid = _slotSid[slot];
			PCentered(W.SpriteRecruitCardSelected, cx, cy, W.RecruitCardWidth, W.RecruitCardHeight, new Color(0.15f, 0.17f, 0.22f, 1f));
			AddPortrait(sid, cx, cy);
			PCentered(W.SpriteRecruitCountOverlay, cx, cy + W.RecruitCountOffset, W.RecruitCountWidth, W.RecruitCountHeight, new Color(0f, 0f, 0f, 0.6f));
			A.AddText(_window, P.FontMedium, P.SizeMain, N(count), cx - W.RecruitSlotWidth / 2f, cy + W.RecruitAmountOffset - W.RecruitLineHeight / 2f, W.RecruitSlotWidth, W.RecruitLineHeight, P.TipTitle, TextAlignmentOptions.Center);
			hover = PCentered(W.SpriteRecruitCardHover, cx, cy, W.RecruitCardWidth, W.RecruitCardHeight, Color.clear);
		}
		hover.enabled = false;
		FusionSlots.Add((hit.rectTransform, which, hover));
	}

	/// <summary>The fused unit and how many the fusion makes (0, in the refusal colour, while it is blocked).</summary>
	private static void BuildResultSlot(string sid, int count)
	{
		var cx = L.RecipeFusedX;
		var cy = L.RecipeRowY;
		_resultRect = PCentered(W.SpriteRecruitSlotBack, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, new Color(0.06f, 0.08f, 0.12f, 1f)).rectTransform;
		if (sid == null)
		{
			PCentered(W.SpriteRecruitSlotEmpty, cx, cy, W.RecruitSlotBackWidth, W.RecruitSlotBackHeight, Color.clear);
			return;
		}
		PCentered(W.SpriteRecruitCard, cx, cy, W.RecruitCardWidth, W.RecruitCardHeight, new Color(0.15f, 0.17f, 0.22f, 1f));
		AddPortrait(sid, cx, cy);
		PCentered(W.SpriteRecruitCountOverlay, cx, cy + W.RecruitCountOffset, W.RecruitCountWidth, W.RecruitCountHeight, new Color(0f, 0f, 0f, 0.6f));
		A.AddText(_window, P.FontMedium, P.SizeMain, N(count), cx - W.RecruitSlotWidth / 2f, cy + W.RecruitAmountOffset - W.RecruitLineHeight / 2f, W.RecruitSlotWidth, W.RecruitLineHeight, count > 0 ? P.TipTitle : P.CostBad, TextAlignmentOptions.Center);
	}

	private static void AddButton(string label, float x, float y, float bw, string normal, string hover, bool enabled, Action click)
	{
		var bh = W.RecruitButtonHeight;
		PImage(W.SpriteRecruitButtonBase, x, y, bw, bh, Color.clear);
		var image = PSliced(enabled ? normal : W.SpriteRecruitButtonDisabled, x, y, bw, bh, W.RecruitButtonSliceMultiplier, enabled ? new Color(0.35f, 0.26f, 0.15f, 1f) : new Color(0.2f, 0.2f, 0.2f, 1f));
		if (!enabled && image.sprite == null)
			image.color = W.DisabledRowTint;
		A.AddText(_window, P.FontBook, P.SizeSubHeader, label, x, y, bw, bh, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.Center);
		if (enabled)
			Buttons.Add((image, PanelSprite(normal), PanelSprite(hover), click));
	}

	/// <summary>Multiplies a sprite image by the tint (Image.color); flat fallbacks keep their colour.</summary>
	private static void Tint(UnityImage image, Color? tint)
	{
		if (tint is { } t && image != null && image.sprite != null)
			image.color = t;
	}

	/// <summary>Unit portrait inside the card's rounded mask, as the War Captives recruit panel draws it.</summary>
	private static void AddPortrait(string sid, float cx, float cy, Color? tint = null)
	{
		if (!TryUnitPortrait(sid, out var portrait))
		{
			A.AddText(_window, P.FontMedium, P.SizeSmall, Homm3UnitDisplayNames.Resolve(sid), cx - W.RecruitPortraitWidth / 2f, cy - W.RecruitPortraitHeight / 2f, W.RecruitPortraitWidth, W.RecruitPortraitHeight - 20f, P.TipNote, TextAlignmentOptions.Center, true);
			return;
		}
		var maskSprite = PanelSprite(W.SpriteRecruitPortraitMask);
		if (maskSprite == null)
		{
			var plain = A.AddSpriteImage(_window, "Portrait", portrait, cx - W.RecruitPortraitWidth / 2f, cy - W.RecruitPortraitHeight / 2f, W.RecruitPortraitWidth, W.RecruitPortraitHeight);
			plain.preserveAspect = true;
			Tint(plain, tint);
			return;
		}
		var mask = A.AddSpriteImage(_window, "PortraitMask", maskSprite, cx - W.RecruitPortraitWidth / 2f, cy - W.RecruitPortraitHeight / 2f, W.RecruitPortraitWidth, W.RecruitPortraitHeight);
		var m = mask.gameObject.AddComponent<Mask>();
		if (m != null)
			m.showMaskGraphic = false;
		var inner = A.NewImage("Portrait", mask.transform, portrait, Color.clear);
		A.Stretch(inner.rectTransform);
		inner.preserveAspect = false;
		Tint(inner, tint);
		var r = portrait.rect;
		if (r.width > 0f && r.height > 0f)
		{
			var k = Math.Max(W.RecruitPortraitWidth / r.width, W.RecruitPortraitHeight / r.height);
			inner.rectTransform.sizeDelta = new Vector2(r.width * k - W.RecruitPortraitWidth, r.height * k - W.RecruitPortraitHeight);
		}
	}

	private static bool TryUnitPortrait(string sid, out Sprite portrait)
	{
		if (Homm3CustomUiIconHook.TryResolveSprite(sid, out portrait) && portrait)
			return true;
		return Homm3NativeSpriteCatalogRegistrar.TryResolveNative(sid, out portrait) && portrait;
	}

	private static string N(long value) => value.ToString("N0", CultureInfo.InvariantCulture);

	private static bool Over(RectTransform rect, Vector2 mouse) => rect != null && RectTransformUtility.RectangleContainsScreenPoint(rect, mouse, null);

	// ---------------------------------------------------------------- sprites

	private static void ResolvePanelSprites()
	{
		var stale = PanelSprites.Count == 0;
		foreach (var sprite in PanelSprites.Values)
			stale |= !sprite;
		if (!stale)
			return;
		PanelSprites.Clear();
		var wanted = new HashSet<string>(W.RecruitSprites, StringComparer.Ordinal);
		var all = Resources.FindObjectsOfTypeAll<Sprite>();
		for (var i = 0; i < all.Length; i++)
		{
			var s = all[i];
			if (!s || s.name == null || !wanted.Contains(s.name))
				continue;
			if (!PanelSprites.TryGetValue(s.name, out var have) || !have || s.rect.width * s.rect.height > have.rect.width * have.rect.height)
				PanelSprites[s.name] = s;
		}
		var missing = new List<string>();
		foreach (var name in wanted)
		{
			if (!PanelSprites.ContainsKey(name) && LoggedMissingSprites.Add(name))
				missing.Add(name);
		}
		if (missing.Count > 0)
			Homm3ConfluxFusionRuntime.LogWarning("panel sprites not loaded, using flat fallbacks: " + string.Join(", ", missing));
	}

	private static Sprite PanelSprite(string name) => PanelSprites.TryGetValue(name, out var s) && s ? s : null;

	private static UnityImage PImage(string sprite, float x, float y, float w, float h, Color fallback)
	{
		var image = A.NewImage(sprite, _window, PanelSprite(sprite), fallback);
		A.Place(image.rectTransform, x, y, w, h);
		return image;
	}

	private static UnityImage PSliced(string sprite, float x, float y, float w, float h, float multiplier, Color fallback)
	{
		var image = PImage(sprite, x, y, w, h, fallback);
		if (image.sprite != null)
		{
			image.type = UnityImage.Type.Sliced;
			image.pixelsPerUnitMultiplier = multiplier;
			image.fillCenter = true;
		}
		return image;
	}

	private static UnityImage PCentered(string sprite, float cx, float cy, float w, float h, Color fallback) => PImage(sprite, cx - w / 2f, cy - h / 2f, w, h, fallback);

	private static void Flip(UnityImage image, bool x, bool y)
	{
		var rect = image.rectTransform;
		var size = rect.sizeDelta;
		rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition += new Vector2(size.x / 2f, -size.y / 2f);
		rect.localScale = new Vector3(x ? -1f : 1f, y ? -1f : 1f, 1f);
	}

	// ---------------------------------------------------------------- canvas

	private static bool EnsureCanvas(out string failReason)
	{
		failReason = null;
		if (_canvasObject != null)
			return true;
		if (_typeFailed)
		{
			failReason = "panel host type failed to register earlier";
			return false;
		}
		if (!_typeRegistered)
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3ConfluxFusionPanelHost>();
				_typeRegistered = true;
			}
			catch (Exception ex)
			{
				_typeFailed = true;
				failReason = "panel host failed: " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}
		A.ResolveNativeSprites();
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
		if (canvas == null || scaler == null)
		{
			DestroyCanvas();
			failReason = "panel canvas could not be created";
			return false;
		}
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = P.SortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= P.ReferenceWidth / P.ReferenceHeight ? 1f : 0f;
		var canvasRect = go.GetComponent<RectTransform>();
		var block = A.NewImage("Block", canvasRect, null, new Color(0f, 0f, 0f, P.BlockAlpha));
		A.Stretch(block.rectTransform);
		block.raycastTarget = true;
		_window = A.NewRect("Window", canvasRect);
		_window.anchorMin = _window.anchorMax = new Vector2(0.5f, 0.5f);
		_window.pivot = new Vector2(0.5f, 0.5f);
		_window.anchoredPosition = Vector2.zero;
		_window.sizeDelta = new Vector2(W.RecruitWidth, L.Height);
		if (go.AddComponent<Homm3ConfluxFusionPanelHost>() == null)
		{
			DestroyCanvas();
			failReason = "panel host component could not be added";
			return false;
		}
		return true;
	}

	private static void DestroyCanvas()
	{
		var canvas = _canvasObject;
		_canvasObject = null;
		_window = null;
		if (canvas == null)
			return;
		try
		{
			UnityObject.Destroy(canvas);
		}
		catch
		{
		}
	}

	/// <summary>The host was destroyed under an open panel (should not happen: DontDestroyOnLoad): refund the cast.</summary>
	internal static void HostDestroyed()
	{
		if (_session == null)
			return;
		var session = _session;
		_session = null;
		_canvasObject = null;
		_window = null;
		Homm3ConfluxFusionGlossary.Forget();
		ClearState();
		Homm3TowerArtificingPickerInputBlock.End();
		Homm3ConfluxFusionRuntime.Refund(session, "panel destroyed");
	}
}

public sealed class Homm3ConfluxFusionPanelHost : MonoBehaviour
{
	public Homm3ConfluxFusionPanelHost(IntPtr ptr) : base(ptr) { }

	private void Update() => Homm3ConfluxFusionPanel.Tick();

	private void OnDestroy() => Homm3ConfluxFusionPanel.HostDestroyed();
}

/// <summary>
/// Geometry of the Elemental Fusion panel (window space: top-left origin, y down, 1920x1080 reference canvas). The shell,
/// army row, slot and button geometry come from <see cref="Homm3DungeonWarCaptivesWindowLayout"/> (the recruit panel).
/// tools/conflux_fusion/panel_mockup.py parses these constants; revise values here only.
/// </summary>
internal static class Homm3ConfluxFusionPanelLayout
{
	internal const string SkillIconKey = "skill_faction_homm3_conflux";
	internal const float Height = 468f;
	internal const float IconCenterX = 58f;
	internal const float IconRing = 58f;
	internal const float IconSize = 42f;
	internal const float ArmyRowY = 118f;
	internal const float RecipeRowY = 268f;
	internal const float RecipeAX = 195f;
	internal const float RecipePlusX = 299f;
	internal const float RecipeBX = 403f;
	internal const float RecipeEqualsX = 507f;
	internal const float RecipeFusedX = 611f;
	internal const float GlyphBox = 60f;
	internal const float StatusY = 334f;
	internal const float ButtonY = 425f;
	internal static readonly Color IneligibleTint = new(0.4f, 0.4f, 0.4f, 1f);

	// Result tooltip (hover on the result slot): a flat plate beside the slot, in window space like the rest.
	internal const float TipWidth = 430f;
	internal const float TipPad = 16f;
	internal const float TipGap = 13f;
	internal const float TipRise = 70f;
	internal const float TipMargin = 8f;
	internal const float TipText = 15f;
	internal const float TipTextSmall = 14f;
	internal const float TipStatPitch = 26f;
	internal const float TipStatLabel = 78f;
	internal const float TipIcon = 26f;
	internal const float TipAbilityTextX = 34f;
	internal const int TipMaxAbilities = 3;
	internal static readonly Color TipBack = new(0.047f, 0.063f, 0.102f, 0.96f);
	internal static readonly Color TipEdge = new(0.839f, 0.737f, 0.486f, 0.75f);
}
