using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Adventure army strip (BhHeroHUDPanel.slots) for heroes with Inferno Gating:
/// - a small hellgate toggle at the top-right corner of every filled slot (click: reserve / release);
/// - a reserved slot wears a burning frame while Gating is open, and a cold ember seal while it is closed;
/// - hovering the toggle explains the slot state and the reserve count (x / allowed).
/// Nothing is added to native containers: the frame is a raycast-off child of the slot, and the toggles live in one
/// mod-owned overlay under the root canvas (tracked to the slot corner each frame), so clicks never reach the native
/// slot and the native slot list/layout never sees a foreign child. Decorations are updated in place, not rebuilt.
/// Visuals are procedural (no bundle). Proof tier: source + build; owner approves the mockup before install.
/// </summary>
internal static class Homm3InfernoGatingArmyStripHud
{
	private const string FrameName = "HOMM3_INFERNO_GATING_FRAME";
	private const string ToggleName = "HOMM3_INFERNO_GATING_TOGGLE";
	private const string TooltipName = "HOMM3_INFERNO_GATING_TOOLTIP";
	private const string OverlayName = "HOMM3_INFERNO_GATING_OVERLAY";
	private const float ToggleSize = 22f;
	private const int FlameFrames = 8;
	private const int FrameTex = 128;

	private sealed class SlotView
	{
		internal Hex.Session.Hud.BhUnitUI Slot;
		internal int SlotId;
		internal int SlotPos;
		internal GameObject Frame;
		internal Image FrameImage;
		internal GameObject Fire;
		internal Image Ring;
		internal RectTransform[] Embers;
		internal Image[] EmberImages;
		internal float[] EmberPhase;
		internal float SlotW;
		internal float SlotH;
		internal GameObject Toggle;
		internal Image ToggleImage;
	}

	private sealed class PanelView
	{
		internal Component Panel;
		internal object LogicHero;
		internal DataHero DataHero;
		internal object HeroHint;
		internal string Signature;
		internal readonly List<SlotView> Slots = new();
	}

	private static readonly object Gate = new();
	private static readonly Dictionary<int, PanelView> Panels = new();
	private static ManualLogSource _log;
	private static bool _registered;
	private static bool _dirty;
	private static int _logged;
	private static Sprite[] _flameSprites;
	private static Sprite _sealSprite;
	// Portal-style edge light on the card (procedural) with a few faint embers drifting up off its top and sides.
	private const int EmberCount = 7;
	private const int EmberTex = 16;
	private static Sprite _emberSprite;
	private const float RingMargin = 0.14f; // glow spill outside the card, as a fraction of its width
	private const int RingTex = 128;
	private static float _ringAspect;
	private const int RingFrames = 16;
	private const float RingFps = 14f;
	private static Sprite[] _ringFrames;
	private static Sprite _toggleOpenSprite;
	private static Sprite _toggleIdleSprite;
	private static GameObject _tooltip;
	private static TextMeshProUGUI _tooltipText;
	private static SlotView _tooltipOwner;
	private static float _nextStateRead;
	private static float _nextRescan;
	private static readonly HashSet<string> LoggedReasons = new();
	private static GameObject _overlay;
	private static bool _loggedLayout;
	private static bool _loggedPanelHidden;
	private static bool _loggedTick;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		if (!Homm3InfernoGatingRuntime.StateRegistered)
		{
			_log?.LogWarning("HoMM3 Inferno Gating army-strip HUD not registered: Gating state runtime is not registered.");
			return;
		}
		try
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3InfernoGatingHudPump>();
			}
			catch (Exception ex)
			{
				_log?.LogDebug("HoMM3 Inferno Gating HUD pump already registered: " + ex.Message);
			}
			var go = new GameObject("Homm3InfernoGatingHudPump");
			go.AddComponent<Homm3InfernoGatingHudPump>();
			UnityEngine.Object.DontDestroyOnLoad(go);

			var panelType = typeof(Hex.Session.Hud.BhHeroHUDPanel);
			var patched = 0;
			var seen = new HashSet<MethodInfo>();
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
			foreach (var name in GameSymbols.ImportVisuals.HeroHudPanelRefresh.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var method = panelType.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method == null || method.ReturnType != typeof(void) || !seen.Add(method))
					continue;
				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3InfernoGatingArmyStripHud), nameof(PostfixPanelRefresh)) { priority = Priority.Last });
				patched++;
			}
			// The hero-argument refresh is the one the panel runs when its hero is (re)bound; the parameterless one can
			// run before the hero view is filled. Both feed Rebuild, and Tick re-checks the strip twice a second.
			foreach (var name in GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				foreach (var method in panelType.GetMethods(flags))
				{
					var parameters = method.GetParameters();
					if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void)
					    || parameters.Length != 1 || !IsSessionHeroType(parameters[0].ParameterType) || !seen.Add(method))
						continue;
					harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3InfernoGatingArmyStripHud), nameof(PostfixPanelHeroArgRefresh)) { priority = Priority.Last });
					patched++;
				}
			}
			if (patched == 0)
				throw new MissingMethodException("BhHeroHUDPanel refresh surface missing");
			_registered = true;
			_log?.LogInfo("HoMM3 Inferno Gating army-strip HUD registered (" + patched + " refresh postfix(es); slot toggles + flame frames).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Inferno Gating army-strip HUD not registered (reservations still apply, no UI): " + ex.GetBaseException().Message);
		}
	}

	internal static void NotifyStateChanged() => _dirty = true;

	private static void PostfixPanelRefresh(object __instance)
	{
		try
		{
			if (__instance is not Component panel || !panel)
				return;
			Rebuild(panel, null);
		}
		catch (Exception ex)
		{
			LogLimited("refresh failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixPanelHeroArgRefresh(object __instance, [HarmonyArgument(0)] object hero)
	{
		try
		{
			if (__instance is not Component panel || !panel)
				return;
			Rebuild(panel, hero);
		}
		catch (Exception ex)
		{
			LogLimited("hero refresh failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static bool IsSessionHeroType(Type type)
	{
		if (type == null || type.IsValueType)
			return false;
		foreach (var hint in GameSymbols.HeroMap.SessionHeroTypeHints)
		{
			if (!string.IsNullOrEmpty(hint) && (string.Equals(type.Name, hint, StringComparison.Ordinal) || string.Equals(type.FullName, hint, StringComparison.Ordinal)))
				return true;
		}
		return false;
	}

	private static void LogReason(string reason)
	{
		lock (LoggedReasons)
		{
			if (LoggedReasons.Count < 24 && LoggedReasons.Add(reason))
				_log?.LogInfo("HoMM3 Inferno Gating HUD: " + reason);
		}
	}

	private static Il2CppSystem.Collections.Generic.List<Hex.Session.Hud.BhUnitUI> ReadSlotList(Component panel)
	{
		var slots = ReadMember(panel, GameSymbols.ImportVisuals.HeroHudPanelUnitSlotsMembers);
		return ReadMember(slots, GameSymbols.ImportVisuals.UnitSlotsListMembers) as Il2CppSystem.Collections.Generic.List<Hex.Session.Hud.BhUnitUI>;
	}

	/// <summary>What the decorations depend on: the hero and each live slot's position, stack and visibility.</summary>
	private static string ComputeSignature(object sessionHero, Il2CppSystem.Collections.Generic.List<Hex.Session.Hud.BhUnitUI> list)
	{
		var sb = new System.Text.StringBuilder();
		sb.Append(sessionHero is Il2CppSystem.Object io ? io.Pointer.ToInt64() : 0L).Append('|');
		if (list == null)
			return sb.Append("nolist").ToString();
		for (var i = 0; i < list.Count; i++)
		{
			var ui = list[i];
			if (ui == null)
				continue;
			Hex.Session.Data.Unit unit = null;
			try
			{
				unit = ui.field_Private_Unit_0;
			}
			catch
			{
			}
			sb.Append(ui.GetInstanceID()).Append(':').Append(ui.gameObject.activeInHierarchy ? 1 : 0).Append(':')
			  .Append(unit == null ? -1 : unit.slotPos).Append(':').Append(unit == null ? 0 : unit.stacks).Append(';');
		}
		return sb.ToString();
	}

	private static void Rebuild(Component panel, object heroHint)
	{
		var key = panel.GetInstanceID();
		PanelView existing;
		lock (Gate)
			Panels.TryGetValue(key, out existing);
		if (heroHint == null)
			heroHint = Homm3FactorySplitAssemblyArmyStripHud.TryResolveSessionHeroFromPanel(panel) ?? existing?.HeroHint;
		var sessionHero = heroHint;
		var logicHero = ResolveLogicHero(sessionHero);
		var dataHero = Homm3InfernoGatingRuntime.ResolveDataHero(logicHero);
		if (dataHero == null && sessionHero != null
		    && Homm3FactorySplitAssemblyArmyStripHud.TryResolveDataHero(sessionHero, out var fallback, out _))
			dataHero = fallback;
		var rank = Homm3InfernoGatingRuntime.ResolveRank(dataHero);
		var list = ReadSlotList(panel);
		lock (Gate)
		{
			if (!Panels.TryGetValue(key, out var view))
			{
				view = new PanelView { Panel = panel };
				Panels[key] = view;
			}
			view.HeroHint = heroHint;
			view.LogicHero = logicHero ?? sessionHero;
			view.DataHero = dataHero;
			view.Signature = ComputeSignature(sessionHero, list);
			string skip = null;
			if (sessionHero == null)
				skip = "panel has no hero yet (waiting for the next refresh).";
			else if (dataHero == null)
				skip = "Data.Hero unresolved from " + (sessionHero.GetType().FullName ?? "?") + "; logic hero " + (logicHero?.GetType().FullName ?? "null") + ".";
			else if (rank <= 0)
				skip = "";
			else if (list == null)
				skip = "army strip slot list unresolved.";
			if (skip != null)
			{
				foreach (var slot in view.Slots)
					DestroySlot(slot);
				view.Slots.Clear();
				if (skip.Length > 0)
					LogReason(skip);
				return;
			}
			EnsureSprites();
			var keep = new List<SlotView>();
			for (var i = 0; i < list.Count; i++)
			{
				var ui = list[i];
				if (ui == null || !ui.gameObject.activeInHierarchy)
					continue;
				Hex.Session.Data.Unit unit = null;
				try
				{
					unit = ui.field_Private_Unit_0;
				}
				catch
				{
				}
				if (unit == null || unit.stacks <= 0)
					continue;
				var id = ui.GetInstanceID();
				var reuse = view.Slots.Find(x => x.SlotId == id && x.Frame && x.Toggle);
				if (reuse != null)
				{
					view.Slots.Remove(reuse);
					reuse.SlotPos = unit.slotPos;
					keep.Add(reuse);
				}
				else
				{
					keep.Add(CreateSlot(ui, unit.slotPos));
				}
			}
			foreach (var slot in view.Slots)
				DestroySlot(slot);
			view.Slots.Clear();
			view.Slots.AddRange(keep);
			LogReason("decorated " + view.Slots.Count + " army slot(s) for " + (dataHero.configSid ?? "?") + " (Gating rank " + rank + ").");
			if (!_loggedLayout && view.Slots.Count > 0)
			{
				_loggedLayout = true;
				LogLayout(panel, view.Slots[0]);
			}
		}
		_dirty = true;
	}

	private static object ResolveLogicHero(object sessionHero)
	{
		if (sessionHero == null)
			return null;
		if (Homm3InfernoGatingRuntime.ResolveDataHero(sessionHero) != null)
			return sessionHero;
		var fromWorld = Homm3InfernoGatingRuntime.ResolveLogicHeroFromWorldHero(sessionHero);
		if (fromWorld != null)
			return fromWorld;
		return ReadMember(sessionHero, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers)
		       ?? ReadMember(sessionHero, GameSymbols.HeroMap.SessionHeroLogicFields);
	}

	private static SlotView CreateSlot(Hex.Session.Hud.BhUnitUI ui, int slotPos)
	{
		var view = new SlotView { Slot = ui, SlotId = ui.GetInstanceID(), SlotPos = slotPos };
		var slotRect = ui.GetComponent<RectTransform>();

		var stale = ui.transform.Find(FrameName);
		if (stale)
			UnityEngine.Object.Destroy(stale.gameObject);
		view.Frame = new GameObject(FrameName);
		view.Frame.layer = ui.gameObject.layer;
		view.Frame.transform.SetParent(ui.transform, false);
		var frameRect = view.Frame.AddComponent<RectTransform>();
		frameRect.anchorMin = Vector2.zero;
		frameRect.anchorMax = Vector2.one;
		frameRect.pivot = new Vector2(0.5f, 0.5f);
		frameRect.offsetMin = new Vector2(-9f, -9f);
		frameRect.offsetMax = new Vector2(9f, 12f);
		view.FrameImage = view.Frame.AddComponent<Image>();
		view.FrameImage.raycastTarget = false;
		view.Frame.AddComponent<LayoutElement>().ignoreLayout = true;
		view.Frame.transform.SetAsLastSibling();
		view.Frame.SetActive(false);

		var overlay = EnsureOverlay(ui.transform);
		view.Toggle = new GameObject(ToggleName + "_" + slotPos);
		view.Toggle.layer = ui.gameObject.layer;
		view.Toggle.transform.SetParent(overlay ? overlay.transform : ui.transform, false);
		var toggleRect = view.Toggle.AddComponent<RectTransform>();
		toggleRect.pivot = new Vector2(0.5f, 0.5f);
		toggleRect.sizeDelta = new Vector2(ToggleSize, ToggleSize);
		view.ToggleImage = view.Toggle.AddComponent<Image>();
		// Raycast target only when it sits in the mod overlay (no native handler above it: the click is swallowed);
		// as a fallback child of the slot it must stay click-through.
		view.ToggleImage.raycastTarget = overlay;
		view.ToggleImage.preserveAspect = true;
		view.Toggle.AddComponent<LayoutElement>().ignoreLayout = true;
		TrackSlotCorner(view, slotRect);
		return view;
	}

	/// <summary>One mod-owned, full-screen, non-blocking container under the slot's root canvas.</summary>
	private static GameObject EnsureOverlay(Transform near)
	{
		var canvas = near ? near.GetComponentInParent<Canvas>() : null;
		var root = canvas ? canvas.rootCanvas.transform : null;
		if (!root)
			return null;
		if (_overlay && _overlay.transform.parent == root)
			return _overlay;
		if (_overlay)
			UnityEngine.Object.Destroy(_overlay);
		_overlay = new GameObject(OverlayName);
		_overlay.layer = near.gameObject.layer;
		_overlay.transform.SetParent(root, false);
		var rect = _overlay.AddComponent<RectTransform>();
		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.offsetMin = Vector2.zero;
		rect.offsetMax = Vector2.zero;
		_overlay.AddComponent<LayoutElement>().ignoreLayout = true;
		// The hero panel draws on nested canvases with their own sort order; a plain child of the root canvas renders
		// underneath them. Give the overlay its own canvas sorted just above the slot's canvas (and a raycaster so the
		// toggles can swallow clicks).
		var own = _overlay.AddComponent<Canvas>();
		own.overrideSorting = true;
		own.sortingLayerID = canvas.sortingLayerID;
		own.sortingOrder = canvas.sortingOrder + 6; // flames draw at +5 (above the panel's nested canvases), toggles above them
		_overlay.AddComponent<GraphicRaycaster>();
		_log?.LogInfo("HoMM3 Inferno Gating HUD overlay: slot canvas='" + canvas.name + "' order=" + canvas.sortingOrder
		              + " override=" + canvas.overrideSorting + " layer=" + near.gameObject.layer + " -> overlay order " + own.sortingOrder + ".");
		return _overlay;
	}

	private static string PathOf(Transform t)
	{
		var parts = new List<string>();
		for (var cur = t; cur && parts.Count < 12; cur = cur.parent)
			parts.Insert(0, cur.name);
		return string.Join("/", parts);
	}

	private static void LogLayout(Component panel, SlotView slot)
	{
		try
		{
			var rect = slot.Slot.GetComponent<RectTransform>();
			var canvas = slot.Slot.GetComponentInParent<Canvas>();
			var root = canvas ? canvas.rootCanvas : null;
			_log?.LogInfo("HoMM3 Inferno Gating HUD layout: panel='" + PathOf(panel.transform) + "' active=" + panel.gameObject.activeInHierarchy
			              + " slot='" + PathOf(slot.Slot.transform) + "' rect=" + (rect ? rect.rect.size.ToString() : "?")
			              + " canvas=" + (root ? root.name + "/" + root.renderMode : "none")
			              + " toggleParent='" + (slot.Toggle ? PathOf(slot.Toggle.transform.parent) : "?") + "'.");
		}
		catch (Exception ex)
		{
			LogLimited("layout log failed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Camera for screen-point tests: null for overlay canvases, the root canvas camera otherwise.</summary>
	private static Camera EventCamera(Graphic graphic)
	{
		var canvas = graphic ? graphic.canvas : null;
		if (!canvas)
			return null;
		var root = canvas.rootCanvas;
		return root.renderMode == RenderMode.ScreenSpaceOverlay ? null : root.worldCamera;
	}

	private static void TrackSlotCorner(SlotView view, RectTransform slotRect)
	{
		if (!view.Toggle || !slotRect)
			return;
		// GetWorldCorners fills a copy of the array under IL2CPP interop (the managed array stays zero), so the corner is
		// computed from the local rect instead.
		var r = slotRect.rect;
		var t = view.Toggle.transform;
		t.position = slotRect.TransformPoint(new Vector3(r.xMax - ToggleSize * 0.35f, r.yMax - ToggleSize * 0.35f, 0f));
	}

	private static void DestroySlot(SlotView slot)
	{
		if (slot == null)
			return;
		if (slot.Frame)
			UnityEngine.Object.Destroy(slot.Frame);
		if (slot.Fire)
			UnityEngine.Object.Destroy(slot.Fire);
		if (slot.Toggle)
			UnityEngine.Object.Destroy(slot.Toggle);
		if (ReferenceEquals(_tooltipOwner, slot))
			HideTooltip();
	}

	// ------------------------------------------------------------------ per-frame (pump)

	internal static void Tick()
	{
		try
		{
			var now = Time.unscaledTime;
			var readState = _dirty || now >= _nextStateRead;
			if (readState)
			{
				_dirty = false;
				_nextStateRead = now + 0.3f;
			}
			if (now >= _nextRescan)
			{
				_nextRescan = now + 0.5f;
				Rescan();
			}
			var frameIndex = (int)(now * 12f) % FlameFrames;
			var mouse = Input.mousePosition;
			var click = Input.GetMouseButtonDown(0);
			SlotView hovered = null;
			PanelView hoveredPanel = null;
			List<int> dead = null;
			lock (Gate)
			{
				foreach (var pair in Panels)
				{
					var panel = pair.Value;
					if (panel.Panel == null || !panel.Panel)
					{
						(dead ??= new List<int>()).Add(pair.Key);
						continue;
					}
					if (panel.Slots.Count == 0)
						continue;
					if (!panel.Panel.gameObject.activeInHierarchy)
					{
						foreach (var slot in panel.Slots)
						{
							if (slot.Toggle && slot.Toggle.activeSelf)
								slot.Toggle.SetActive(false);
						}
						if (!_loggedPanelHidden)
						{
							_loggedPanelHidden = true;
							_log?.LogInfo("HoMM3 Inferno Gating HUD: army panel went inactive (city/screen change); toggles hidden.");
						}
						continue;
					}
					var open = false;
					var mask = 0;
					if (panel.DataHero != null)
						Homm3InfernoGatingRuntime.ReadState(panel.DataHero, out open, out mask);
					var allowed = Homm3InfernoGatingRuntime.ResolveAllowedSlots(panel.DataHero);
					var used = CountBits(mask);
					foreach (var slot in panel.Slots)
					{
						if (slot.Slot == null || !slot.Slot || !slot.Toggle)
							continue;
						var visible = slot.Slot.gameObject.activeInHierarchy;
						if (slot.Toggle.activeSelf != visible)
							slot.Toggle.SetActive(visible);
						if (!visible)
						{
							if (slot.Frame)
								slot.Frame.SetActive(false);
							if (slot.Fire)
								slot.Fire.SetActive(false);
							continue;
						}
						TrackSlotCorner(slot, slot.Slot.GetComponent<RectTransform>());
						var reserved = slot.SlotPos >= 0 && slot.SlotPos < 32 && (mask & (1 << slot.SlotPos)) != 0;
						slot.ToggleImage.sprite = reserved ? _toggleOpenSprite : _toggleIdleSprite;
						slot.ToggleImage.color = reserved || (used < allowed && !LastDeployedStack(panel, mask)) ? Color.white : new Color(1f, 1f, 1f, 0.35f);
						if (!_loggedTick)
						{
							_loggedTick = true;
							var c = slot.ToggleImage.canvas;
							_log?.LogInfo("HoMM3 Inferno Gating HUD first tick: toggle active=" + slot.Toggle.activeInHierarchy + " pos=" + slot.Toggle.transform.position
							              + " slotPos=" + slot.Slot.transform.position + " sprite=" + (slot.ToggleImage.sprite ? "yes" : "null")
							              + " canvas=" + (c ? c.name + " order=" + c.sortingOrder : "none") + " allowed=" + allowed + " mask=" + mask + ".");
						}
						var fire = reserved && open && EnsureFire(slot);
						if (slot.Fire && slot.Fire.activeSelf != fire)
							slot.Fire.SetActive(fire);
						if (fire)
							AnimateFire(slot, now);
						if (slot.Frame)
						{
							slot.Frame.SetActive(reserved && !fire);
							if (reserved && !fire)
							{
								slot.FrameImage.sprite = open ? _flameSprites[(frameIndex + slot.SlotPos * 3) % FlameFrames] : _sealSprite;
								var pulse = open ? 0.85f + 0.15f * Mathf.Sin(now * 7f + slot.SlotPos) : 0.8f;
								slot.FrameImage.color = new Color(1f, 1f, 1f, pulse);
							}
						}
						var rect = slot.Toggle.GetComponent<RectTransform>();
						if (hovered == null && rect && RectTransformUtility.RectangleContainsScreenPoint(rect, mouse, EventCamera(slot.ToggleImage)))
						{
							hovered = slot;
							hoveredPanel = panel;
						}
					}
				}
				if (dead != null)
				{
					foreach (var key in dead)
						Panels.Remove(key);
				}
			}

			if (hovered != null && click)
			{
				Homm3InfernoGatingRuntime.ReadState(hoveredPanel.DataHero, out _, out var clickMask);
				var clickReserved = (clickMask & (1 << hovered.SlotPos)) != 0;
				if (!clickReserved && LastDeployedStack(hoveredPanel, clickMask))
					LogReason("slot " + hovered.SlotPos + " not reserved: at least one stack must deploy normally.");
				else if (!Homm3InfernoGatingRuntime.TryToggleSlot(hoveredPanel.LogicHero, hovered.SlotPos, out _, out var fail))
					LogLimited("slot " + hovered.SlotPos + " toggle refused: " + fail);
				_dirty = true;
			}
			if (hovered != null)
				ShowTooltip(hovered, hoveredPanel);
			else if (_tooltipOwner != null)
				HideTooltip();
		}
		catch (Exception ex)
		{
			LogLimited("tick failed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Rebuild any known panel whose hero or slots changed since its last build (refresh postfixes can run
	/// before the panel is filled, and slot changes do not always go through the panel refresh).</summary>
	private static void Rescan()
	{
		List<(Component Panel, object Hint, string Signature)> work = null;
		lock (Gate)
		{
			foreach (var pair in Panels)
			{
				var view = pair.Value;
				if (view.Panel == null || !view.Panel || !view.Panel.gameObject.activeInHierarchy)
					continue;
				(work ??= new List<(Component, object, string)>()).Add((view.Panel, view.HeroHint, view.Signature));
			}
		}
		if (work == null)
			return;
		foreach (var item in work)
		{
			try
			{
				var hero = Homm3FactorySplitAssemblyArmyStripHud.TryResolveSessionHeroFromPanel(item.Panel) ?? item.Hint;
				if (!string.Equals(ComputeSignature(hero, ReadSlotList(item.Panel)), item.Signature, StringComparison.Ordinal))
					Rebuild(item.Panel, hero);
			}
			catch (Exception ex)
			{
				LogLimited("rescan failed: " + ex.GetBaseException().Message);
			}
		}
	}

	/// <summary>True when reserving one more stack would leave none deploying (every decorated slot is a filled stack).</summary>
	private static bool LastDeployedStack(PanelView panel, int mask)
	{
		var unreserved = 0;
		foreach (var slot in panel.Slots)
		{
			if (slot.SlotPos < 0 || slot.SlotPos >= 32 || (mask & (1 << slot.SlotPos)) == 0)
				unreserved++;
		}
		return unreserved <= 1;
	}

	private static void ShowTooltip(SlotView slot, PanelView panel)
	{
		EnsureTooltip(slot.Toggle.transform);
		if (!_tooltip)
			return;
		Homm3InfernoGatingRuntime.ReadState(panel.DataHero, out _, out var mask);
		var allowed = Homm3InfernoGatingRuntime.ResolveAllowedSlots(panel.DataHero);
		var reserved = (mask & (1 << slot.SlotPos)) != 0;
		if (reserved)
			_tooltipText.text = "Disable gating";
		else if (CountBits(mask) >= allowed)
			_tooltipText.text = "No gating slots left";
		else if (LastDeployedStack(panel, mask))
			_tooltipText.text = "One stack must deploy";
		else
			_tooltipText.text = "Enable gating";
		_tooltipOwner = slot;
		var tipRect = _tooltip.GetComponent<RectTransform>();
		// Size the plate to the one line of text (the sliced plate's own preferred size is huge).
		var pref = _tooltipText.GetPreferredValues(_tooltipText.text);
		tipRect.sizeDelta = new Vector2(Mathf.Ceil(pref.x) + 28f, Mathf.Max(30f, Mathf.Ceil(pref.y) + 12f));
		var toggleRect = slot.Toggle.GetComponent<RectTransform>();
		var tr = toggleRect.rect;
		tipRect.position = toggleRect.TransformPoint(new Vector3(tr.center.x, tr.yMax + 4f, 0f));
		_tooltip.transform.SetAsLastSibling();
		_tooltip.SetActive(true);
	}

	private static void HideTooltip()
	{
		_tooltipOwner = null;
		if (_tooltip)
			_tooltip.SetActive(false);
	}

	private static void EnsureTooltip(Transform near)
	{
		var canvas = near ? near.GetComponentInParent<Canvas>() : null;
		// near is a toggle, so this is the overlay's own sorted canvas: the tooltip draws above the hero panel too.
		var root = canvas ? canvas.transform : null;
		if (_tooltip && _tooltip.transform.parent == root)
			return;
		if (_tooltip)
			UnityEngine.Object.Destroy(_tooltip);
		_tooltip = new GameObject(TooltipName);
		if (root)
			_tooltip.transform.SetParent(root, false);
		var rect = _tooltip.AddComponent<RectTransform>();
		rect.pivot = new Vector2(0.5f, 0f);
		rect.sizeDelta = new Vector2(120f, 24f);
		var bg = _tooltip.AddComponent<Image>();
		bg.raycastTarget = false;
		// The game's own small tooltip plate (as the Artificing picker uses); opaque dark plate if it is not loaded.
		var plate = FindNativeSprite("littlr_tooltip 2");
		if (plate)
		{
			bg.sprite = plate;
			bg.type = Image.Type.Sliced;
			bg.pixelsPerUnitMultiplier = 8f; // thin corners at one-line size
			bg.fillCenter = true;
			bg.color = Color.white;
		}
		else
		{
			bg.color = new Color(0.07f, 0.03f, 0.02f, 1f);
		}
		var textGo = new GameObject("text");
		textGo.transform.SetParent(_tooltip.transform, false);
		var textRect = textGo.AddComponent<RectTransform>();
		textRect.anchorMin = Vector2.zero;
		textRect.anchorMax = Vector2.one;
		textRect.offsetMin = new Vector2(14f, 6f);
		textRect.offsetMax = new Vector2(-14f, -6f);
		_tooltipText = textGo.AddComponent<TextMeshProUGUI>();
		_tooltipText.fontSize = 17f;
		_tooltipText.richText = false;
		_tooltipText.enableWordWrapping = false;
		_tooltipText.alignment = TextAlignmentOptions.Center;
		_tooltipText.color = new Color(0.95f, 0.86f, 0.64f, 1f); // light gold on the dark plate
		_tooltipText.raycastTarget = false;
		if (canvas)
		{
			foreach (var donor in canvas.GetComponentsInChildren<TextMeshProUGUI>(true))
			{
				if (donor != null && donor.font && donor != _tooltipText)
				{
					_tooltipText.font = donor.font;
					break;
				}
			}
		}
		_tooltip.SetActive(false);
	}

	private static Sprite FindNativeSprite(string name)
	{
		Sprite best = null;
		try
		{
			var all = Resources.FindObjectsOfTypeAll<Sprite>();
			for (var i = 0; i < all.Length; i++)
			{
				var sp = all[i];
				if (sp && sp.name == name && (!best || sp.rect.width * sp.rect.height > best.rect.width * best.rect.height))
					best = sp;
			}
		}
		catch (Exception ex)
		{
			LogLimited("tooltip sprite lookup failed: " + ex.GetBaseException().Message);
		}
		if (!best)
			LogReason("tooltip plate '" + name + "' not loaded; using a flat plate.");
		return best;
	}

	// ------------------------------------------------------------------ vanilla flame frame

	/// <summary>Portal-style edge light on the unit card with faint embers drifting off its top and sides (once per slot); false = sprite-frame fallback.</summary>
	private static bool EnsureFire(SlotView slot)
	{
		if (slot.Fire)
			return true;
		var slotRect = slot.Slot.GetComponent<RectTransform>();
		if (!slotRect)
			return false;
		var w = slotRect.rect.width;
		var h = slotRect.rect.height;
		if (w <= 1f || h <= 1f)
			return false;
		EnsureRingFrames(h / w);
		var go = new GameObject(FrameName + "_fire_" + slot.SlotPos);
		go.layer = slot.Slot.gameObject.layer;
		go.transform.SetParent(slot.Slot.transform, false);
		var rect = go.AddComponent<RectTransform>();
		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.offsetMin = Vector2.zero;
		rect.offsetMax = Vector2.zero;
		go.AddComponent<LayoutElement>().ignoreLayout = true;
		go.transform.SetAsLastSibling();
		// edge light: the card plus a glow margin all round
		var ringGo = new GameObject("portal");
		ringGo.layer = go.layer;
		ringGo.transform.SetParent(go.transform, false);
		var rr = ringGo.AddComponent<RectTransform>();
		rr.anchorMin = Vector2.zero;
		rr.anchorMax = Vector2.one;
		var m = w * RingMargin;
		rr.offsetMin = new Vector2(-m, -m);
		rr.offsetMax = new Vector2(m, m);
		var ring = ringGo.AddComponent<Image>();
		ring.raycastTarget = false;
		ring.sprite = _ringFrames[0];
		slot.Ring = ring;
		_emberSprite ??= MakeSprite(Homm3InfernoGatingArt.Ember(EmberTex), EmberTex, EmberTex);
		slot.SlotW = w;
		slot.SlotH = h;
		slot.Embers = new RectTransform[EmberCount];
		slot.EmberImages = new Image[EmberCount];
		slot.EmberPhase = new float[EmberCount];
		for (var i = 0; i < EmberCount; i++)
		{
			var ember = new GameObject("ember_" + i);
			ember.layer = go.layer;
			ember.transform.SetParent(go.transform, false);
			var er = ember.AddComponent<RectTransform>();
			er.anchorMin = er.anchorMax = Vector2.zero;
			er.pivot = new Vector2(0.5f, 0.5f);
			var image = ember.AddComponent<Image>();
			image.raycastTarget = false;
			image.sprite = _emberSprite;
			image.color = new Color(1f, 1f, 1f, 0f);
			slot.Embers[i] = er;
			slot.EmberImages[i] = image;
			slot.EmberPhase[i] = UnityEngine.Random.Range(0f, 100f);
		}
		go.SetActive(false);
		slot.Fire = go;
		return true;
	}

	/// <summary>Builds the edge-light frames at the card's aspect (cards share one size; rebuilt if it changes).</summary>
	private static void EnsureRingFrames(float aspect)
	{
		if (_ringFrames != null && Mathf.Abs(aspect - _ringAspect) < 0.02f)
			return;
		_ringAspect = aspect;
		var tw = RingTex;
		var th = Mathf.Clamp(Mathf.RoundToInt(RingTex * (aspect + 2f * RingMargin) / (1f + 2f * RingMargin)), 32, 512);
		var frames = new Sprite[RingFrames];
		for (var f = 0; f < RingFrames; f++)
			frames[f] = MakeSprite(Homm3InfernoGatingArt.HudPortal(tw, th, RingMargin, f, RingFrames), tw, th);
		_ringFrames = frames;
	}

	private static void AnimateFire(SlotView slot, float now)
	{
		if (slot.Ring && _ringFrames != null)
			slot.Ring.sprite = _ringFrames[(int)(now * RingFps) % _ringFrames.Length];
		if (slot.Embers == null)
			return;
		var w = slot.SlotW;
		var h = slot.SlotH;
		for (var i = 0; i < slot.Embers.Length; i++)
		{
			var er = slot.Embers[i];
			var image = slot.EmberImages[i];
			if (!er || !image)
				continue;
			// each ember lives one cycle (period varies per ember), then respawns somewhere new on the edge
			var period = 2.6f + 1.4f * Hash01(i, 7);
			var t = (now + slot.EmberPhase[i]) / period;
			var cycle = Mathf.FloorToInt(t);
			var p = t - cycle;
			// start point on the top edge or the upper two thirds of a side (bottom stays clear for the count)
			var pick = Hash01(i * 131 + cycle, 11);
			float x0, y0;
			if (pick < 0.5f)
			{
				x0 = Mathf.Lerp(0.08f, 0.92f, Hash01(i * 17 + cycle, 13)) * w;
				y0 = h;
			}
			else
			{
				x0 = pick < 0.75f ? 0f : w;
				y0 = Mathf.Lerp(0.35f, 1f, Hash01(i * 29 + cycle, 17)) * h;
			}
			var rise = (0.22f + 0.18f * Hash01(i * 37 + cycle, 19)) * h;
			var sway = Mathf.Sin((p * 2.2f + Hash01(i * 41 + cycle, 23)) * Mathf.PI * 2f) * w * 0.035f;
			er.anchoredPosition = new Vector2(x0 + sway, y0 + rise * p);
			var size = w * (0.045f + 0.03f * Hash01(i * 53 + cycle, 29)) * (1f - 0.4f * p);
			er.sizeDelta = new Vector2(size, size);
			var flicker = 0.8f + 0.2f * Mathf.Sin(now * 13f + i * 1.7f);
			image.color = new Color(1f, 1f, 1f, 0.55f * Mathf.Sin(p * Mathf.PI) * flicker);
		}
	}

	private static float Hash01(int a, int seed)
	{
		unchecked
		{
			var h = (uint)(a * 374761393 + seed * 668265263);
			h = (h ^ (h >> 13)) * 1274126177u;
			h ^= h >> 16;
			return (h & 0xFFFF) / 65535f;
		}
	}

	// ------------------------------------------------------------------ procedural sprites

	private static void EnsureSprites()
	{
		if (_flameSprites != null)
			return;
		_flameSprites = new Sprite[FlameFrames];
		for (var f = 0; f < FlameFrames; f++)
			_flameSprites[f] = MakeSprite(Homm3InfernoGatingArt.FlameFrame(FrameTex, f, FlameFrames), FrameTex, FrameTex);
		_sealSprite = MakeSprite(Homm3InfernoGatingArt.EmberSeal(FrameTex), FrameTex, FrameTex);
		_toggleOpenSprite = MakeSprite(Homm3InfernoGatingArt.GateIcon(48, true), 48, 48);
		_toggleIdleSprite = MakeSprite(Homm3InfernoGatingArt.GateIcon(48, false), 48, 48);
	}

	private static Sprite MakeSprite(byte[] rgba, int w, int h)
	{
		var tex = Homm3InfernoGatingPortal.MakeTexture(rgba, w, h);
		var sprite = Sprite.Create(tex, new Rect(0, 0, w, h), new Vector2(0.5f, 0.5f), 100f);
		sprite.hideFlags = HideFlags.DontUnloadUnusedAsset;
		return sprite;
	}

	// ------------------------------------------------------------------ helpers

	private static int CountBits(int mask)
	{
		var n = 0;
		for (; mask != 0; mask &= mask - 1)
			n++;
		return n;
	}

	private static object ReadMember(object target, IEnumerable<string> names)
	{
		if (target == null)
			return null;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cur = target.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var property = cur.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						var value = property.GetValue(target);
						if (value != null)
							return value;
					}
					var method = cur.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						var value = method.Invoke(target, null);
						if (value != null)
							return value;
					}
					var field = cur.GetField(name, flags);
					if (field != null)
					{
						var value = field.GetValue(target);
						if (value != null)
							return value;
					}
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 30)
			_log?.LogWarning("HoMM3 Inferno Gating HUD: " + message);
	}
}

public sealed class Homm3InfernoGatingHudPump : MonoBehaviour
{
	public Homm3InfernoGatingHudPump(IntPtr ptr) : base(ptr) { }

	private void LateUpdate()
	{
		Homm3InfernoGatingArmyStripHud.Tick();
		Homm3InfernoGatingPortal.Tick();
	}
}
