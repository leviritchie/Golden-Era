using System;
using System.Collections.Generic;
using System.Globalization;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using R = OfflineUnlockMod.Homm3CoveTreasureRuntime;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// The Treasure Chart (approved mockup v4, 2026-11-17): one parchment sheet with every region of the map and, per
/// region, how many map pieces the local player holds and whether the treasure is still buried. Opened by a scroll
/// button on the adventure map or Ctrl+T, for players with a Treasure Hunting hero. Rivals' piece counts are never
/// shown, only that a treasure is gone. The chart is drawn once per opening from <see cref="R.SnapshotChart"/>.
/// Ticked by <see cref="Homm3CoveTreasureMarkersHost"/>.
/// </summary>
internal static class Homm3CoveTreasureChart
{
	private const string WindowObjectName = "OFFLINE_UNLOCK_MOD_COVE_TREASURE_CHART";
	private const string ButtonObjectName = "OFFLINE_UNLOCK_MOD_COVE_TREASURE_CHART_BUTTON";
	internal const KeyCode Key = KeyCode.T;
	private const float WindowWidth = 1400f;
	private const float WindowHeight = 960f;
	private const float ChartSize = 700f;
	private const float ChartX = 74f;
	private const float ChartY = 150f;
	private const float ColumnX = 830f;
	private const float ColumnWidth = 500f;
	private const int TexturePixels = 640;
	private const float ButtonSize = 64f;
	private const float ViewCheckSeconds = 0.5f;
	private static readonly Color Ink = new(0.23f, 0.15f, 0.09f, 1f);
	private static readonly Color FactInk = new(0.17f, 0.12f, 0.07f, 1f);
	private static readonly Color Blood = new(0.59f, 0.10f, 0.08f, 1f);
	private static readonly Color Rule = new(0.47f, 0.34f, 0.19f, 0.9f);
	private static readonly Color ButtonText = new(0.94f, 0.82f, 0.51f, 1f);

	// ---- window state
	private static GameObject _window;
	private static Texture2D _texture;
	private static Sprite _chartSprite;
	private static RectTransform _chartRect;
	private static Image _close;
	private static TextMeshProUGUI[] _hoverLines;
	private static int _openedFrame;
	private static int _hoverArea = int.MinValue;
	private static int[] _tileArea;
	/// <summary>Map node per chart cell, for click to jump.</summary>
	private static int[] _tileNode;
	private static int _hoverNode = -1;
	private static bool _closeOnRelease;
	private static int _texW, _texH;
	private static readonly Dictionary<int, (R.ChartRegion Row, int Number)> Rows = new();

	// ---- map button state
	private static GameObject _buttonObject;
	private static Canvas _buttonCanvas;
	private static RectTransform _buttonRect;
	private static Image _buttonFrame;
	private static Camera _camera;
	private static object _map;
	private static IntPtr _boundCamera;
	private static bool _viewOk;
	private static float _nextViewCheck;
	private static bool _hoverHeld;
	private static int _warned;

	internal static bool IsOpen => _window != null;

	private static string N(int value) => value.ToString(CultureInfo.InvariantCulture);

	private static void Warn(string message)
	{
		if (_warned++ < 20)
			try { Plugin.LogSource?.LogWarning(R.LogPrefix + "chart: " + message); } catch { }
	}

	// ---------------------------------------------------------------- tick (host, every frame)

	internal static void Tick()
	{
		if (_window != null)
		{
			TickWindow();
			return;
		}
		if (Homm3CoveTreasurePopup.IsOpen)
		{
			// The popup owns the input block now.
			_hoverHeld = false;
			ShowButton(false);
			return;
		}
		if (!R.LocalHunter)
		{
			ReleaseHover();
			ShowButton(false);
			return;
		}
		var now = Time.realtimeSinceStartup;
		if (now >= _nextViewCheck)
		{
			_nextViewCheck = now + ViewCheckSeconds;
			_viewOk = Homm3FactoryLogisticsAdventureView.TryAdventureView(out _camera, out _map);
		}
		if (!_viewOk || _camera == null)
		{
			ReleaseHover();
			ShowButton(false);
			return;
		}
		try
		{
			if (!EnsureButton())
				return;
			ShowButton(true);
			BindButtonCamera();
			var over = RectTransformUtility.RectangleContainsScreenPoint(_buttonRect, (Vector2)Input.mousePosition, _camera);
			if (over && !_hoverHeld && Homm3TowerArtificingPickerInputBlock.GamePointerOverUi())
				over = false; // a game window covers the button
			if (over != _hoverHeld)
			{
				// While the pointer is on the button the map must not take the click as a move order.
				_hoverHeld = over;
				if (over)
					Homm3TowerArtificingPickerInputBlock.Begin();
				else
					Homm3TowerArtificingPickerInputBlock.End();
				if (_buttonFrame != null)
					_buttonFrame.color = over ? new Color(0.36f, 0.25f, 0.14f, 0.96f) : new Color(0.2f, 0.13f, 0.08f, 0.92f);
			}
			if (over)
				Homm3TowerArtificingPickerInputBlock.Hold();
			var hotkey = Input.GetKeyDown(Key) && (Input.GetKey(KeyCode.LeftControl) || Input.GetKey(KeyCode.RightControl)) && !TextFieldFocused();
			if ((over && Input.GetMouseButtonDown(0)) || hotkey)
				TryOpen();
		}
		catch (Exception ex)
		{
			Warn("map button failed (" + ex.GetBaseException().Message + ").");
			ReleaseHover();
			DestroyButton();
		}
	}

	private static bool TextFieldFocused()
	{
		try
		{
			var selected = UnityEngine.EventSystems.EventSystem.current?.currentSelectedGameObject;
			return selected != null && (selected.GetComponent<TMP_InputField>() != null || selected.GetComponent<InputField>() != null);
		}
		catch
		{
			return false;
		}
	}

	private static void ReleaseHover()
	{
		if (!_hoverHeld)
			return;
		_hoverHeld = false;
		try { Homm3TowerArtificingPickerInputBlock.End(); } catch { }
	}

	// ---------------------------------------------------------------- map button

	private static void ShowButton(bool shown)
	{
		if (_buttonObject != null && _buttonObject.activeSelf != shown)
			_buttonObject.SetActive(shown);
	}

	private static bool EnsureButton()
	{
		if (_buttonObject != null)
			return true;
		var go = new GameObject(ButtonObjectName, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		_buttonObject = go;
		_buttonCanvas = go.GetComponent<Canvas>();
		_boundCamera = IntPtr.Zero;
		var scaler = go.GetComponent<CanvasScaler>();
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = 1f;
		// Left edge of the map view, a third of the way down: clear of the top bar and the bottom panels.
		_buttonFrame = A.NewImage("Frame", go.transform, null, new Color(0.2f, 0.13f, 0.08f, 0.92f));
		_buttonRect = _buttonFrame.rectTransform;
		_buttonRect.anchorMin = _buttonRect.anchorMax = new Vector2(0f, 0.66f);
		_buttonRect.pivot = new Vector2(0f, 0.5f);
		_buttonRect.anchoredPosition = new Vector2(14f, 0f);
		_buttonRect.sizeDelta = new Vector2(ButtonSize, ButtonSize);
		var rim = A.NewImage("Rim", _buttonRect, null, new Color(0.77f, 0.61f, 0.32f, 1f));
		rim.rectTransform.anchorMin = new Vector2(0f, 0f);
		rim.rectTransform.anchorMax = new Vector2(1f, 0f);
		rim.rectTransform.pivot = new Vector2(0.5f, 0f);
		rim.rectTransform.anchoredPosition = Vector2.zero;
		rim.rectTransform.sizeDelta = new Vector2(0f, 3f);
		var icon = A.NewImage("Icon", _buttonRect, Homm3CoveTreasureMarkers.Art("map_piece"), Color.white);
		icon.rectTransform.anchorMin = icon.rectTransform.anchorMax = icon.rectTransform.pivot = new Vector2(0.5f, 0.5f);
		icon.rectTransform.anchoredPosition = new Vector2(0f, 1f);
		icon.rectTransform.sizeDelta = new Vector2(ButtonSize - 12f, ButtonSize - 12f);
		return true;
	}

	/// <summary>Drawn by the map camera itself (as the map markers are), so game windows cover the button.</summary>
	private static void BindButtonCamera()
	{
		if (_buttonCanvas == null || _camera == null)
			return;
		if (_boundCamera != _camera.Pointer)
		{
			_boundCamera = _camera.Pointer;
			_buttonCanvas.renderMode = RenderMode.ScreenSpaceCamera;
			_buttonCanvas.worldCamera = _camera;
			_buttonCanvas.overrideSorting = true;
			_buttonCanvas.sortingOrder = 6;
			var mask = _camera.cullingMask;
			var layer = (mask & 1) != 0 ? 0 : -1;
			for (var i = 1; layer < 0 && i < 32; i++)
				if ((mask & (1 << i)) != 0)
					layer = i;
			SetLayer(_buttonObject.transform, layer < 0 ? 0 : layer);
		}
		var near = _camera.nearClipPlane;
		var plane = near + 0.05f + near * 0.01f;
		if (Math.Abs(_buttonCanvas.planeDistance - plane) > 0.0005f)
			_buttonCanvas.planeDistance = plane;
	}

	private static void SetLayer(Transform t, int layer)
	{
		t.gameObject.layer = layer;
		for (var i = t.childCount - 1; i >= 0; i--)
			SetLayer(t.GetChild(i), layer);
	}

	private static void DestroyButton()
	{
		var go = _buttonObject;
		_buttonObject = null;
		_buttonCanvas = null;
		_buttonRect = null;
		_buttonFrame = null;
		if (go != null)
			try { UnityObject.Destroy(go); } catch { }
	}

	// ---------------------------------------------------------------- window

	private static void TryOpen()
	{
		try
		{
			if (!Homm3FactoryLogisticsEffects.TryGetData(out var data, out _) || data == null)
				return;
			var snap = R.SnapshotChart(R.LocalSide(data));
			if (snap == null)
			{
				Homm3DungeonWarCaptivesWindow.ShowBanner("The treasure chart is not ready yet.");
				return;
			}
			_hoverHeld = false; // Open() takes the input block over
			Open(snap);
			try { Plugin.LogSource?.LogInfo(R.LogPrefix + "chart: opened, " + N(Rows.Count) + " regions, texture " + N(_texW) + "x" + N(_texH) + "."); } catch { }
		}
		catch (Exception ex)
		{
			Warn("failed to open (" + ex.GetBaseException().Message + ").");
			Close();
		}
	}

	private static void TickWindow()
	{
		try
		{
			Homm3TowerArtificingPickerInputBlock.Hold();
			if (_closeOnRelease)
			{
				if (!Input.GetMouseButton(0))
					Close();
				return;
			}
			var mouse = (Vector2)Input.mousePosition;
			var over = _close != null && RectTransformUtility.RectangleContainsScreenPoint(_close.rectTransform, mouse, null);
			var sprite = Homm3CoveTreasureMarkers.Art(over ? "popup_button_hover" : "popup_button");
			if (_close != null && sprite != null && _close.sprite != sprite)
				_close.sprite = sprite;
			UpdateHover(mouse);
			if (Time.frameCount <= _openedFrame + 1)
				return;
			var hotkey = Input.GetKeyDown(Key) && (Input.GetKey(KeyCode.LeftControl) || Input.GetKey(KeyCode.RightControl));
			// Click on the chart: the map camera jumps to that tile and the chart closes.
			if (!over && _hoverNode >= 0 && Input.GetMouseButtonDown(0))
			{
				// The chart (and its input block) stays until the button is released, so the click never reaches the map.
				JumpTo(_hoverNode);
				_closeOnRelease = true;
				return;
			}
			if ((over && Input.GetMouseButtonDown(0)) || hotkey || Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter)
				|| Input.GetKeyDown(KeyCode.Escape))
				Close();
		}
		catch (Exception ex)
		{
			Warn("input failed (" + ex.GetBaseException().Message + "); closed.");
			Close();
		}
	}

	/// <summary>Moves the adventure map camera to a tile with the game's own move call (BhWorldCamera, the Vector3
	/// overload: it hands the point to the camera's mover; decompiled on build 26615913).</summary>
	private static void JumpTo(int node)
	{
		try
		{
			var camera = Hex.BhWorldCamera.prop_BhWorldCamera_0;
			if (camera == null || _map == null || !Homm3CoveTreasureMarkers.TryNodeToWorld(_map, node, out var world))
			{
				Warn("jump to tile " + N(node) + " skipped: " + (camera == null ? "no map camera" : "tile has no world point") + ".");
				return;
			}
			camera.Method_Public_Void_Vector3_0(world);
			try { Plugin.LogSource?.LogInfo(R.LogPrefix + "chart: camera jumped to tile " + N(node) + "."); } catch { }
		}
		catch (Exception ex)
		{
			Warn("jump to tile " + N(node) + " failed: " + ex.GetBaseException().Message);
		}
	}

	private static void Close()
	{
		var go = _window;
		_window = null;
		_close = null;
		_chartRect = null;
		_hoverLines = null;
		_tileArea = null;
		_tileNode = null;
		_hoverNode = -1;
		_closeOnRelease = false;
		_hoverArea = int.MinValue;
		try { Homm3TowerArtificingPickerInputBlock.End(); } catch { }
		if (go != null)
			try { UnityObject.Destroy(go); } catch { }
		if (_chartSprite != null)
			try { UnityObject.Destroy(_chartSprite); } catch { }
		if (_texture != null)
			try { UnityObject.Destroy(_texture); } catch { }
		_chartSprite = null;
		_texture = null;
	}

	private static void Open(R.ChartSnapshot snap)
	{
		var go = new GameObject(WindowObjectName, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		_window = go;
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

		var dim = A.NewImage("Dim", canvasRect, null, new Color(0f, 0f, 0f, 0.45f));
		A.Stretch(dim.rectTransform);
		dim.raycastTarget = true;

		var window = A.NewRect("Window", canvasRect);
		window.anchorMin = window.anchorMax = window.pivot = new Vector2(0.5f, 0.5f);
		window.anchoredPosition = Vector2.zero;
		window.sizeDelta = new Vector2(WindowWidth, WindowHeight);
		var sheet = A.NewImage("Paper", window, Homm3CoveTreasureMarkers.Art("popup_paper"), new Color(0.87f, 0.78f, 0.59f, 1f));
		A.Stretch(sheet.rectTransform);

		var title = Homm3CoveTreasureMarkers.Art("popup_title_chart");
		if (title != null)
		{
			var image = A.NewImage("Title", window, title, Color.white);
			var h = 62f;
			var w = h * title.rect.width / Mathf.Max(1f, title.rect.height);
			A.Place(image.rectTransform, (WindowWidth - w) * 0.5f, 50f, w, h);
		}
		else
			Text(window, "Treasure Chart", 34f, WindowWidth * 0.5f - 300f, 54f, 600f, 50f, Ink, FontStyles.Bold, TextAlignmentOptions.Center);
		A.Place(A.NewImage("Rule", window, null, Rule).rectTransform, 80f, 124f, WindowWidth - 160f, 2f);

		BuildChart(window, snap);
		BuildColumn(window, snap);

		_close = A.NewImage("Close", window, Homm3CoveTreasureMarkers.Art("popup_button"), new Color(0.2f, 0.13f, 0.08f, 1f));
		A.Place(_close.rectTransform, (WindowWidth - 170f) * 0.5f, WindowHeight - 98f, 170f, 46f);
		var label = A.AddText(_close.rectTransform, P.FontMedium, 20f, "Close", 0f, 0f, 170f, 46f, ButtonText, TextAlignmentOptions.Center);
		if (label != null)
		{
			var rt = label.rectTransform;
			rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
			rt.anchoredPosition = Vector2.zero;
			rt.sizeDelta = new Vector2(170f, 46f);
		}
		_openedFrame = Time.frameCount;
		_hoverArea = int.MinValue;
		Homm3TowerArtificingPickerInputBlock.Begin();
	}

	private static TextMeshProUGUI Text(Transform parent, string text, float size, float x, float y, float w, float h, Color color, FontStyles style,
		TextAlignmentOptions align = TextAlignmentOptions.TopLeft, bool wrap = false)
	{
		var t = A.AddText(parent, P.FontMedium, size, text, x, y, w, h, color, align, wrap);
		if (t == null)
			return null;
		t.fontStyle = style;
		t.overflowMode = TextOverflowModes.Overflow;
		A.Place(t.rectTransform, x, y, w, h);
		return t;
	}

	// ---------------------------------------------------------------- the chart image

	private static Color32 Tint(R.ChartState state)
	{
		switch (state)
		{
			case R.ChartState.Sea: return new Color32(150, 176, 178, 255);
			case R.ChartState.Uncharted: return new Color32(150, 132, 100, 255);
			case R.ChartState.Pieces: return new Color32(244, 226, 160, 255);
			case R.ChartState.Site: return new Color32(250, 214, 120, 255);
			case R.ChartState.Yours: return new Color32(196, 214, 170, 255);
			case R.ChartState.Rival: return new Color32(176, 168, 158, 255);
			default: return new Color32(236, 222, 184, 255); // charted, no pieces (and regions without a treasure)
		}
	}

	/// <summary>
	/// How map tiles map to chart pixels so that the chart reads like the map on screen: which tile axis runs
	/// left-to-right for the map camera, and in which direction. Falls back to x right, y up.
	/// </summary>
	private static void Orientation(int width, out bool swap, out bool flipH, out bool flipV)
	{
		swap = flipH = flipV = false;
		try
		{
			if (_camera == null || _map == null
				|| !Homm3CoveTreasureMarkers.TryNodeToWorld(_map, 0, out var p0)
				|| !Homm3CoveTreasureMarkers.TryNodeToWorld(_map, 1, out var px)
				|| !Homm3CoveTreasureMarkers.TryNodeToWorld(_map, width, out var py))
				return;
			var right = _camera.transform.right;
			var up = _camera.transform.up;
			var ex = px - p0;
			var ey = py - p0;
			float exR = Vector3.Dot(ex, right), exU = Vector3.Dot(ex, up), eyR = Vector3.Dot(ey, right), eyU = Vector3.Dot(ey, up);
			swap = Mathf.Abs(exR) < Mathf.Abs(exU);
			flipH = (swap ? eyR : exR) < 0f;
			flipV = (swap ? exU : eyU) < 0f;
			try { Plugin.LogSource?.LogInfo(R.LogPrefix + "chart: orientation swap=" + swap + " flipH=" + flipH + " flipV=" + flipV + "."); } catch { }
		}
		catch (Exception ex)
		{
			Warn("orientation unknown (" + ex.GetBaseException().Message + "); drawn x right, y up.");
		}
	}

	private static void BuildChart(RectTransform window, R.ChartSnapshot snap)
	{
		Rows.Clear();
		var number = 0;
		foreach (var row in snap.Regions)
			Rows[row.AreaId] = (row, row.State == R.ChartState.Sea ? 0 : ++number);

		Orientation(snap.Width, out var swap, out var flipH, out var flipV);
		int w = snap.Width, h = snap.Height;
		var tw = swap ? h : w;
		var th = swap ? w : h;
		// Tile grid in chart space (origin bottom-left), area id per cell; sea and empty tiles become -1.
		var grid = new int[tw * th];
		var nodes = new int[tw * th];
		var sumX = new Dictionary<int, long>();
		var sumY = new Dictionary<int, long>();
		for (var node = 0; node < snap.AreaOfTile.Length; node++)
		{
			int x = node % w, y = node / w;
			var cx = swap ? y : x;
			var cy = swap ? x : y;
			if (flipH)
				cx = tw - 1 - cx;
			if (flipV)
				cy = th - 1 - cy;
			var area = snap.AreaOfTile[node];
			nodes[cy * tw + cx] = area >= 0 ? node : -1;
			if (area >= 0 && Rows.TryGetValue(area, out var info) && info.Row.State == R.ChartState.Sea)
				area = -1;
			grid[cy * tw + cx] = area;
			if (area < 0)
				continue;
			sumX.TryGetValue(area, out var sx);
			sumY.TryGetValue(area, out var sy);
			sumX[area] = sx + cx;
			sumY[area] = sy + cy;
		}
		_tileArea = grid;
		_tileNode = nodes;
		_texW = tw;
		_texH = th;

		var scale = Mathf.Clamp(TexturePixels / Mathf.Max(tw, th), 1, 16);
		int pw = tw * scale, ph = th * scale;
		var pixels = new Il2CppStructArray<Color32>(pw * ph);
		var ink = new Color32(70, 46, 26, 255);
		var sea = Tint(R.ChartState.Sea);
		var tints = new Dictionary<int, Color32>();
		foreach (var pair in Rows)
			tints[pair.Key] = Tint(pair.Value.Row.State);
		var thick = scale >= 4;
		for (var cy = 0; cy < th; cy++)
		{
			for (var cx = 0; cx < tw; cx++)
			{
				var area = grid[cy * tw + cx];
				var colour = area >= 0 && tints.TryGetValue(area, out var t) ? t : sea;
				// A light grain so flat fills read as paper.
				var grain = 0.95f + 0.05f * (((cx * 7349 + cy * 9151) ^ (cx * 31 + cy * 17)) & 15) / 15f;
				colour = new Color32((byte)(colour.r * grain), (byte)(colour.g * grain), (byte)(colour.b * grain), 255);
				var left = cx > 0 && grid[cy * tw + cx - 1] != area;
				var below = cy > 0 && grid[(cy - 1) * tw + cx] != area;
				var rightEdge = thick && cx < tw - 1 && grid[cy * tw + cx + 1] != area;
				var above = thick && cy < th - 1 && grid[(cy + 1) * tw + cx] != area;
				for (var sy = 0; sy < scale; sy++)
				{
					var rowStart = (cy * scale + sy) * pw + cx * scale;
					for (var sx = 0; sx < scale; sx++)
					{
						var border = (left && sx == 0) || (below && sy == 0) || (rightEdge && sx == scale - 1) || (above && sy == scale - 1);
						pixels[rowStart + sx] = border ? ink : colour;
					}
				}
			}
		}
		_texture = new Texture2D(pw, ph, TextureFormat.RGBA32, mipChain: false);
		_texture.SetPixels32(pixels);
		_texture.Apply(false, true);
		_texture.wrapMode = TextureWrapMode.Clamp;
		_texture.filterMode = FilterMode.Bilinear;
		_texture.hideFlags = HideFlags.HideAndDontSave;
		_chartSprite = Sprite.Create(_texture, new Rect(0f, 0f, pw, ph), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
		_chartSprite.hideFlags = HideFlags.HideAndDontSave;

		// Fit the chart into its square, keeping the map's proportions.
		var fit = ChartSize / Mathf.Max(tw, th);
		float cw = tw * fit, ch = th * fit;
		var frame = A.NewImage("ChartFrame", window, null, new Color(0.27f, 0.18f, 0.1f, 1f));
		A.Place(frame.rectTransform, ChartX + (ChartSize - cw) * 0.5f - 3f, ChartY + (ChartSize - ch) * 0.5f - 3f, cw + 6f, ch + 6f);
		var chart = A.NewImage("Chart", window, _chartSprite, Color.white);
		_chartRect = chart.rectTransform;
		A.Place(_chartRect, ChartX + (ChartSize - cw) * 0.5f, ChartY + (ChartSize - ch) * 0.5f, cw, ch);

		foreach (var pair in Rows)
		{
			var row = pair.Value.Row;
			if (row.State == R.ChartState.Sea || row.State == R.ChartState.NoTreasure || row.Tiles < 24 || !sumX.TryGetValue(pair.Key, out var sx))
				continue;
			var x = (sx / (float)row.Tiles + 0.5f) * fit;
			var y = (sumY[pair.Key] / (float)row.Tiles + 0.5f) * fit;
			Mark(_chartRect, row.State, row.Pieces, x, y, 1f);
		}
	}

	/// <summary>One region's mark, centred at (x, y) from the parent's bottom-left corner.</summary>
	private static void Mark(RectTransform parent, R.ChartState state, int pieces, float x, float y, float size)
	{
		switch (state)
		{
			case R.ChartState.Pieces:
			case R.ChartState.NoPieces:
				for (var k = 0; k < 5; k++)
				{
					var filled = k < pieces;
					var pip = A.NewImage("Pip", parent, filled ? Disc(true) : Disc(false), Color.white);
					pip.color = filled ? new Color(0.47f, 0.12f, 0.09f, 1f) : state == R.ChartState.NoPieces ? new Color(0.47f, 0.38f, 0.26f, 0.8f) : Ink;
					At(pip.rectTransform, parent, x + (k - 2) * 12f * size, y, 11f * size, 11f * size);
				}
				break;
			case R.ChartState.Site:
				Glyph(parent, "mark_exclaim", Color.white, x, y, 40f * size);
				break;
			case R.ChartState.Yours:
				Glyph(parent, "ground_x", Color.white, x, y, 22f * size);
				break;
			case R.ChartState.Rival:
				Glyph(parent, "ground_x", new Color(0.42f, 0.42f, 0.42f, 0.9f), x, y, 20f * size);
				break;
			case R.ChartState.Uncharted:
				Glyph(parent, "mark_question", new Color(0.45f, 0.42f, 0.36f, 0.75f), x, y, 22f * size);
				break;
		}
	}

	private static void Glyph(RectTransform parent, string art, Color tint, float x, float y, float height)
	{
		var sprite = Homm3CoveTreasureMarkers.Art(art);
		if (sprite == null)
			return;
		var image = A.NewImage(art, parent, sprite, Color.white);
		image.color = tint;
		At(image.rectTransform, parent, x, y, height * sprite.rect.width / Mathf.Max(1f, sprite.rect.height), height);
	}

	private static void At(RectTransform rt, RectTransform parent, float x, float y, float w, float h)
	{
		rt.anchorMin = rt.anchorMax = Vector2.zero;
		rt.pivot = new Vector2(0.5f, 0.5f);
		rt.anchoredPosition = new Vector2(x, y);
		rt.sizeDelta = new Vector2(w, h);
	}

	private static Sprite _discFull, _discRing;

	/// <summary>A small white disc or ring, tinted per use (the map-piece pips).</summary>
	private static Sprite Disc(bool filled)
	{
		var cached = filled ? _discFull : _discRing;
		if (cached)
			return cached;
		const int size = 32;
		var texture = new Texture2D(size, size, TextureFormat.RGBA32, mipChain: false);
		var pixels = new Il2CppStructArray<Color32>(size * size);
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var dx = x + 0.5f - size * 0.5f;
				var dy = y + 0.5f - size * 0.5f;
				var d = Mathf.Sqrt(dx * dx + dy * dy);
				var alpha = Mathf.Clamp01(size * 0.5f - 1f - d);
				if (!filled)
					alpha *= Mathf.Clamp01(d - (size * 0.5f - 6f));
				pixels[y * size + x] = new Color32(255, 255, 255, (byte)(255f * alpha));
			}
		}
		texture.SetPixels32(pixels);
		texture.Apply(false, true);
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.hideFlags = HideFlags.HideAndDontSave;
		var sprite = Sprite.Create(texture, new Rect(0f, 0f, size, size), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
		sprite.hideFlags = HideFlags.HideAndDontSave;
		if (filled)
			_discFull = sprite;
		else
			_discRing = sprite;
		return sprite;
	}

	// ---------------------------------------------------------------- right column

	private static void BuildColumn(RectTransform window, R.ChartSnapshot snap)
	{
		int total = 0, yours = 0, rival = 0, sites = 0, withPieces = 0;
		foreach (var row in snap.Regions)
		{
			if (row.State == R.ChartState.Sea || row.State == R.ChartState.NoTreasure)
				continue;
			total++;
			switch (row.State)
			{
				case R.ChartState.Yours: yours++; break;
				case R.ChartState.Rival: rival++; break;
				case R.ChartState.Site: sites++; break;
				case R.ChartState.Pieces: withPieces++; break;
			}
		}
		var y = ChartY;
		foreach (var line in new[]
		{
			"Treasures dug up by you: " + N(yours) + " of " + N(total),
			"Lost to rivals: " + N(rival),
			"Sites marked, ready to dig: " + N(sites),
			"Regions with map pieces: " + N(withPieces),
		})
		{
			Text(window, line, 22f, ColumnX, y, ColumnWidth, 30f, FactInk, FontStyles.Bold);
			y += 34f;
		}
		y += 12f;
		A.Place(A.NewImage("Rule", window, null, Rule).rectTransform, ColumnX, y, ColumnWidth, 1f);
		y += 16f;

		var legend = new (R.ChartState State, int Pieces, string Text)[]
		{
			(R.ChartState.Pieces, 2, "Map pieces held, of 5 in the region"),
			(R.ChartState.Site, 4, "Site marked: enough pieces to dig"),
			(R.ChartState.Yours, 0, "Treasure dug up by you"),
			(R.ChartState.Rival, 0, "Treasure taken by a rival"),
			(R.ChartState.Uncharted, 0, "Uncharted: no hero of yours has been there"),
		};
		foreach (var (state, pieces, text) in legend)
		{
			var cell = A.NewRect("Legend", window);
			A.Place(cell, ColumnX, y, 76f, 40f);
			Mark(cell, state, pieces, 38f, 20f, 1f);
			Text(window, text, 19f, ColumnX + 88f, y + 8f, ColumnWidth - 88f, 28f, FactInk, FontStyles.Normal);
			y += 44f;
		}
		y += 10f;
		A.Place(A.NewImage("Rule", window, null, Rule).rectTransform, ColumnX, y, ColumnWidth, 1f);
		y += 18f;

		var card = A.NewImage("HoverCard", window, null, new Color(0.96f, 0.92f, 0.78f, 0.9f));
		A.Place(card.rectTransform, ColumnX, y, ColumnWidth, 150f);
		_hoverLines = new TextMeshProUGUI[4];
		for (var i = 0; i < _hoverLines.Length; i++)
			_hoverLines[i] = Text(card.rectTransform, string.Empty, i == 0 ? 22f : 19f, 18f, 14f + i * 31f, ColumnWidth - 36f, 28f, FactInk, i == 0 ? FontStyles.Bold : FontStyles.Normal);
		SetHover(-1);
		y += 168f;
		Text(window, "Dug regions keep their mark until the end of the game. Rivals' progress is never shown, only that a treasure is gone.",
			18f, ColumnX, y, ColumnWidth, 84f, Ink, FontStyles.Italic, TextAlignmentOptions.TopLeft, true);
	}

	private static void UpdateHover(Vector2 mouse)
	{
		var area = -1;
		_hoverNode = -1;
		if (_chartRect != null && _tileArea != null && RectTransformUtility.ScreenPointToLocalPointInRectangle(_chartRect, mouse, null, out var local))
		{
			// Local to the pivot; the rect knows its own pivot and size.
			var rect = _chartRect.rect;
			var u = (local.x - rect.xMin) / Mathf.Max(1f, rect.width);
			var v = (local.y - rect.yMin) / Mathf.Max(1f, rect.height);
			if (u >= 0f && u < 1f && v >= 0f && v < 1f)
			{
				var cell = Mathf.Min(_texH - 1, (int)(v * _texH)) * _texW + Mathf.Min(_texW - 1, (int)(u * _texW));
				area = _tileArea[cell];
				if (_tileNode != null)
					_hoverNode = _tileNode[cell];
			}
		}
		if (area != _hoverArea)
			SetHover(area);
	}

	private static void SetHover(int area)
	{
		_hoverArea = area;
		if (_hoverLines == null)
			return;
		var lines = new[] { "Point at a region", "to see its map pieces and", "whether its treasure is still buried.", "Click the chart to jump there." };
		if (area >= 0 && Rows.TryGetValue(area, out var info) && info.Row.State != R.ChartState.Sea)
		{
			var row = info.Row;
			lines[0] = "Region " + N(info.Number);
			lines[1] = "Map pieces: " + N(row.Pieces) + " of " + N(Homm3CoveTreasurePlan.PiecesPerRegion);
			lines[3] = string.Empty;
			switch (row.State)
			{
				case R.ChartState.NoTreasure:
					lines[1] = "No treasure is buried here.";
					lines[2] = string.Empty;
					break;
				case R.ChartState.Uncharted:
					lines[2] = "Uncharted: none of your heroes has been here.";
					lines[3] = "Treasure: still buried, as far as you know";
					break;
				case R.ChartState.NoPieces:
					lines[2] = "No possible sites known yet.";
					lines[3] = "Treasure: still buried";
					break;
				case R.ChartState.Pieces:
					lines[2] = N(row.Leads) + " possible sites marked on the map";
					lines[3] = "Treasure: still buried";
					break;
				case R.ChartState.Site:
					lines[2] = "The site is marked: ready to dig.";
					lines[3] = "Treasure: still buried";
					break;
				case R.ChartState.Yours:
					lines[2] = string.Empty;
					lines[3] = "Treasure: dug up by you";
					break;
				case R.ChartState.Rival:
					lines[2] = string.Empty;
					lines[3] = "Treasure: taken by a rival";
					break;
			}
		}
		for (var i = 0; i < _hoverLines.Length; i++)
			if (_hoverLines[i] != null)
				_hoverLines[i].text = lines[i];
	}
}
