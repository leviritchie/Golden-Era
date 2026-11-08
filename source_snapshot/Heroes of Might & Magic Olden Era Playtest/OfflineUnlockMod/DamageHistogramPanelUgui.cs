using System;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

namespace OfflineUnlockMod;

internal readonly struct HistogramLayoutParams
{
	internal readonly float TotalW, TotalH, S, WAttack, WRetal, Gap, BorderPad, BlockH, PlotH, Pad, AxisR;
	internal readonly Font CapFont, BinFont;
	internal readonly int CapFontPx, BinFontPx;
	internal readonly string CaptionAttack, CaptionRetal;

	internal HistogramLayoutParams(
		float totalW, float totalH, float s,
		float wAttack, float wRetal, float gap,
		float borderPad, float blockH, float plotH, float pad, float axisR,
		Font capFont, Font binFont,
		int capFontPx, int binFontPx,
		string captionAttack, string captionRetal)
	{
		TotalW = totalW; TotalH = totalH; S = s;
		WAttack = wAttack; WRetal = wRetal; Gap = gap;
		BorderPad = borderPad; BlockH = blockH; PlotH = plotH; Pad = pad; AxisR = axisR;
		CapFont = capFont; BinFont = binFont;
		CapFontPx = capFontPx; BinFontPx = binFontPx;
		CaptionAttack = captionAttack; CaptionRetal = captionRetal;
	}

	/// <summary>O(1) key for when PMF <see cref="DamageHistogramState.PmfDataSequence"/> and view token are
	/// unchanged; avoids re-histogramming probability arrays to validate the uGUI signature each repaint.</summary>
	internal ulong LayoutStableKey()
	{
		static int Q6(float f) => Mathf.RoundToInt(f * 64f);
		ulong h = 0xCBF2_9CE4_8422_2037UL;
		void W(int a)
		{
			unchecked
			{
				h = h * 1099511628211UL ^ (ulong) (uint) a;
			}
		}
		W(Q6(TotalW));
		W(Q6(TotalH));
		W(Q6(S));
		W(Q6(WAttack));
		W(Q6(WRetal));
		W(Q6(Gap));
		W(Q6(BorderPad));
		W(Q6(BlockH));
		W(Q6(PlotH));
		W(Q6(Pad));
		W(Q6(AxisR));
		W(CapFontPx);
		W(BinFontPx);
		W(
			CapFont != null && !CapFont.Equals(null) ? CapFont.GetInstanceID() : 0
		);
		W(
			BinFont != null && !BinFont.Equals(null) ? BinFont.GetInstanceID() : 0
		);
		return h;
	}
}

/// <summary>uGUI kill PMF as a <b>child of the game damage forecast <see cref="RectTransform"/></b>, so it uses the
/// same Canvas / scale as the working tooltip. IMGUI+GL is the fallback when the panel is not tracked (see
/// <see cref="DamageHistogramSettings.UsePanelCanvasUgui"/>).</summary>
internal static class DamageHistogramPanelUgui
{
	private static GameObject s_root;
	private static int s_rootParentId;
	private static bool s_logOnce;
	private static Sprite s_white1;
	private static Sprite s_round9;
	private static Texture2D s_softBackTex;
	private static Sprite s_softBackSprite;
	private static int s_softW;
	private static int s_softH;
	private static int s_softFeather;
	private const float PlacingMargin = 16f;
	private const float UguiPanelSidePad = 12f;

	// Persistent Screen Space Overlay canvas owned by the mod. Rendering on our own canvas at
	// sortingOrder 32700 keeps the histogram in front of game world objects (grass, rocks, etc.)
	// regardless of how the game's canvas is configured, and eliminates the canvas-scale mismatch
	// that caused incorrect sizing when the game's canvas scaleFactor ≠ 1.
	private static Canvas s_overlayCanvas;
	private static RectTransform s_overlayRt;

	private static ulong s_lastPmfPresentSignature;
	private static bool s_havePmfPresentSignature;

	/// <summary>When <see cref="DamageHistogramState.PmfDataSequence"/> / <see cref="DamageHistogramState.PmfViewToken"/>
	/// and <see cref="HistogramLayoutParams.LayoutStableKey"/> are unchanged, reuse the last full signature without
	/// re-hashing probability arrays.</summary>
	private static int s_memoPmfDataSeq = -1;
	private static int s_memoPmfViewToken = -1;
	private static ulong s_memoLayoutKeyU;
	private static ulong s_memoPmfLayoutSignature;


	private static void EnsureOverlayCanvas()
	{
		if (s_overlayCanvas != null && !s_overlayCanvas.Equals(null))
			return;
		var go = new GameObject("ModHistogramOverlay");
		Object.DontDestroyOnLoad(go);
		go.hideFlags = HideFlags.HideAndDontSave;
		s_overlayCanvas = go.AddComponent<Canvas>();
		s_overlayCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
		s_overlayCanvas.sortingOrder = 32700;
		s_overlayRt = go.GetComponent<RectTransform>();
	}

	/// <summary>Follows the mouse cursor, preferring right-and-below offset and clamping to screen bounds.</summary>
	private static void PlaceNearMouse(RectTransform sRoot, float totalW, float totalH)
	{
		// Event.current.mousePosition: IMGUI coords — x from left, y from TOP.
		// Overlay canvas anchor (0,1) top-left: anchoredPosition maps directly (y = -yFromTop).
		var ev = Event.current;
		if (ev == null) return;
		var m = PlacingMargin;
		var mx = ev.mousePosition.x;
		var my = ev.mousePosition.y; // y from top
		const float off = 20f;

		// Prefer right of cursor, fall back to left
		var x = mx + off;
		if (x + totalW > Screen.width - m)
			x = mx - off - totalW;
		x = Mathf.Clamp(x, m, Mathf.Max(m, Screen.width - totalW - m));

		// Below cursor = larger y-from-top
		var yFromTop = my + off;
		yFromTop = Mathf.Clamp(yFromTop, m, Screen.height - totalH - m);

		sRoot.anchoredPosition = new Vector2(x, -yFromTop);
	}

	internal static void TearDown()
	{
		DestroyPmfUguiRoot();
		ReleaseSoftBackSprite();
		DamageHistogramGuiBehaviour.InvalidateUguiLayoutCache();
	}

	private static void DestroyPmfUguiRoot()
	{
		if (s_root != null)
		{
			Object.Destroy(s_root);
			s_root = null;
		}
		s_rootParentId = 0;
		s_lastPmfPresentSignature = 0U;
		s_havePmfPresentSignature = false;
		s_memoPmfDataSeq = -1;
		s_memoPmfViewToken = -1;
	}

	internal static void Present(
		RectTransform panel,
		Sprite gameFrame,
		DamageDistribution.HistogramSnapshot forward,
		DamageDistribution.HistogramSnapshot retal,
		bool showRetalChart,
		in HistogramLayoutParams layout)
	{
		if (panel == null
		    || panel.gameObject == null
		    || !panel.gameObject.activeInHierarchy)
		{
			TearDown();
			return;
		}

		var layoutKeyU = layout.LayoutStableKey();
		ulong sig;
		if (s_memoPmfDataSeq == DamageHistogramState.PmfDataSequence
		    && s_memoPmfViewToken == DamageHistogramState.PmfViewToken
		    && s_memoLayoutKeyU == layoutKeyU)
		{
			sig = s_memoPmfLayoutSignature;
		}
		else
		{
			sig = ComputePmfLayoutSignature(
				panel,
				gameFrame,
				forward,
				retal,
				showRetalChart,
				in layout
			);
			s_memoPmfLayoutSignature = sig;
			s_memoPmfDataSeq = DamageHistogramState.PmfDataSequence;
			s_memoPmfViewToken = DamageHistogramState.PmfViewToken;
			s_memoLayoutKeyU = layoutKeyU;
		}
		if (s_havePmfPresentSignature
		    && sig == s_lastPmfPresentSignature
		    && s_root != null
		    && s_rootParentId == panel.GetInstanceID()
		    && s_overlayRt != null
		    && s_root.transform.parent == s_overlayRt
		    && s_root.transform.childCount > 0)
		{
			s_root.SetActive(true);
			// Mouse-relative placement is cheap — always update so panel follows the cursor.
			var rtf = s_root.GetComponent<RectTransform>();
			if (rtf != null)
				PlaceNearMouse(rtf, layout.TotalW, layout.TotalH);
			return;
		}

		EnsureSprites();
		EnsureOverlayCanvas();
		if (s_root == null
		    || s_rootParentId != panel.GetInstanceID()
		    || s_overlayRt == null
		    || s_root.transform.parent != s_overlayRt)
		{
			DestroyPmfUguiRoot();
			s_root = new GameObject("ModKillPmf");
			s_root.transform.SetParent(s_overlayRt, false);
			s_rootParentId = panel.GetInstanceID();
		}

		s_root.SetActive(true);
		var rt = s_root.GetComponent<RectTransform>();
		if (rt == null)
		{
			rt = s_root.AddComponent<RectTransform>();
		}
		rt.anchorMin = new Vector2(0f, 1f);
		rt.anchorMax = new Vector2(0f, 1f);
		rt.pivot = new Vector2(0f, 1f);
		rt.sizeDelta = new Vector2(layout.TotalW, layout.TotalH);
		rt.localScale = Vector3.one;
		DestroyAllChildren(s_root.transform);

		{
			var softGo = new GameObject("SoftBack");
			softGo.transform.SetParent(s_root.transform, false);
			var so = softGo.AddComponent<Image>();
			so.raycastTarget = false;
			so.sprite = GetOrBuildSoftBackSprite(
				layout.TotalW,
				layout.TotalH,
				DamageHistogramSettings.PanelUguiEdgeFeatherPixels());
			so.type = Image.Type.Simple;
			so.preserveAspect = false;
			var srt = so.rectTransform;
			srt.anchorMin = new Vector2(0f, 1f);
			srt.anchorMax = new Vector2(0f, 1f);
			srt.pivot = new Vector2(0f, 1f);
			srt.anchoredPosition = Vector2.zero;
			srt.sizeDelta = new Vector2(layout.TotalW, layout.TotalH);
		}

		if (DamageHistogramSettings.UseNativeFrameSprite()
		    && gameFrame != null
		    && !gameFrame.Equals(null))
		{
			var n = new GameObject("GameFrame");
			var ni = n.AddComponent<Image>();
			ni.raycastTarget = false;
			ni.sprite = gameFrame;
			ni.type = Image.Type.Sliced;
			ni.preserveAspect = true;
			n.transform.SetParent(s_root.transform, false);
			var nrt = n.GetComponent<RectTransform>();
			nrt.anchorMin = new Vector2(0f, 1f);
			nrt.anchorMax = new Vector2(0f, 1f);
			nrt.pivot = new Vector2(0f, 1f);
			nrt.anchoredPosition = Vector2.zero;
			nrt.sizeDelta = new Vector2(layout.TotalW, layout.TotalH);
		}

		var row = new GameObject("Row");
		row.transform.SetParent(s_root.transform, false);
		var rowRt = row.AddComponent<RectTransform>();
		rowRt.anchorMin = new Vector2(0f, 1f);
		rowRt.anchorMax = new Vector2(0f, 1f);
		rowRt.pivot = new Vector2(0f, 1f);
		rowRt.anchoredPosition = new Vector2(layout.BorderPad, -layout.BorderPad);
		var innerW = layout.WAttack + (showRetalChart ? layout.Gap + layout.WRetal : 0f);
		rowRt.sizeDelta = new Vector2(innerW, layout.BlockH);

		FillBlock(
			row.transform,
			new Rect(0f, 0f, layout.WAttack, layout.BlockH),
			false,
			forward,
			in layout);

		if (showRetalChart && !retal.IsEmpty)
		{
			FillBlock(
				row.transform,
				new Rect(layout.WAttack + layout.Gap, 0f, layout.WRetal, layout.BlockH),
				true,
				retal,
				in layout);
		}

		PlaceNearMouse(rt, layout.TotalW, layout.TotalH);
		s_lastPmfPresentSignature = sig;
		s_havePmfPresentSignature = true;

		if (!s_logOnce)
		{
			s_logOnce = true;
			Plugin.LogSource?.LogInfo(
				"Damage histogram: Screen Space Overlay canvas (sortOrder 32700). IMGUI+GL fallback when panel not tracked.");
		}
	}

	private static ulong ComputePmfLayoutSignature(
		RectTransform panel,
		Sprite gameFrame,
		DamageDistribution.HistogramSnapshot forward,
		DamageDistribution.HistogramSnapshot retal,
		bool showRetalChart,
		in HistogramLayoutParams layout)
	{
		ulong h = 1468508857UL;
		h = Fnv1aI(h, panel.GetInstanceID());
		h = Fnv1aI(h, Quant6(layout.TotalW));
		h = Fnv1aI(h, Quant6(layout.TotalH));
		h = Fnv1aI(h, Quant6(layout.S));
		h = Fnv1aI(h, Quant6(layout.WAttack));
		h = Fnv1aI(h, Quant6(layout.WRetal));
		h = Fnv1aI(h, Quant6(layout.Gap));
		h = Fnv1aI(h, Quant6(layout.BorderPad));
		h = Fnv1aI(h, Quant6(layout.BlockH));
		h = Fnv1aI(h, Quant6(layout.PlotH));
		h = Fnv1aI(h, Quant6(layout.Pad));
		h = Fnv1aI(h, Quant6(layout.AxisR));
		h = Fnv1aI(h, layout.CapFontPx);
		h = Fnv1aI(h, layout.BinFontPx);
		h = Fnv1aI(h, showRetalChart ? 1 : 0);
		h = Fnv1aI(h, HistogramContentHash(forward));
		h = Fnv1aI(h, showRetalChart ? HistogramContentHash(retal) : 0);
		h = Fnv1aI(h, DamageHistogramSettings.UseNativeFrameSprite() ? 1 : 0);
		h = Fnv1aI(
			h,
			gameFrame != null && !gameFrame.Equals(null)
				? gameFrame.GetInstanceID()
				: 0);
		h = Fnv1aI(h, DamageHistogramSettings.PanelUguiEdgeFeatherPixels());
		return h;
	}

	private static int Quant6(float f) => Mathf.RoundToInt(f * 64f);

	internal static int HistogramContentHash(
		DamageDistribution.HistogramSnapshot h
	)
	{
		if (h == null || h.Probabilities == null || h.Probabilities.Length == 0)
		{
			return 19;
		}
		unchecked
		{
			var p = h.Probabilities;
			var x = 17 + h.MinOutcome * 101 + h.MaxOutcome * 103 + p.Length * 107;
			for (var i = 0; i < p.Length; i++)
			{
				x = (x * 1000003) ^ p[i].GetHashCode();
			}
			if (h.LuckSharePerBin != null
			    && h.LuckSharePerBin.Length == p.Length)
			{
				for (var i = 0; i < p.Length; i++)
				{
					x = (x * 1000003) ^ h.LuckSharePerBin[i].GetHashCode();
				}
			}
			return x;
		}
	}

	// FNV-1a: XOR-then-multiply (not multiply-then-XOR).
	private static ulong Fnv1aI(ulong h, int v)
	{
		unchecked
		{
			return (h ^ (ulong)(uint)v) * 1099511628211UL;
		}
	}

	/// <summary>Prefer right of the forecast panel, fall back to left, then nudge into <see cref="Screen.safeArea"/>.
	/// Calls <see cref="Canvas.ForceUpdateCanvases"/> three times; gate the call with the panel-position cache in
	/// <see cref="Present"/> to avoid this cost every repaint frame.</summary>
	private static void PlaceAndClampInScreen(
		RectTransform sRoot,
		RectTransform parentPanel,
		float totalW,
		float totalH)
	{
		_ = totalH;
		var qp = parentPanel.rect;
		var toRight = new Vector2(qp.width + UguiPanelSidePad, -UguiPanelSidePad);
		var toLeft = new Vector2(-UguiPanelSidePad - totalW, -UguiPanelSidePad);
		var canvas = sRoot.GetComponentInParent<Canvas>();
		if (canvas == null)
		{
			sRoot.anchoredPosition = toRight;
			return;
		}
		var cam = ResolveProjectCamera(canvas);
		if (cam == null || cam.Equals(null))
		{
			sRoot.anchoredPosition = toRight;
			return;
		}
		sRoot.anchoredPosition = toRight;
		Canvas.ForceUpdateCanvases();
		NudgeIntoSafeArea(sRoot, parentPanel, cam);
		var sRight = OutOfScreenPenalty(sRoot, cam);
		sRoot.anchoredPosition = toLeft;
		Canvas.ForceUpdateCanvases();
		NudgeIntoSafeArea(sRoot, parentPanel, cam);
		var sLeft = OutOfScreenPenalty(sRoot, cam);
		sRoot.anchoredPosition = sLeft + 2f < sRight ? toLeft : toRight;
		Canvas.ForceUpdateCanvases();
		NudgeIntoSafeArea(sRoot, parentPanel, cam);
	}

	private static Camera ResolveProjectCamera(Canvas canvas)
	{
		if ((canvas.renderMode == RenderMode.ScreenSpaceCamera || canvas.renderMode == RenderMode.WorldSpace)
		    && canvas.worldCamera != null
		    && !canvas.worldCamera.Equals(null))
		{
			return canvas.worldCamera;
		}
		return Camera.main;
	}

	private static readonly Vector3[] s_wc4 = new Vector3[4];

	private static void NudgeIntoSafeArea(RectTransform child, RectTransform parent, Camera cam)
	{
		if (cam == null || cam.Equals(null))
		{
			return;
		}
		var sA = Screen.safeArea;
		for (var iter = 0; iter < 4; iter++)
		{
			if (!TryScreenAabb(child, cam, out var minS, out var maxS))
			{
				return;
			}
			var m = PlacingMargin;
			var dlx = 0f;
			var dly = 0f;
			if (minS.x < sA.xMin + m) dlx += sA.xMin + m - minS.x;
			if (maxS.x > sA.xMax - m) dlx += sA.xMax - m - maxS.x;
			if (minS.y < sA.yMin + m) dly += sA.yMin + m - minS.y;
			if (maxS.y > sA.yMax - m) dly += sA.yMax - m - maxS.y;
			if (dlx * dlx + dly * dly < 0.1f)
			{
				return;
			}
			ApplyParentDeltaFromScreenDelta(child, parent, cam, dlx, dly);
		}
	}

	private static float OutOfScreenPenalty(RectTransform t, Camera cam)
	{
		if (cam == null
		    || cam.Equals(null)
		    || !TryScreenAabb(t, cam, out var minS, out var maxS))
		{
			return 0f;
		}
		var sA = Screen.safeArea;
		var m = PlacingMargin;
		var px = 0f;
		if (minS.x < sA.xMin + m) px += sA.xMin + m - minS.x;
		if (maxS.x > sA.xMax - m) px += maxS.x - (sA.xMax - m);
		if (minS.y < sA.yMin + m) px += sA.yMin + m - minS.y;
		if (maxS.y > sA.yMax - m) px += maxS.y - (sA.yMax - m);
		return px;
	}

	private static bool TryScreenAabb(
		RectTransform t,
		Camera cam,
		out Vector2 minS,
		out Vector2 maxS)
	{
		minS = default;
		maxS = default;
		if (cam == null || cam.Equals(null))
		{
			return false;
		}
		t.GetWorldCorners(s_wc4);
		minS = (Vector2)cam.WorldToScreenPoint(s_wc4[0]);
		maxS = minS;
		for (var i = 1; i < 4; i++)
		{
			var p = (Vector2)cam.WorldToScreenPoint(s_wc4[i]);
			minS = Vector2.Min(minS, p);
			maxS = Vector2.Max(maxS, p);
		}
		return true;
	}

	private static void ApplyParentDeltaFromScreenDelta(
		RectTransform child,
		RectTransform parent,
		Camera cam,
		float dlx,
		float dly)
	{
		if (dlx * dlx + dly * dly < 1E-6f || cam == null || cam.Equals(null))
		{
			return;
		}
		child.GetWorldCorners(s_wc4);
		var a = (Vector2)cam.WorldToScreenPoint(s_wc4[0]);
		var b = a + new Vector2(dlx, dly);
		RectTransformUtility.ScreenPointToLocalPointInRectangle(parent, a, cam, out var la);
		RectTransformUtility.ScreenPointToLocalPointInRectangle(parent, b, cam, out var lb);
		child.anchoredPosition += lb - la;
	}

	private static void ReleaseSoftBackSprite()
	{
		if (s_softBackSprite != null && !s_softBackSprite.Equals(null))
		{
			Object.Destroy(s_softBackSprite);
		}
		s_softBackSprite = null;
		if (s_softBackTex != null && !s_softBackTex.Equals(null))
		{
			Object.Destroy(s_softBackTex);
		}
		s_softBackTex = null;
		s_softW = 0;
		s_softH = 0;
		s_softFeather = 0;
	}

	/// <summary>Half-res RGBA with smooth alpha falloff at the edges, stretched to full size for extra blurriness
	/// (bilinear+upscale). Keyed on w/h/feather so re-rasterization only happens when those change.</summary>
	private static Sprite GetOrBuildSoftBackSprite(float width, float height, int featherLogicalPx)
	{
		var wKey = Mathf.Max(2, Mathf.RoundToInt(width));
		var hKey = Mathf.Max(2, Mathf.RoundToInt(height));
		var fKey = Mathf.Clamp(featherLogicalPx, 8, 120);
		if (s_softBackSprite != null
		    && s_softW == wKey
		    && s_softH == hKey
		    && s_softFeather == fKey
		    && !s_softBackSprite.Equals(null))
		{
			return s_softBackSprite;
		}
		ReleaseSoftBackSprite();
		var xn = Mathf.Max(2, Mathf.CeilToInt(wKey * 0.5f));
		var xx = Mathf.Max(2, Mathf.CeilToInt(hKey * 0.5f));
		var f = Mathf.Max(1, Mathf.CeilToInt(fKey * 0.5f));
		s_softW = wKey;
		s_softH = hKey;
		s_softFeather = fKey;
		s_softBackTex = new Texture2D(xn, xx, TextureFormat.RGBA32, false);
		s_softBackTex.wrapMode = TextureWrapMode.Clamp;
		s_softBackTex.filterMode = FilterMode.Bilinear;
		var softPx = new Color32[xn * xx];
		for (var y = 0; y < xx; y++)
		{
			for (var x = 0; x < xn; x++)
			{
				var d = Mathf.Min(
					Mathf.Min(x + 1, xn - x),
					Mathf.Min(y + 1, xx - y));
				var t1 = (d < f && f > 0) ? Smooth((float)d / f) : 1f;
				var a = (byte)Mathf.RoundToInt(0.62f * t1 * 255f);
				softPx[y * xn + x] = new Color32(13, 13, 17, a);
			}
		}
		s_softBackTex.SetPixels32(softPx);
		s_softBackTex.Apply();
		s_softBackSprite = Sprite.Create(
			s_softBackTex,
			new Rect(0, 0, xn, xx),
			new Vector2(0f, 1f),
			100f);
		return s_softBackSprite;
	}

	private static float Smooth(float t)
	{
		t = Mathf.Clamp01(t);
		return t * t * (3f - 2f * t);
	}

	private static void DestroyAllChildren(Transform t)
	{
		for (var i = t.childCount - 1; i >= 0; i--)
		{
			Object.Destroy(t.GetChild(i).gameObject);
		}
	}

	/// <summary>Local <paramref name="chartRegion"/> in parent space, top-left origin, y down.</summary>
	private static void FillBlock(
		Transform parent,
		Rect chartRegion,
		bool retaliation,
		DamageDistribution.HistogramSnapshot snap,
		in HistogramLayoutParams layout)
	{
		if (snap.IsEmpty)
		{
			return;
		}
		var probabilities = snap.Probabilities;
		if (probabilities == null || probabilities.Length == 0)
		{
			return;
		}
		var pmax = 0f;
		var psum = 0f;
		for (var i = 0; i < probabilities.Length; i++)
		{
			pmax = Mathf.Max(pmax, probabilities[i]);
			psum += probabilities[i];
		}
		if (pmax <= 0f || psum <= 1E-15f)
		{
			return;
		}
		var contentW = chartRegion.width - layout.Pad * 2f - layout.AxisR;
		if (contentW < 2f)
		{
			return;
		}
		var captionText = retaliation
			? layout.CaptionRetal
			: layout.CaptionAttack;
		var capH = 2.5f * layout.S + Mathf.Max(12f, layout.CapFontPx * 1.25f);
		var blockGo = new GameObject("Block");
		blockGo.transform.SetParent(parent, false);
		var blockRt = blockGo.AddComponent<RectTransform>();
		blockRt.anchorMin = new Vector2(0f, 1f);
		blockRt.anchorMax = new Vector2(0f, 1f);
		blockRt.pivot = new Vector2(0f, 1f);
		blockRt.anchoredPosition = new Vector2(chartRegion.x, -chartRegion.y);
		blockRt.sizeDelta = new Vector2(chartRegion.width, chartRegion.height);

		var innerX = layout.Pad;
		var innerY = layout.Pad;
		var inner = new Rect(innerX, innerY, contentW, layout.PlotH);
		var plotR = new Rect(0f, 0f, chartRegion.width, layout.PlotH + layout.Pad * 2f);
		var outlineColor = new Color(1f, 1f, 1f, 0.1f);
		AddLine(blockGo.transform, new Rect(plotR.x, plotR.y, plotR.width, 1f), outlineColor);
		AddLine(blockGo.transform, new Rect(plotR.x, plotR.yMax - 1f, plotR.width, 1f), outlineColor);
		AddLine(blockGo.transform, new Rect(plotR.x, plotR.y, 1f, plotR.height), outlineColor);
		AddLine(blockGo.transform, new Rect(plotR.xMax - 1f, plotR.y, 1f, plotR.height), outlineColor);

		var tgo = new GameObject(retaliation ? "RetaliationCaption" : "AttackCaption");
		tgo.transform.SetParent(blockGo.transform, false);
		var capText = tgo.AddComponent<Text>();
		capText.text = captionText;
		capText.font = layout.CapFont ? layout.CapFont : UIFonts.Default;
		capText.fontSize = layout.CapFontPx;
		capText.fontStyle = FontStyle.Bold;
		capText.alignment = TextAnchor.UpperLeft;
		capText.color = new Color(0.92f, 0.92f, 0.95f, 1f);
		capText.raycastTarget = false;
		var capShadow = tgo.AddComponent<Shadow>();
		capShadow.effectColor = new Color(0f, 0f, 0f, 0.85f);
		capShadow.effectDistance = new Vector2(1f, -1f) * Mathf.Max(1f, layout.S);
		var tRt = capText.rectTransform;
		tRt.anchorMin = new Vector2(0f, 1f);
		tRt.anchorMax = new Vector2(0f, 1f);
		tRt.pivot = new Vector2(0f, 1f);
		tRt.anchoredPosition = new Vector2(inner.x, -inner.y);
		tRt.sizeDelta = new Vector2(contentW, capH);

		var dataTop = inner.y + capH;
		var dataInnerH = Mathf.Max(1f, inner.yMax - dataTop);
		var dataRect = new Rect(inner.x, dataTop, contentW, dataInnerH);
		var numberRowH = Mathf.Max(6f, 3f + layout.BinFontPx * 1.1f);
		var labelToBar = Mathf.Max(2.5f, 3.5f * layout.S);
		var bottomLineH = Mathf.Max(2f, 2.2f * layout.S);
		var barBottomY = dataRect.yMax - bottomLineH;
		var barHAvail = Mathf.Max(1f, (barBottomY - dataRect.y) - numberRowH - labelToBar);
		var barGapH = Mathf.Max(2.5f, 4.5f * layout.S);
		var n2 = probabilities.Length;
		var nCol = Mathf.Max(1, n2, DamageHistogramSettings.MinBars());
		var slotW = (dataRect.width - (nCol - 1) * barGapH) / nCol;
		var barW = Mathf.Max(1f, slotW);

		var gridColor = new Color(1f, 1f, 1f, 0.07f);
		for (var g = 1; g <= 2; g++)
		{
			var gy = barBottomY - barHAvail * g / 3f;
			AddLine(blockGo.transform, new Rect(dataRect.x, gy, contentW, 1f), gridColor);
		}

		var luck = snap.LuckSharePerBin;
		var hasLuck = luck != null && luck.Length == n2;
		var baseBar = new Color(0.95f, 0.95f, 0.97f, 0.97f);
		var goldBar = new Color(0.94f, 0.82f, 0.36f, 0.95f);
		var expIdx = 0f;
		for (var e = 0; e < n2; e++)
			expIdx += probabilities[e] / psum * e;
		var exX = dataRect.x + expIdx * (slotW + barGapH) + barW * 0.5f;
		exX = Mathf.Clamp(exX, dataRect.x, dataRect.x + contentW - 2f);

		for (var k2 = 0; k2 < n2; k2++)
		{
			if (probabilities[k2] <= 1E-8f)
			{
				continue;
			}
			var xSlot = dataRect.x + k2 * (slotW + barGapH);
			var barH = probabilities[k2] / pmax * barHAvail;
			var yTop = barBottomY - barH;
			var fLuck = 0f;
			if (hasLuck)
			{
				fLuck = Mathf.Clamp01(luck[k2]);
			}
			var barCol = hasLuck
				? Color.Lerp(
					baseBar,
					goldBar,
					fLuck)
				: baseBar;
			var bgo = new GameObject("B" + k2);
			bgo.transform.SetParent(blockGo.transform, false);
			var bi = bgo.AddComponent<Image>();
			bi.raycastTarget = false;
			bi.sprite = s_round9;
			bi.type = Image.Type.Sliced;
			bi.color = barCol;
			var br = bgo.GetComponent<RectTransform>();
			br.anchorMin = new Vector2(0f, 1f);
			br.anchorMax = new Vector2(0f, 1f);
			br.pivot = new Vector2(0f, 1f);
			br.anchoredPosition = new Vector2(xSlot, -yTop);
			br.sizeDelta = new Vector2(barW, barH);

			var lgo = new GameObject("L" + k2);
			lgo.transform.SetParent(blockGo.transform, false);
			var lab = lgo.AddComponent<Text>();
			lab.text = (snap.MinOutcome + k2).ToString();
			lab.font = layout.BinFont ? layout.BinFont : UIFonts.Default;
			lab.fontSize = layout.BinFontPx;
			lab.fontStyle = FontStyle.Bold;
			lab.alignment = TextAnchor.UpperCenter;
			lab.color = Color.white;
			lab.raycastTarget = false;
			var shadow = lgo.AddComponent<Shadow>();
			shadow.effectColor = new Color(0f, 0f, 0f, 0.85f);
			shadow.effectDistance = new Vector2(1f, -1f) * Mathf.Max(1f, layout.S);
			var labY = yTop - numberRowH - labelToBar;
			if (labY < dataRect.y)
			{
				labY = dataRect.y;
			}
			var lrt = lgo.GetComponent<RectTransform>();
			lrt.anchorMin = new Vector2(0f, 1f);
			lrt.anchorMax = new Vector2(0f, 1f);
			lrt.pivot = new Vector2(0f, 1f);
			lrt.anchoredPosition = new Vector2(xSlot, -labY);
			lrt.sizeDelta = new Vector2(barW, numberRowH);
		}

		AddLine(blockGo.transform,
			new Rect(exX - 1f, barBottomY - 5f, 2f, 5f + bottomLineH + 1f),
			new Color(0.94f, 0.82f, 0.36f, 0.88f));

		var z = new GameObject("Base");
		z.transform.SetParent(blockGo.transform, false);
		var zi = z.AddComponent<Image>();
		zi.raycastTarget = false;
		zi.sprite = s_round9;
		zi.type = Image.Type.Sliced;
		zi.color = new Color(1f, 1f, 1f, 0.28f);
		var zrt = z.GetComponent<RectTransform>();
		zrt.anchorMin = new Vector2(0f, 1f);
		zrt.anchorMax = new Vector2(0f, 1f);
		zrt.pivot = new Vector2(0f, 1f);
		zrt.anchoredPosition = new Vector2(dataRect.x, -(dataRect.yMax - bottomLineH));
		zrt.sizeDelta = new Vector2(dataRect.width, bottomLineH);
	}

	private static void AddLine(Transform blockT, Rect r, Color c)
	{
		var g = new GameObject("Line");
		g.transform.SetParent(blockT, false);
		var i = g.AddComponent<Image>();
		i.sprite = s_white1;
		i.type = Image.Type.Simple;
		i.color = c;
		i.raycastTarget = false;
		var t = g.GetComponent<RectTransform>();
		t.anchorMin = new Vector2(0f, 1f);
		t.anchorMax = new Vector2(0f, 1f);
		t.pivot = new Vector2(0f, 1f);
		t.anchoredPosition = new Vector2(r.x, -r.y);
		t.sizeDelta = new Vector2(r.width, r.height);
	}

	private static void EnsureSprites()
	{
		if (s_white1 == null || s_white1.Equals(null))
		{
			var ym = new Texture2D(1, 1, TextureFormat.RGBA32, false);
			ym.SetPixel(0, 0, Color.white);
			ym.Apply();
			s_white1 = Sprite.Create(ym, new Rect(0, 0, 1, 1), new Vector2(0.5f, 0.5f), 100f);
		}
		if (s_round9 == null || s_round9.Equals(null))
		{
			s_round9 = Rounded9Slice(32, 6);
		}
	}

	private static Sprite Rounded9Slice(int w, int b)
	{
		var t = new Texture2D(w, w, TextureFormat.RGBA32, false);
		var px = new Color32[w * w];
		var white = new Color32(255, 255, 255, 255);
		var clear = new Color32(0, 0, 0, 0);
		for (var y = 0; y < w; y++)
		{
			for (var x = 0; x < w; x++)
			{
				px[y * w + x] = InsideR(x, y, w, b) ? white : clear;
			}
		}
		t.SetPixels32(px);
		t.wrapMode = TextureWrapMode.Clamp;
		t.filterMode = FilterMode.Bilinear;
		t.Apply();
		return Sprite.Create(
			t,
			new Rect(0, 0, w, w),
			new Vector2(0.5f, 0.5f),
			100f,
			0,
			SpriteMeshType.FullRect,
			new Vector4(b, b, b, b));
	}

	private static bool InsideR(int x, int y, int w, int b)
	{
		var threshSq = (b - 0.5f) * (b - 0.5f);
		if (x < b && y < b) return DSq(x, y, b, b) <= threshSq;
		if (x >= w - b && y < b) return DSq(x, y, w - b, b) <= threshSq;
		if (x >= w - b && y >= w - b) return DSq(x, y, w - b, w - b) <= threshSq;
		if (x < b && y >= w - b) return DSq(x, y, b, w - b) <= threshSq;
		return true;
	}

	private static float DSq(int x, int y, float cx, float cy)
	{
		var dx = x - cx;
		var dy = y - cy;
		return dx * dx + dy * dy;
	}
}

internal static class UIFonts
{
	private static Font _d;

	internal static Font Default
	{
		get
		{
			if (_d == null || _d.Equals(null))
			{
				try
				{
					_d = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
				}
				catch
				{
					_d = null;
				}
				if (_d == null || _d.Equals(null))
				{
					try
					{
						_d = Resources.GetBuiltinResource<Font>("Arial.ttf");
					}
					catch
					{
					}
				}
			}
			return _d;
		}
	}
}
