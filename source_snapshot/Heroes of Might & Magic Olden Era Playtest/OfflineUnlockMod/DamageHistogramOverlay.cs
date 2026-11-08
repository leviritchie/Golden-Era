using System;
using System.Reflection;
using System.Threading;
using BepInEx;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class DamageHistogramSettings
{
	private static bool? _enabled;
	private static int? _convMax;
	private static int? _chartW;
	private static int? _chartH;
	private static int? _gap;
	private static bool? _useNativeFrame;
	private static bool? _panelUgui;
	private static int? _panelUguiLayoutPercent;
	private static int? _panelUguiEdgeFeatherPx;
	private static int? _fontScalePct;
	private static int? _minBars;

	internal const float HistogramContentScale = 1.0f;

	internal static void InvalidateCache()
	{
		_enabled = null;
		_convMax = null;
		_chartW = null;
		_chartH = null;
		_gap = null;
		_useNativeFrame = null;
		_panelUgui = null;
		_panelUguiLayoutPercent = null;
		_panelUguiEdgeFeatherPx = null;
		_fontScalePct = null;
		_minBars = null;
	}

	internal static bool ShouldApplyPatches()
	{
		if (!_enabled.HasValue)
		{
			_enabled = LauncherConfigReader.TryLoad()?.DamageHistograms ?? false;
		}
		return _enabled.Value;
	}

	internal static int ConvolutionMaxUnits()
	{
		if (!_convMax.HasValue)
		{
			var n = LauncherConfigReader.TryLoad()?.DamageHistogramConvolutionMaxUnits ?? 120;
			_convMax = Mathf.Clamp(n, 8, 400);
		}
		return _convMax.Value;
	}

	internal static int ChartWidthPx()
	{
		if (!_chartW.HasValue)
		{
			var n = LauncherConfigReader.TryLoad()?.DamageHistogramChartWidthPx ?? 275;
			_chartW = Mathf.Clamp(n, 48, 400);
		}
		return _chartW.Value;
	}

	internal static int ChartHeightPx()
	{
		if (!_chartH.HasValue)
		{
			var n = LauncherConfigReader.TryLoad()?.DamageHistogramChartHeightPx ?? 144;
			_chartH = Mathf.Clamp(n, 32, 400);
		}
		return _chartH.Value;
	}

	internal static int GapPx()
	{
		if (!_gap.HasValue)
		{
			var n = LauncherConfigReader.TryLoad()?.DamageHistogramGapPx ?? 12;
			_gap = Mathf.Clamp(n, 0, 80);
		}
		return _gap.Value;
	}

	internal static float UiScale()
	{
		return Mathf.Clamp((float)Screen.height / 1080f, 0.65f, 3.2f);
	}

	/// <summary>Default <c>false</c>: the cached <c>Frame_Damege_Back</c> sprite is fully opaque; drawing it on top of the new radial underlay made the underlay effectively invisible. Set to <c>true</c> in <c>config.json</c> to restore GL-drawn game chrome on top of the underlay.</summary>
	internal static bool UseNativeFrameSprite()
	{
		if (!_useNativeFrame.HasValue)
		{
			_useNativeFrame = LauncherConfigReader.TryLoad()
				?.DamageHistogramUseNativeFrameSprite
				?? false;
		}
		return _useNativeFrame.Value;
	}

	/// <summary>When <c>true</c>, the PMF is drawn in uGUI parented to the forecast
	/// <see cref="RectTransform"/> when tracked. When <c>false</c> (default) or no panel, use <c>OnGUI</c>+GL by the
	/// cursor (cheaper; luck still shown via lerp in <c>DrawHistogramBlock</c>).</summary>
	internal static bool UsePanelCanvasUgui()
	{
		if (!_panelUgui.HasValue)
		{
			_panelUgui = LauncherConfigReader.TryLoad()?.DamageHistogramPanelUgui ?? false;
		}
		return _panelUgui.Value;
	}

	/// <summary>Multiplier for uGUI PMF when parented to the forecast panel. Default 1.2 (120%).</summary>
	internal static float PanelUguiLayoutMultiplier()
	{
		if (!_panelUguiLayoutPercent.HasValue)
		{
			_panelUguiLayoutPercent = LauncherConfigReader.TryLoad()
				?.DamageHistogramPanelUguiLayoutPercent
				?? 120;
		}
		return Mathf.Clamp(
			_panelUguiLayoutPercent.Value / 100f,
			0.7f,
			2.5f
		);
	}

	/// <summary>Feather (edge fade) in logical px for the uGUI soft backplate. Default 40.</summary>
	internal static int PanelUguiEdgeFeatherPixels()
	{
		if (!_panelUguiEdgeFeatherPx.HasValue)
		{
			_panelUguiEdgeFeatherPx = LauncherConfigReader.TryLoad()
				?.DamageHistogramPanelUguiEdgeFeatherPx
				?? 40;
		}
		return Mathf.Clamp(
			_panelUguiEdgeFeatherPx.Value,
			8,
			120
		);
	}

	internal static float FontScaleMultiplier()
	{
		if (!_fontScalePct.HasValue)
			_fontScalePct = Mathf.Clamp(LauncherConfigReader.TryLoad()?.DamageHistogramFontScalePercent ?? 100, 50, 300);
		return _fontScalePct.Value / 100f;
	}

	internal static int MinBars()
	{
		if (!_minBars.HasValue)
			_minBars = Mathf.Clamp(LauncherConfigReader.TryLoad()?.DamageHistogramMinBars ?? 0, 0, 30);
		return _minBars.Value;
	}

	internal static void ApplyTunerOverride(
		int chartW, int chartH, int gapPx, int layoutPct, int featherPx,
		int fontScalePct, int minBars)
	{
		_chartW = Mathf.Clamp(chartW, 80, 600);
		_chartH = Mathf.Clamp(chartH, 32, 400);
		_gap = Mathf.Clamp(gapPx, 0, 80);
		_panelUguiLayoutPercent = Mathf.Clamp(layoutPct, 80, 200);
		_panelUguiEdgeFeatherPx = Mathf.Clamp(featherPx, 8, 120);
		_fontScalePct = Mathf.Clamp(fontScalePct, 50, 300);
		_minBars = Mathf.Clamp(minBars, 0, 30);
	}
}

internal static class DamageHistogramState
{
	private static readonly ReaderWriterLockSlim Rw = new(LockRecursionPolicy.NoRecursion);

	internal static DamageDistribution.HistogramSnapshot ForwardKills = new(
		Array.Empty<float>(),
		0,
		0);

	internal static DamageDistribution.HistogramSnapshot RetaliationKills = new(
		Array.Empty<float>(),
		0,
		0);

	internal static bool HasRetaliation;
	internal static volatile bool TooltipRetaliationRowVisible;
	internal static RectTransform ForecastPanelRect;
	internal static volatile bool PanelTracked;

	/// <summary>Populated by <see cref="DamageHistogramGameChrome"/> from the live forecast panel (for future uGUI-matched frame).</summary>
	internal static Sprite CachedDamagePanelFrameSprite;

	/// <summary>From <c>UnityEngine.UI.Text</c> on the same panel, if any — IMGUI can set <see cref="GUIStyle.font"/> to match.</summary>
	internal static Font CachedPreviewGuiFont;

	/// <summary>Font size (points) from the first suitable <c>TextMeshProUGUI</c> (or 0 to keep mod defaults).</summary>
	internal static int CachedPreviewTmpFontSize;

	/// <summary>Whether <see cref="CachedPreviewTmpFontSize"/> / legacy font was captured from the game (vs 0 = defaults).</summary>
	internal static bool CachedPreviewFontFromGame;

	/// <summary>Increments when <see cref="SetForward"/> stores a new (trimmed) PMF that differs in content. Used to skip
	/// the heavy <c>OnGUI</c> layout when charts are visually unchanged between repaints.</summary>
	internal static int PmfDataSequence;

	/// <summary>When the damage tooltip’s retal row visibility, panel anchor, or similar UI-only gating flips, the PMF
	/// arrays are unchanged but <c>OnGUI</c> must re-layout. Incremented from forecast-panel patches.</summary>
	internal static int PmfViewToken;

	/// <summary>Last panel <see cref="RectTransform.GetInstanceID"/> for <see cref="SetPanelRect"/>. 0 = none.</summary>
	private static int s_lastPanelRtId = -1;

	/// <summary>Last resolved counterattack indicator visibility; used to bump <see cref="PmfViewToken"/> on change.</summary>
	internal static bool s_lastCounterIndicatorVisible;

	internal static bool s_hadFirstForecastShow;

	/// <summary>Pending hashes for <see cref="SetForward"/> no-op (same trimmed PMF as already stored).</summary>
	private static int s_lastHf;
	private static int s_lastHr;
	private static bool s_lastHasRetal;

	static DamageHistogramState()
	{
		s_lastHf = int.MinValue;
		s_lastHr = int.MinValue;
	}

	internal static void Clear()
	{
		Rw.EnterWriteLock();
		try
		{
			ForwardKills = new DamageDistribution.HistogramSnapshot(Array.Empty<float>(), 0, 0);
			RetaliationKills = new DamageDistribution.HistogramSnapshot(Array.Empty<float>(), 0, 0);
			HasRetaliation = false;
			TooltipRetaliationRowVisible = false;
			ForecastPanelRect = null;
			PanelTracked = false;
			CachedDamagePanelFrameSprite = null;
			CachedPreviewGuiFont = null;
			CachedPreviewTmpFontSize = 0;
			CachedPreviewFontFromGame = false;
		}
		finally
		{
			Rw.ExitWriteLock();
		}
		PmfDataSequence++;
		PmfViewToken++;
		s_lastHf = int.MinValue;
		s_lastHr = int.MinValue;
		s_hadFirstForecastShow = false;
		s_lastPanelRtId = -1;
		DamageHistogramPanelUgui.TearDown();
		DamageHistogramForecastRecorder.InvalidateInputCache();
	}

	internal static void SetForward(
		DamageDistribution.HistogramSnapshot snap,
		DamageDistribution.HistogramSnapshot retal,
		bool hasRetal)
	{
		var f = DamageDistribution.TrimToNonZeroSupport(
			snap,
			1E-7f
		);
		var r = DamageDistribution.TrimToNonZeroSupport(
			retal,
			1E-7f
		);
		var nh = DamageHistogramPanelUgui.HistogramContentHash(f);
		var nhr = DamageHistogramPanelUgui.HistogramContentHash(r);
		if (hasRetal == s_lastHasRetal
		    && nh == s_lastHf
		    && nhr == s_lastHr)
		{
			return;
		}
		Rw.EnterWriteLock();
		try
		{
			ForwardKills = f;
			RetaliationKills = r;
			HasRetaliation = hasRetal;
		}
		finally
		{
			Rw.ExitWriteLock();
		}
		s_lastHf = nh;
		s_lastHr = nhr;
		s_lastHasRetal = hasRetal;
		PmfDataSequence++;
	}

	internal static void SetPanelRect(RectTransform rt)
	{
		var id = rt != null && !rt.Equals(null) ? rt.GetInstanceID() : 0;
		if (s_lastPanelRtId != id)
		{
			if (s_lastPanelRtId != -1)
			{
				PmfViewToken++;
			}
			s_lastPanelRtId = id;
		}
		Rw.EnterWriteLock();
		try
		{
			ForecastPanelRect = rt;
			PanelTracked = rt != null;
		}
		finally
		{
			Rw.ExitWriteLock();
		}
	}

	/// <summary>Called when <see cref="BhHealDamageForecastPanel.Hide"/> runs. Clears the attack chart too — otherwise
	/// the forward kill PMF would stay non-empty and the IMGUI cluster would keep following the cursor after the game
	/// closed the damage tooltip (retaliation only “worked” because that chart was gated on <see cref="TooltipRetaliationRowVisible"/>).</summary>
	internal static void ClearPanelAnchor()
	{
		Clear();
	}

	internal static bool TryReadForGui(
		out DamageDistribution.HistogramSnapshot forward,
		out DamageDistribution.HistogramSnapshot retal,
		out bool hasRetal,
		out bool showRetalChart,
		out RectTransform panelRt,
		out Sprite gamePanelFrameSprite)
	{
		Rw.EnterReadLock();
		try
		{
			forward = ForwardKills;
			retal = RetaliationKills;
			hasRetal = HasRetaliation;
			panelRt = ForecastPanelRect;
			showRetalChart = hasRetal && !retal.IsEmpty && TooltipRetaliationRowVisible;
			gamePanelFrameSprite = CachedDamagePanelFrameSprite;
			// Shipped v0.1.0 also required a tracked panel; in IL2CPP + merge-config setups that can block all draws
			// even when bdwu/oez is recording. We only need non-empty forward PMF to show near the mouse.
			return forward.Probabilities != null && forward.Probabilities.Length != 0;
		}
		finally
		{
			Rw.ExitReadLock();
		}
	}
}

internal static class DamageHistogramBootstrap
{
	private const string GoName = "DamageHistogramImGui";
	private static bool _registered;
	private static bool _attached;
	private static bool _logOnce;

	/// <summary>IL2CPP: managed MonoBehaviours on the BepInEx process must be registered; plain AddComponent on BasePlugin is unreliable.</summary>
	internal static void Ensure()
	{
		if (_attached)
		{
			return;
		}
		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<DamageHistogramGuiBehaviour>();
				_registered = true;
			}
			// Unity 6 IL2CPP: Object.FindObjectOfType<T> often fails with
			// NotSupportedException: Method unstripping failed — do not use it for host lookup.
			// `Ensure` runs once per chainload; duplicate check is the `_attached` flag.
			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<DamageHistogramGuiBehaviour>() == null)
			{
				Plugin.LogSource?.LogError("Damage histogram: AddComponent returned null.");
			}
			UnityObject.DontDestroyOnLoad(go);
			_attached = true;
			if (!_logOnce)
			{
				_logOnce = true;
				Plugin.LogSource?.LogInfo(
					"Damage histogram: registered Il2Cpp type + IMGUI host (" + GoName + ").");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Damage histogram GUI could not start: " + ex);
		}
	}
}

public sealed class DamageHistogramGuiBehaviour : MonoBehaviour
{
	private static bool s_uguiLayoutCacheValid;
	private static HistogramLayoutParams s_uguiCachedLayout;
	private static int s_uguiCachePmfSeq;
	private static int s_uguiCacheViewToken;
	private static bool s_uguiCacheShowRetal;
	private static int s_uguiCacheScreenW;
	private static int s_uguiCacheScreenH;
	private static int s_uguiCacheLoadGen;

	/// <summary>Clears the <see cref="OnGUI"/> layout skip cache (e.g. tooltip cleared or config reloaded).</summary>
	internal static void InvalidateUguiLayoutCache()
	{
		s_uguiLayoutCacheValid = false;
	}

	private GUIStyle _labelStyle;
	private GUIStyle _killOnBarStyle;
	private GUIStyle _chartCaptionStyle;
	private GUIStyle _binNumberStyle;
	private static Font s_builtinAxisBinFont;
	private static bool s_builtinAxisBinFontResolved;

	// Radial fill: more opaque in the center, nearly invisible at edges (see DrawRadialRoundedVignetteFill).
	private const float MainPanelVignetteCenterA = 0.72f;

	private const float MainPanelVignetteEdgeA = 0.0f;
	private const float MainPanelVignetteFalloffPower = 2.35f;

	/// <summary>Very dark blue, multiplied per-cell (RGB); alpha is driven by radial lerp above.</summary>
	private static readonly Color MainPanelVignetteFillRgb = new(0.05f, 0.05f, 0.08f, 1f);

	private const string ChartCaptionAttack = "Kills (Attack)";
	private const string ChartCaptionRetal = "Deaths (Retaliation)";

	/// <summary>Cached for drawing captured forecast-panel sprites. Do not use <see cref="Graphics.DrawTexture"/> in OnGUI — it can access-violate under IL2CPP when combined with the IMGUI state machine.</summary>
	private static Material s_gameFrameUnlit;

	/// <summary>White/vertex-color GL draws (histogram bars) — not shared with atlas textures.</summary>
	private static Material s_solidUnlit;

	/// <summary>Once: explain that the forecast-panel sprite path still uses the same IMGUI underlay (see <see cref="DrawPopupMenuFrame"/>).</summary>
	private static bool s_logOnceVignetteWithGameFrame;

	/// <summary>Once: default path skips the opaque game frame so the mod radial is visible.</summary>
	private static bool s_logOnceVignetteModOnly;

	/// <summary>Once: IMGUI underlay (rect, grid) so we can confirm the fill path in LogOutput if needed.</summary>
	private static bool s_logOnceVignetteImguiMeta;

	/// <summary>Widest kill-count string for one snapshot — used to size bars so text never clips.</summary>
	private static float MeasureMaxBinLabelWidth(
		DamageDistribution.HistogramSnapshot snap,
		GUIStyle style
	)
	{
		var w = 0f;
		var p = snap.Probabilities;
		if (p == null
		    || p.Length == 0)
		{
			return 0f;
		}
		for (var i = 0; i < p.Length; i++)
		{
			if (p[i] > 1E-12f)
			{
				var t = (snap.MinOutcome + i).ToString();
				w = Mathf.Max(
					w,
					style.CalcSize(
						new GUIContent(t)
					).x
				);
			}
		}
		return w;
	}

	private void OnGUI()
	{
		if (Event.current == null) return;

		// F9 toggles the tuner overlay
		if (Event.current.type == EventType.KeyDown && Event.current.keyCode == KeyCode.F9)
		{
			s_tunerOpen = !s_tunerOpen;
			if (s_tunerOpen) LoadTunerFromConfig();
			Event.current.Use();
			return;
		}

		// Tuner receives all event types so sliders/buttons are fully interactive
		if (s_tunerOpen)
		{
			GUI.depth = -3000;
			DrawTuner();
			GUI.depth = -2000;
		}

		// Only Repaint should touch the histogram — prevents destroying the uGUI tree on Layout events.
		if (Event.current.type != EventType.Repaint)
			return;
		if (
			!DamageHistogramSettings.ShouldApplyPatches()
			|| !DamageHistogramState.TryReadForGui(
				out var forward,
				out var retal,
				out _,
				out var showRetalChart,
				out var forecastPanel,
				out var gameFrame))
		{
			DamageHistogramPanelUgui.TearDown();
			return;
		}
		forward = DamageDistribution.TrimToNonZeroSupport(
			forward,
			1E-7f
		);
		if (forward.IsEmpty)
		{
			DamageHistogramPanelUgui.TearDown();
			return;
		}
		if (showRetalChart)
		{
			retal = DamageDistribution.TrimToNonZeroSupport(
				retal,
				1E-7f
			);
			if (retal.IsEmpty)
			{
				showRetalChart = false;
			}
		}
		GUI.depth = -2000;

		var usePanelUguiThisFrame = DamageHistogramSettings.UsePanelCanvasUgui()
			&& forecastPanel != null
			&& forecastPanel.gameObject != null
			&& forecastPanel.gameObject.activeInHierarchy;
		if (usePanelUguiThisFrame)
		{
			var loadGen = LauncherConfigReader.LoadGeneration;
			if (s_uguiLayoutCacheValid
			    && s_uguiCachePmfSeq == DamageHistogramState.PmfDataSequence
			    && s_uguiCacheViewToken == DamageHistogramState.PmfViewToken
			    && s_uguiCacheShowRetal == showRetalChart
			    && s_uguiCacheScreenW == Screen.width
			    && s_uguiCacheScreenH == Screen.height
			    && s_uguiCacheLoadGen == loadGen)
			{
				DamageHistogramPanelUgui.Present(
					forecastPanel,
					gameFrame,
					forward,
					retal,
					showRetalChart,
					in s_uguiCachedLayout
				);
				return;
			}
		}
		var s0 = DamageHistogramSettings.UiScale() * DamageHistogramSettings.HistogramContentScale
			* (usePanelUguiThisFrame
				? DamageHistogramSettings.PanelUguiLayoutMultiplier()
				: 1f);
		int nF = 1;
		if (forward.Probabilities != null
		    && forward.Probabilities.Length > 0)
		{
			nF = forward.Probabilities.Length;
		}
		int nR = 0;
		if (showRetalChart
		    && retal.Probabilities != null
		    && retal.Probabilities.Length > 0)
		{
			nR = retal.Probabilities.Length;
		}
		var minBarsLayout = DamageHistogramSettings.MinBars();
		if (minBarsLayout > 0)
		{
			nF = Mathf.Max(nF, minBarsLayout);
			if (showRetalChart) nR = Mathf.Max(nR, minBarsLayout);
		}
		var maxTotal = (float)Screen.width - 32f;
		var maxTotalH = (float)Screen.height - 48f;
		// Web-like fit: at most two passes; second pass reuses measured label widths and screen scale.
		var layoutScaleK = 1f;
		float s = s0;
		var gap = 0f;
		var wAttack = 0f;
		var wRetal = 0f;
		var plotH = 0f;
		var blockH = 0f;
		var pad = 0f;
		var borderPad = 0f;
		var unclampedTotal = 0f;
		for (var layoutPass = 0; layoutPass < 2; layoutPass++)
		{
			s = s0 * layoutScaleK;
			gap = (float)DamageHistogramSettings.GapPx() * s;
			var baseChartW = (float)DamageHistogramSettings.ChartWidthPx() * s;
			plotH = (float)DamageHistogramSettings.ChartHeightPx() * s;
			pad = 9f * s;
			borderPad = 14f * s;
			blockH = plotH + pad * 2f;
			// Min width per bar from measured labels (tighten after styles exist)
			var minWPerF = 10f * s;
			var minWPerR = 10f * s;
			var minBarWFloor = 4.5f * s;
			var interBarGaps = Mathf.Max(2.5f, 4.5f * s);
			var axisRightPad = 10f * s;
			float Wfor(
				int n,
				float mPer
			)
			{
				if (n <= 0)
				{
					n = 1;
				}
				var nGap = n > 1
					? n - 1
					: 0;
				return Mathf.Max(
					baseChartW,
					pad * 2f
					+ n * mPer
					+ nGap * interBarGaps
					+ axisRightPad
				);
			}
			wAttack = Wfor(
				nF,
				minWPerF
			);
			wRetal = showRetalChart
				? Wfor(
					nR,
					minWPerR
				)
				: 0f;
			unclampedTotal = wAttack + (showRetalChart
				? wRetal + gap
				: 0f) + borderPad * 2f;
			if (unclampedTotal > maxTotal
			    && nF + nR > 0
			   )
			{
				for (var t = 0; t < 6
				    && unclampedTotal > maxTotal
				    && (minWPerF > minBarWFloor + 0.01f
				        || minWPerR > minBarWFloor + 0.01f
				       ); t++)
				{
					minWPerF = Mathf.Max(
						minBarWFloor,
						minWPerF * 0.82f
					);
					minWPerR = Mathf.Max(
						minBarWFloor,
						minWPerR * 0.82f
					);
					wAttack = Wfor(
						nF,
						minWPerF
					);
					wRetal = showRetalChart
						? Wfor(
							nR,
							minWPerR
						)
						: 0f;
					unclampedTotal = wAttack + (showRetalChart
						? wRetal + gap
						: 0f) + borderPad * 2f;
				}
			}
			{
				var maxInnerW = maxTotal - borderPad * 2f;
				var gapW = showRetalChart
					? gap
					: 0f;
				var chartWsum = wAttack + (showRetalChart
					? wRetal
					: 0f);
				if (chartWsum + gapW > maxInnerW
				    && maxInnerW > gapW + 1f
				    && chartWsum > 0.1f
				   )
				{
					var f = (maxInnerW - gapW) / chartWsum;
					if (f < 0.999f
					    && f > 0.05f
					   )
					{
						var minW = pad * 2f + 4f * s;
						wAttack = Mathf.Max(
							minW,
							wAttack * f
						);
						wRetal = showRetalChart
							? Mathf.Max(
								minW,
								wRetal * f
							)
							: 0f;
						unclampedTotal = wAttack + (showRetalChart
							? wRetal + gap
							: 0f) + borderPad * 2f;
					}
				}
			}
			var perBarA = wAttack > pad * 2f
				? (wAttack - pad * 2f) / Mathf.Max(nF, 1)
				: minWPerF;
			var perBarR = showRetalChart && wRetal > pad * 2f
				? (wRetal - pad * 2f) / Mathf.Max(nR, 1)
				: perBarA;
			var thinnest = perBarA;
			if (showRetalChart)
			{
				thinnest = Mathf.Min(
					perBarA,
					perBarR
				);
			}
			var gameFontSize = DamageHistogramState.CachedPreviewFontFromGame
				? DamageHistogramState.CachedPreviewTmpFontSize
				: 0;
			var fontBase = gameFontSize > 0
				? gameFontSize
				: Mathf.Clamp(
					Mathf.RoundToInt(16f * s),
					14,
					48
				);
			var tightFactor = thinnest < 9.5f * s
				? Mathf.InverseLerp(9.5f * s, 4.5f * s, thinnest)
				: 0f;
			if (tightFactor > 0.01f)
			{
				fontBase = Mathf.Max(
					7,
					Mathf.RoundToInt(fontBase * (1f - 0.28f * tightFactor)
					)
				);
			}
			var fontPx = Mathf.Clamp(
				Mathf.RoundToInt(fontBase),
				8,
				64
			);
			var subFont = Mathf.Clamp(
				fontPx - 1,
				7,
				60
			);
			if (_labelStyle == null)
			{
				_labelStyle = new GUIStyle(GUI.skin.label);
			}
			_labelStyle.font = DamageHistogramState.CachedPreviewGuiFont;
			_labelStyle.fontSize = fontPx;
			_labelStyle.normal.textColor = new Color(0.92f, 0.92f, 0.94f);
			_labelStyle.wordWrap = false;
			if (_killOnBarStyle == null)
			{
				_killOnBarStyle = new GUIStyle(_labelStyle);
			}
			_killOnBarStyle.font = _labelStyle.font;
			_killOnBarStyle.fontSize = Mathf.Clamp(
				Mathf.RoundToInt(
					(subFont + 2) * 1.05f
					* (tightFactor > 0.01f
						? 1f - 0.35f * tightFactor
						: 1f)
				),
				7,
				64
			);
			_killOnBarStyle.normal.textColor = new Color(0.98f, 0.97f, 0.94f);
			if (_chartCaptionStyle == null)
			{
				_chartCaptionStyle = new GUIStyle(GUI.skin.label);
			}
			_chartCaptionStyle.font = _labelStyle.font;
			_chartCaptionStyle.fontSize = Mathf.Clamp(Mathf.RoundToInt(18f * s), 14, 30);
			_chartCaptionStyle.alignment = TextAnchor.UpperLeft;
			_chartCaptionStyle.clipping = TextClipping.Overflow;
			_chartCaptionStyle.fontStyle = FontStyle.Bold;
			_chartCaptionStyle.normal.textColor = new Color(0.92f, 0.92f, 0.95f, 1f);
			if (!s_builtinAxisBinFontResolved)
			{
				s_builtinAxisBinFontResolved = true;
				try
				{
					s_builtinAxisBinFont = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
				}
				catch
				{
					s_builtinAxisBinFont = null;
				}
				if (s_builtinAxisBinFont == null)
				{
					try
					{
						s_builtinAxisBinFont = Resources.GetBuiltinResource<Font>("Arial.ttf");
					}
					catch
					{
						s_builtinAxisBinFont = null;
					}
				}
			}
			if (_binNumberStyle == null)
			{
				_binNumberStyle = new GUIStyle(_labelStyle);
			}
			_binNumberStyle.font = s_builtinAxisBinFont != null
				? s_builtinAxisBinFont
				: _labelStyle.font;
			_binNumberStyle.fontSize = Mathf.Clamp(
				Mathf.RoundToInt(
					22f * s
					* (tightFactor > 0.01f
						? 1f - 0.08f * tightFactor
						: 1f)
				),
				17, 36
			);
			_binNumberStyle.alignment = TextAnchor.UpperCenter;
			_binNumberStyle.clipping = TextClipping.Overflow;
			_binNumberStyle.fontStyle = FontStyle.Bold;
			_binNumberStyle.normal.textColor = Color.white;
			var fontMult = DamageHistogramSettings.FontScaleMultiplier();
			if (fontMult < 0.99f || fontMult > 1.01f)
			{
				_chartCaptionStyle.fontSize = Mathf.Clamp(
					Mathf.RoundToInt(_chartCaptionStyle.fontSize * fontMult), 8, 80);
				_binNumberStyle.fontSize = Mathf.Clamp(
					Mathf.RoundToInt(_binNumberStyle.fontSize * fontMult), 6, 60);
			}
			var labelPad = 4f;
			var capF = MeasureMaxBinLabelWidth(
				forward,
				_binNumberStyle
			) + labelPad;
			var capR = 0f;
			if (showRetalChart)
			{
				capR = MeasureMaxBinLabelWidth(
						retal,
						_binNumberStyle
					)
					+ labelPad;
			}
			minWPerF = Mathf.Max(
				minWPerF,
				minBarWFloor,
				capF
			);
			minWPerR = Mathf.Max(
				minWPerR,
				minBarWFloor,
				showRetalChart
					? capR
					: 0f
			);
			if (!showRetalChart)
			{
				minWPerR = 10f * s;
			}
			wAttack = Wfor(
				nF,
				minWPerF
			);
			wRetal = showRetalChart
				? Wfor(
					nR,
					minWPerR
				)
				: 0f;
			unclampedTotal = wAttack + (showRetalChart
				? wRetal + gap
				: 0f) + borderPad * 2f;
			if (unclampedTotal > maxTotal
			    && nF + nR > 0
			   )
			{
				for (var t2 = 0; t2 < 6
				    && unclampedTotal > maxTotal; t2++)
				{
					if (minWPerF > minBarWFloor + 0.01f)
					{
						minWPerF = Mathf.Max(
							minBarWFloor,
							minWPerF * 0.84f
						);
					}
					if (minWPerR > minBarWFloor + 0.01f)
					{
						minWPerR = Mathf.Max(
							minBarWFloor,
							minWPerR * 0.84f
						);
					}
					wAttack = Wfor(
						nF,
						minWPerF
					);
					wRetal = showRetalChart
						? Wfor(
							nR,
							minWPerR
						)
						: 0f;
					unclampedTotal = wAttack + (showRetalChart
						? wRetal + gap
						: 0f) + borderPad * 2f;
					if (unclampedTotal <= maxTotal)
					{
						break;
					}
				}
			}
			{
				var maxInnerW = maxTotal - borderPad * 2f;
				var gapW = showRetalChart
					? gap
					: 0f;
				var chartWsum = wAttack + (showRetalChart
					? wRetal
					: 0f);
				if (chartWsum + gapW > maxInnerW
				    && maxInnerW > gapW + 1f
				    && chartWsum > 0.1f
				   )
				{
					var f = (maxInnerW - gapW) / chartWsum;
					if (f < 0.999f
					    && f > 0.05f
					   )
					{
						var minW = pad * 2f + 4f * s;
						wAttack = Mathf.Max(
							minW,
							wAttack * f
						);
						wRetal = showRetalChart
							? Mathf.Max(
								minW,
								wRetal * f
							)
							: 0f;
						unclampedTotal = wAttack + (showRetalChart
							? wRetal + gap
							: 0f) + borderPad * 2f;
					}
				}
			}
			var passTotalH = blockH + borderPad * 2f;
			if (layoutPass == 0)
			{
				var kW = maxTotal / Mathf.Max(0.1f, unclampedTotal);
				var kH = maxTotalH / Mathf.Max(0.1f, passTotalH);
				layoutScaleK = Mathf.Clamp(
					Mathf.Min(1f, kW, kH),
					0.4f,
					1f
				);
			}
			if (Mathf.Approximately(1f, layoutScaleK)
			    || layoutPass == 1
			   )
			{
				break;
			}
		}
		s = s0 * layoutScaleK;
		gap = (float)DamageHistogramSettings.GapPx() * s;
		plotH = (float)DamageHistogramSettings.ChartHeightPx() * s;
		pad = 8f * s;
		borderPad = 12f * s;
		blockH = plotH + pad * 2f;
		var totalH = blockH + borderPad * 2f;
		var totalW = Mathf.Min(unclampedTotal, maxTotal);
		var axisRPre = 10f * s;
		if (DamageHistogramSettings.UsePanelCanvasUgui()
		    && forecastPanel != null
		    && forecastPanel.gameObject != null
		    && forecastPanel.gameObject.activeInHierarchy)
		{
			var layout = new HistogramLayoutParams(
				totalW, totalH, s,
				wAttack, wRetal, gap,
				borderPad, blockH, plotH, pad, axisRPre,
				_chartCaptionStyle.font != null ? _chartCaptionStyle.font : _labelStyle.font,
				_binNumberStyle.font != null ? _binNumberStyle.font : _labelStyle.font,
				_chartCaptionStyle.fontSize,
				_binNumberStyle.fontSize,
				ChartCaptionAttack,
				ChartCaptionRetal
			);
			s_uguiCachedLayout = layout;
			s_uguiCachePmfSeq = DamageHistogramState.PmfDataSequence;
			s_uguiCacheViewToken = DamageHistogramState.PmfViewToken;
			s_uguiCacheShowRetal = showRetalChart;
			s_uguiCacheScreenW = Screen.width;
			s_uguiCacheScreenH = Screen.height;
			s_uguiCacheLoadGen = LauncherConfigReader.LoadGeneration;
			s_uguiLayoutCacheValid = true;
			DamageHistogramPanelUgui.Present(forecastPanel, gameFrame, forward, retal, showRetalChart, in layout);
			return;
		}
		DamageHistogramPanelUgui.TearDown();
		GetClusterOriginNearMouse(
			Event.current.mousePosition,
			totalW,
			totalH,
			s,
			out var cx,
			out var cy
		);
		DrawPopupMenuFrame(new Rect(cx, cy, totalW, totalH), s, gameFrame);
		var innerX = cx + borderPad;
		var innerY = cy + borderPad;
		var axisR = 10f * s;
		DrawHistogramBlock(
			new Rect(innerX, innerY, wAttack, blockH),
			false,
			forward,
			_chartCaptionStyle,
			_binNumberStyle,
			s,
			plotH,
			pad,
			axisR);
		if (showRetalChart)
		{
			DrawHistogramBlock(
				new Rect(innerX + wAttack + gap, innerY, wRetal, blockH),
				true,
				retal,
				_chartCaptionStyle,
				_binNumberStyle,
				s,
				plotH,
				pad,
				axisR);
		}
	}

	private static void GetClusterOriginNearMouse(
		Vector2 mouseGui,
		float totalW,
		float totalH,
		float scale,
		out float clusterX,
		out float clusterY)
	{
		var o = 18f * scale;
		clusterX = mouseGui.x + o;
		clusterY = mouseGui.y + o;
		clusterX = Mathf.Clamp(clusterX, 16f, Mathf.Max(16f, (float)Screen.width - totalW - 16f));
		clusterY = Mathf.Clamp(clusterY, 16f, Mathf.Max(16f, (float)Screen.height - totalH - 16f));
	}

	private static void DrawPopupMenuFrame(Rect r, float scale, Sprite gameFrame)
	{
		// Underlay is IMGUI-only first; GL in this function (native frame) would sit above it, not under.
		var prevContent = GUI.contentColor;
		GUI.contentColor = new Color(1f, 1f, 1f, 1f);
		DrawRadialRoundedVignetteFill(
			r,
			scale,
			MainPanelVignetteCenterA,
			MainPanelVignetteEdgeA
		);
		GUI.contentColor = prevContent;
		var useNativeFrame = DamageHistogramSettings.UseNativeFrameSprite();
		var hadGameFrame = useNativeFrame
			&& DrawGameFrameIfPossible(
				r,
				gameFrame
			);
		if (hadGameFrame
		    && !s_logOnceVignetteWithGameFrame)
		{
			s_logOnceVignetteWithGameFrame = true;
			Plugin.LogSource?.LogInfo(
				"Damage histogram: GL forecast frame is drawn (damageHistogramUseNativeFrameSprite=true) on top of the blue radial. "
				+ "The sprite is mostly opaque, so the underlay is only obvious at transparent edges."
			);
		}
		if (!useNativeFrame
		    && !s_logOnceVignetteModOnly)
		{
			s_logOnceVignetteModOnly = true;
			Plugin.LogSource?.LogInfo(
				"Damage histogram: only mod background (no native frame sprite) — the forecast panel art is very opaque, "
				+ "so use damageHistogramUseNativeFrameSprite=true if you want that art drawn on top."
			);
		}
		// Soft cool edge feather — do not reintroduce a “graph” look; only a faint blue rim.
		var rings = Mathf.Clamp(Mathf.RoundToInt(20f * scale), 8, 36);
		var aCurve = 0.22f;
		for (var d = 1; d <= rings; d++)
		{
			var t = d / (float)rings;
			var a = aCurve * (1f - t) * (1f - t) * (1f - t) * (1f - 0.12f * t);
			if (a < 0.002f)
			{
				continue;
			}
			var outlineR = new Rect(
				r.x - d,
				r.y - d,
				r.width + 2f * d,
				r.height + 2f * d);
			var tintB = 0.08f + 0.06f * (1f - t) * (1f - t);
			var tintG = 0.07f + 0.055f * (1f - t) * (1f - t);
			var tintR = 0.05f + 0.04f * (1f - t) * (1f - t);
			DrawRectOutline(
				outlineR,
				new Color(tintR, tintG, tintB, a * 0.5f)
			);
		}
	}

	/// <summary>Smooth-ish radial: opaque center, clear edges, rounded clip. Uses a fixed 8x8 <see cref="DrawRectFilled"/> grid (64 quads max).</summary>
	/// <remarks>
	/// Rationale: (1) We previously issued GL before other IMGUI in the same <see cref="OnGUI"/>. In this URP+IL2CPP
	/// build that can fail to show (while GL from <see cref="DrawRoundedBarSolidGLLocal"/> after IMGUI still does).
	/// (2) Thousands of <c>GUI.DrawTexture</c> in one Repaint can also be dropped. A small, fixed count is the reliable
	/// middle path. (3) A single full-rect fallback remains if the rounded mask rejects all cells.
	/// </remarks>
	private static void DrawRadialRoundedVignetteFill(
		Rect r,
		float scale,
		float centerAlpha,
		float edgeAlpha
	)
	{
		if (r.width < 1f
		    || r.height < 1f)
		{
			return;
		}
		if (Event.current == null
		    || Event.current.type != EventType.Repaint)
		{
			return;
		}
		var w = r.width;
		var h = r.height;
		var tr = Mathf.Clamp(
			14f * scale,
			5f,
			Mathf.Max(4f, 0.4f * Mathf.Min(w, h) - 1f)
		);
		var cxi = w * 0.5f;
		var cyi = h * 0.5f;
		// 8x8: enough for a soft radial without macro tiles, few enough for IMGUI
		const int gW = 8;
		const int gH = 8;
		var bt = MainPanelVignetteFillRgb;
		var nDrawn = 0;
		if (!s_logOnceVignetteImguiMeta)
		{
			s_logOnceVignetteImguiMeta = true;
			Plugin.LogSource?.LogInfo(
				"Damage histogram underlay: IMGUI "
				+ gW
				+ "x"
				+ gH
				+ " (no leading GL; build "
				+ Plugin.PluginVersion
				+ " panelRect=("
				+ r.x.ToString("F0")
				+ ","
				+ r.y.ToString("F0")
				+ ","
				+ r.width.ToString("F0")
				+ ","
				+ r.height.ToString("F0")
				+ ") screen="
				+ Screen.width
				+ "x"
				+ Screen.height
			);
		}
		for (var j = 0; j < gH; j++)
		{
			for (var i = 0; i < gW; i++)
			{
				var tix = i / (float)gW;
				var tjx = (i + 1f) / gW;
				var tjy = j / (float)gH;
				var tjy1 = (j + 1f) / gH;
				var x0 = r.x + w * tix;
				var y0 = r.y + h * tjy;
				var cw = w * (tjx - tix) + 0.2f;
				var ch = h * (tjy1 - tjy) + 0.2f;
				var cxa = x0 + cw * 0.5f;
				var cya = y0 + ch * 0.5f;
				if (!InRoundedRectLocal(
					    cxa - r.x,
					    cya - r.y,
					    w,
					    h,
					    tr)
				   )
				{
					continue;
				}
				var dx = (cxa - (r.x + cxi)) / Mathf.Max(0.1f, cxi);
				var dy = (cya - (r.y + cyi)) / Mathf.Max(0.1f, cyi);
				var tRaw = Mathf.Clamp01(
					Mathf.Sqrt(0.5f * (dx * dx + dy * dy)) * 0.92f
					+ 0.1f
						* (Mathf.Abs(dx) * 0.5f
						   + Mathf.Abs(dy) * 0.5f)
				);
				var te = Mathf.Pow(
					tRaw,
					MainPanelVignetteFalloffPower
				);
				var a2 = Mathf.Lerp(
					centerAlpha,
					edgeAlpha,
					te
				);
				if (a2 < 0.0045f)
				{
					continue;
				}
				DrawRectFilled(
					new Rect(
						x0,
						y0,
						cw,
						ch
					),
					new Color(
						bt.r,
						bt.g,
						bt.b,
						a2
					)
				);
				nDrawn++;
			}
		}
		if (nDrawn < 1)
		{
			DrawRectFilled(
				r,
				new Color(
					bt.r,
					bt.g,
					bt.b,
					Mathf.Max(0.15f, centerAlpha * 0.6f)
				)
			);
		}
	}

	private static bool InRoundedRectLocal(
		float px,
		float py,
		float boxW,
		float boxH,
		float tr)
	{
		if (px < 0f
		    || py < 0f
		    || px > boxW
		    || py > boxH
		   )
		{
			return false;
		}
		if (tr < 0.25f)
		{
			return true;
		}
		tr = Mathf.Min(tr, Mathf.Max(0.5f, 0.5f * Mathf.Min(boxW, boxH) - 0.5f));
		// top-left
		if (px < tr
		    && py < tr
		   )
		{
			var dx = tr - px;
			var dy = tr - py;
			if (dx * dx + dy * dy > tr * tr + 0.01f)
			{
				return false;
			}
		}
		// top-right
		if (px > boxW - tr
		    && py < tr
		   )
		{
			var dx = (boxW - tr) - px;
			var dy = tr - py;
			if (dx * dx + dy * dy > tr * tr + 0.01f)
			{
				return false;
			}
		}
		// bottom-right
		if (px > boxW - tr
		    && py > boxH - tr
		   )
		{
			var dx = (boxW - tr) - px;
			var dy = (boxH - tr) - py;
			if (dx * dx + dy * dy > tr * tr + 0.01f)
			{
				return false;
			}
		}
		// bottom-left
		if (px < tr
		    && py > boxH - tr
		   )
		{
			var dx = tr - px;
			var dy = (boxH - tr) - py;
			if (dx * dx + dy * dy > tr * tr + 0.01f)
			{
				return false;
			}
		}
		return true;
	}

	// u, v: 0..1 (left..right, bottom..top) — same radial as the non-sprite vignette, without coarse sub-quad seams
	private static float GameFrameVignetteMultAtUv01(
		float u,
		float v
	)
	{
		var dx = (u - 0.5f) * 2f;
		var dy = (v - 0.5f) * 2f;
		var dd = Mathf.Sqrt(0.5f * (dx * dx + dy * dy));
		var tRaw = Mathf.Clamp01(
			dd * 0.9f
			+ 0.12f
				* (Mathf.Abs(dx) * 0.5f
				   + Mathf.Abs(dy) * 0.5f)
		);
		return Mathf.Lerp(
			0.5f,
			0.035f,
			Mathf.Pow(
				tRaw,
				MainPanelVignetteFalloffPower * 0.92f
			)
		);
	}

	/// <summary>Returns <c>true</c> if the game frame was drawn; otherwise caller should use the solid IMGUI look.</summary>
	private static bool DrawGameFrameIfPossible(Rect r, Sprite s)
	{
		if (s == null
		    || Event.current == null
		    || Event.current.type != EventType.Repaint)
		{
			return false;
		}

		var tex = s.texture;
		if (tex == null)
		{
			return false;
		}

		var tr = s.textureRect;
		var xn = (float)tex.width;
		var xx = (float)tex.height;
		if (xn < 1f
		    || xx < 1f
		    || tr.width < 1f
		    || tr.height < 1f)
		{
			return false;
		}

		// Do not use Graphics.DrawTexture in OnGUI — it has caused native crashes in IL2CPP. Draw one quad in GL
		// with a cached Unlit material and atlas UVs (Sprite.textureRect) instead.
		try
		{
			if (s_gameFrameUnlit == null)
			{
				var zj = Shader.Find("Unlit/Transparent");
				if (zj == null)
				{
					return false;
				}
				s_gameFrameUnlit = new Material(zj)
				{
					hideFlags = HideFlags.HideAndDontSave
				};
			}

			s_gameFrameUnlit.mainTexture = tex;
			var u0 = tr.x / xn;
			var u1 = (tr.x + tr.width) / xn;
			var v0 = tr.y / xx;
			var v1 = (tr.y + tr.height) / xx;
			var x0 = r.x;
			var x1 = r.x + r.width;
			var yBottom = Screen.height - (r.y + r.height);
			var yTop = Screen.height - r.y;

			GL.PushMatrix();
			GL.LoadPixelMatrix(0f, Screen.width, 0f, Screen.height);
			s_gameFrameUnlit.SetPass(0);
			var gc = GUI.color;
			const int nq = 8;
			GL.Begin(GL.QUADS);
			for (var ro = 0; ro < nq; ro++)
			{
				for (var qy = 0; qy < nq; qy++)
				{
					for (var k = 0; k < 4; k++)
					{
						var ii = k switch
						{
							0 => 0f,
							1 => 1f,
							2 => 1f,
							_ => 0f
						};
						var jjV = k switch
						{
							0 => 0f,
							1 => 0f,
							2 => 1f,
							_ => 1f
						};
						var gxu = (ro + ii) / nq;
						var gxv = (qy + jjV) / nq;
						var av = GameFrameVignetteMultAtUv01(
							gxu,
							gxv
						);
						var ya = Mathf.Lerp(
							u0,
							u1,
							(ro + ii) / nq
						);
						var zg = Mathf.Lerp(
							v0,
							v1,
							(qy + jjV) / nq
						);
						GL.TexCoord2(
							ya,
							zg
						);
						GL.Color(
							new Color(
								gc.r,
								gc.g,
								gc.b,
								gc.a * av
							)
						);
						GL.Vertex3(
							Mathf.Lerp(
								x0,
								x1,
								(ro + ii) / nq
							),
							Mathf.Lerp(
								yBottom,
								yTop,
								(qy + jjV) / nq
							),
							0f
						);
					}
				}
			}
			GL.End();
			GL.PopMatrix();
		}
		catch
		{
			return false;
		}

		// Plots still use the dark fill inside DrawHistogramBlock; no extra full-panel wash here.
		return true;
	}

	private static void GLEmitTriGui(
		float ax,
		float ay,
		float bx,
		float by,
		float cx,
		float cy,
		Color c,
		int zj
	)
	{
		GL.TexCoord2(0f, 0f);
		GL.Color(c);
		GL.Vertex3(
			ax,
			zj - ay,
			0f
		);
		GL.TexCoord2(0f, 0f);
		GL.Color(c);
		GL.Vertex3(
			bx,
			zj - by,
			0f
		);
		GL.TexCoord2(0f, 0f);
		GL.Color(c);
		GL.Vertex3(
			cx,
			zj - cy,
			0f
		);
	}

	private static void GLEmitRectGui(
		float x0,
		float y0,
		float w,
		float h,
		Color c,
		int zj
	)
	{
		if (w < 0.01f
		    || h < 0.01f)
		{
			return;
		}
		var x1 = x0 + w;
		var y1 = y0 + h;
		GLEmitTriGui(
			x0,
			y0,
			x1,
			y0,
			x0,
			y1,
			c,
			zj
		);
		GLEmitTriGui(
			x1,
			y0,
			x1,
			y1,
			x0,
			y1,
			c,
			zj
		);
	}

	/// <summary>GUI-space rounded rect, corner radius from <paramref name="k"/>; falls back to fill when too small.</summary>
	private static void DrawRoundedBarSolidGLLocal(
		Rect rGui,
		Color c,
		float k,
		Texture2D white
	)
	{
		if (rGui.width < 1f
		    || rGui.height < 1f
		    || white == null
		    || Event.current == null
		    || Event.current.type != EventType.Repaint)
		{
			return;
		}
		if (k < 0.25f)
		{
			DrawRectFilled(
				rGui,
				c
			);
			return;
		}
		var w = rGui.width;
		var h = rGui.height;
		var rPx = Mathf.Min(
			k,
			0.5f * w - 0.25f,
			0.5f * h - 0.25f
		);
		if (rPx < 0.5f)
		{
			DrawRectFilled(
				rGui,
				c
			);
			return;
		}
		var x0 = rGui.x;
		var y0 = rGui.y;
		var x1 = x0 + w;
		var y1 = y0 + h;
		const int segs = 6;
		var zj = (int)Screen.height;
		try
		{
			if (s_solidUnlit == null)
			{
				var sShader = Shader.Find("Unlit/Transparent");
				if (sShader == null)
				{
					DrawRectFilled(
						rGui,
						c
					);
					return;
				}
				s_solidUnlit = new Material(sShader)
				{
					hideFlags = HideFlags.HideAndDontSave
				};
			}
			s_solidUnlit.mainTexture = white;
			var gc = c;
			GL.PushMatrix();
			GL.LoadPixelMatrix(0f, Screen.width, 0f, Screen.height);
			s_solidUnlit.SetPass(0);
			GL.Begin(GL.TRIANGLES);
			var rp = rPx;
			// 5 center rectangles
			if (w > 2f * rp + 0.25f
			    && h > 2f * rp + 0.25f)
			{
				GLEmitRectGui(
					x0 + rp,
					y0 + rp,
					w - 2f * rp,
					h - 2f * rp,
					gc,
					zj
				);
			}
			if (w > 2f * rp + 0.25f)
			{
				GLEmitRectGui(
					x0 + rp,
					y0,
					w - 2f * rp,
					rp,
					gc,
					zj
				);
				GLEmitRectGui(
					x0 + rp,
					y1 - rp,
					w - 2f * rp,
					rp,
					gc,
					zj
				);
			}
			if (h > 2f * rp + 0.25f)
			{
				GLEmitRectGui(
					x0,
					y0 + rp,
					rp,
					h - 2f * rp,
					gc,
					zj
				);
				GLEmitRectGui(
					x1 - rp,
					y0 + rp,
					rp,
					h - 2f * rp,
					gc,
					zj
				);
			}
			// Corner fans (quarter-circles)
			var cTlX = x0 + rp;
			var cTlY = y0 + rp;
			for (var t = 0; t < segs; t++)
			{
				var a0 = (0.5f * Mathf.PI) * (t / (float)segs);
				var a1 = (0.5f * Mathf.PI) * ((t + 1) / (float)segs);
				var p0x = cTlX - rp * Mathf.Cos(a0);
				var p0y = cTlY - rp * Mathf.Sin(a0);
				var p1x = cTlX - rp * Mathf.Cos(a1);
				var p1y = cTlY - rp * Mathf.Sin(a1);
				GLEmitTriGui(
					cTlX,
					cTlY,
					p0x,
					p0y,
					p1x,
					p1y,
					gc,
					zj
				);
			}
			var cTrX = x1 - rp;
			var cTrY = y0 + rp;
			for (var t2 = 0; t2 < segs; t2++)
			{
				var a0 = (0.5f * Mathf.PI) * (t2 / (float)segs);
				var a1 = (0.5f * Mathf.PI) * ((t2 + 1) / (float)segs);
				var q0x = cTrX + rp * Mathf.Sin(a0);
				var q0y = cTrY - rp * Mathf.Cos(a0);
				var q1x = cTrX + rp * Mathf.Sin(a1);
				var q1y = cTrY - rp * Mathf.Cos(a1);
				GLEmitTriGui(
					cTrX,
					cTrY,
					q0x,
					q0y,
					q1x,
					q1y,
					gc,
					zj
				);
			}
			var cBrX = x1 - rp;
			var cBrY = y1 - rp;
			for (var t3 = 0; t3 < segs; t3++)
			{
				var a0 = (0.5f * Mathf.PI) * (t3 / (float)segs);
				var a1 = (0.5f * Mathf.PI) * ((t3 + 1) / (float)segs);
				var s0x = cBrX + rp * Mathf.Cos(a0);
				var s0y = cBrY + rp * Mathf.Sin(a0);
				var s1x = cBrX + rp * Mathf.Cos(a1);
				var s1y = cBrY + rp * Mathf.Sin(a1);
				GLEmitTriGui(
					cBrX,
					cBrY,
					s0x,
					s0y,
					s1x,
					s1y,
					gc,
					zj
				);
			}
			var cBlX = x0 + rp;
			var cBlY = y1 - rp;
			for (var t4 = 0; t4 < segs; t4++)
			{
				var a0 = (0.5f * Mathf.PI) * (t4 / (float)segs);
				var a1 = (0.5f * Mathf.PI) * ((t4 + 1) / (float)segs);
				var u0x = cBlX - rp * Mathf.Cos(a0);
				var u0y = cBlY + rp * Mathf.Sin(a0);
				var u1x = cBlX - rp * Mathf.Cos(a1);
				var u1y = cBlY + rp * Mathf.Sin(a1);
				GLEmitTriGui(
					cBlX,
					cBlY,
					u0x,
					u0y,
					u1x,
					u1y,
					gc,
					zj
				);
			}
			GL.End();
			GL.PopMatrix();
		}
		catch
		{
			DrawRectFilled(
				rGui,
				c
			);
		}
	}

	private static void DrawHistogramBlock(
		Rect chartArea,
		bool retaliation,
		DamageDistribution.HistogramSnapshot snap,
		GUIStyle chartCaptionStyle,
		GUIStyle binNumberStyle,
		float scale,
		float plotH,
		float pad,
		float axisRightPad
	)
	{
		if (snap.IsEmpty)
		{
			return;
		}
		var probabilities = snap.Probabilities;
		if (probabilities == null
		    || probabilities.Length == 0)
		{
			return;
		}
		var pmax = 0f;
		for (var i = 0; i < probabilities.Length; i++)
		{
			pmax = Mathf.Max(
				pmax,
				probabilities[i]
			);
		}
		if (pmax <= 0f)
		{
			return;
		}
		var psum = 0f;
		for (var j = 0; j < probabilities.Length; j++)
		{
			psum += probabilities[j];
		}
		if (psum <= 1E-15f)
		{
			return;
		}
		var contentW = chartArea.width - pad * 2f - axisRightPad;
		if (contentW < 2f)
		{
			return;
		}
		var captionText = retaliation
			? ChartCaptionRetal
			: ChartCaptionAttack;
		var capH = 2.5f * scale + Mathf.Max(12f, chartCaptionStyle.fontSize * 1.25f);
		var inner = new Rect(
			chartArea.x + pad,
			chartArea.y + pad,
			contentW,
			plotH
		);
		var r = new Rect(
			chartArea.x,
			chartArea.y,
			chartArea.width,
			plotH + pad * 2f
		);
		// No second vignette fill — use the same wash as the outer frame only. Hairline to separate the plot.
		DrawRectOutline(
			r,
			new Color(1f, 1f, 1f, 0.1f)
		);
		var captionRect = new Rect(inner.x, inner.y, contentW, capH);
		var oldCaptionColor = chartCaptionStyle.normal.textColor;
		chartCaptionStyle.normal.textColor = new Color(0f, 0f, 0f, 0.85f);
		GUI.Label(
			new Rect(captionRect.x + 1f, captionRect.y + 1f, captionRect.width, captionRect.height),
			captionText,
			chartCaptionStyle
		);
		chartCaptionStyle.normal.textColor = oldCaptionColor;
		GUI.Label(captionRect, captionText, chartCaptionStyle);
		var dataTop = inner.y + capH;
		var dataInner = new Rect(
			inner.x,
			dataTop,
			contentW,
			Mathf.Max(1f, inner.yMax - dataTop)
		);
		var numberRowH = Mathf.Max(6f, 3f + binNumberStyle.fontSize * 1.1f);
		var labelToBar = Mathf.Max(2.5f, 3.5f * scale);
		var bottomLineH = Mathf.Max(2f, 2.2f * scale);
		var barBottomY = dataInner.yMax - bottomLineH;
		// Tallest bar + label/label gap must fit in [dataInner.y, barBottomY)
		var barHAvail = Mathf.Max(1f, (barBottomY - dataInner.y) - numberRowH - labelToBar);
		var gridColor = new Color(1f, 1f, 1f, 0.07f);
		for (var g = 1; g <= 2; g++)
		{
			var gy = barBottomY - barHAvail * g / 3f;
			DrawRectFilled(new Rect(dataInner.x, gy, dataInner.width, 1f), gridColor);
		}
		var barGapH = Mathf.Max(2.5f, 4.5f * scale);
		var numStyle = new GUIStyle(binNumberStyle)
		{
			alignment = TextAnchor.UpperCenter,
			clipping = TextClipping.Overflow,
			fontStyle = FontStyle.Bold
		};
		numStyle.normal.textColor = Color.white;
		var n2 = probabilities.Length;
		var nCol = Mathf.Max(1, n2, DamageHistogramSettings.MinBars());
		var slotW = (dataInner.width - (nCol - 1) * barGapH) / nCol;
		var barW = Mathf.Max(1f, slotW);
		var barK = Mathf.Max(0.6f, 2.4f * scale);
		var barColor = new Color(0.95f, 0.95f, 0.97f, 0.97f);
		var luckColor = new Color(0.94f, 0.82f, 0.36f, 0.95f);
		var luckS = snap.LuckSharePerBin;
		var wtex = Texture2D.whiteTexture;
		var expIdx = 0f;
		for (var e = 0; e < n2; e++)
			expIdx += probabilities[e] / psum * e;
		var exX = dataInner.x + expIdx * (slotW + barGapH) + barW * 0.5f;
		exX = Mathf.Clamp(exX, dataInner.x, dataInner.x + dataInner.width - 2f);
		Rect barRect;
		for (var k2 = 0; k2 < n2; k2++)
		{
			if (probabilities[k2] <= 1E-8f)
			{
				continue;
			}
			var xSlot = dataInner.x + k2 * (slotW + barGapH);
			var barH = probabilities[k2] / pmax * barHAvail;
			var fL = 0f;
			if (luckS != null
			    && k2 < luckS.Length)
			{
				fL = Mathf.Clamp01(luckS[k2]);
			}
			var yTop = barBottomY - barH;
			var kUse = Mathf.Min(
				barK,
				0.4f * barW,
				0.4f * barH
			);
			barRect = new Rect(
				xSlot,
				yTop,
				barW,
				barH);
			var fill = luckS == null
				? barColor
				: Color.Lerp(
					barColor,
					luckColor,
					fL);
			DrawRoundedBarSolidGLLocal(
				barRect,
				fill,
				kUse,
				wtex);
			var label = (snap.MinOutcome + k2).ToString();
			var labelY = barRect.y
				- numberRowH
				- labelToBar;
			if (labelY < dataInner.y)
			{
				labelY = dataInner.y;
			}
			var labelRect = new Rect(
				xSlot,
				labelY,
				barW,
				numberRowH
			);
			var oldText = numStyle.normal.textColor;
			numStyle.normal.textColor = new Color(0f, 0f, 0f, 0.9f);
			GUI.Label(
				new Rect(labelRect.x + 1f, labelRect.y + 1f, labelRect.width, labelRect.height),
				label,
				numStyle
			);
			numStyle.normal.textColor = oldText;
			GUI.Label(labelRect, label, numStyle);
		}
		DrawRectFilled(
			new Rect(
				dataInner.x,
				dataInner.yMax - bottomLineH,
				dataInner.width,
				bottomLineH
			),
			new Color(1f, 1f, 1f, 0.28f)
		);
		DrawRectFilled(
			new Rect(exX - 1f, barBottomY - 5f, 2f, 5f + bottomLineH),
			luckColor
		);
	}

	// ── Tuner overlay (F9) ──────────────────────────────────────────────────────────────────

	private static bool s_tunerOpen;
	private static Rect s_tunerRect = new Rect(20f, 80f, 340f, 270f);
	private static bool s_tunerDragging;
	private static Vector2 s_tunerDragOffset;
	private static int s_tunerChartW, s_tunerChartH, s_tunerGapPx;
	private static int s_tunerFontPct, s_tunerMinBars, s_tunerLayoutPct, s_tunerFeatherPx;
	private static string s_tunerSaveMsg;
	private static float s_tunerSaveMsgExpiry;
	private static GUIStyle s_tunerTitleStyle;
	private static GUIStyle s_tunerRowStyle;

	private static void LoadTunerFromConfig()
	{
		s_tunerChartW = DamageHistogramSettings.ChartWidthPx();
		s_tunerChartH = DamageHistogramSettings.ChartHeightPx();
		s_tunerGapPx = DamageHistogramSettings.GapPx();
		s_tunerFontPct = Mathf.RoundToInt(DamageHistogramSettings.FontScaleMultiplier() * 100f);
		s_tunerMinBars = DamageHistogramSettings.MinBars();
		s_tunerLayoutPct = Mathf.RoundToInt(DamageHistogramSettings.PanelUguiLayoutMultiplier() * 100f);
		s_tunerFeatherPx = DamageHistogramSettings.PanelUguiEdgeFeatherPixels();
	}

	private static void OnTunerChanged()
	{
		DamageHistogramSettings.ApplyTunerOverride(
			s_tunerChartW, s_tunerChartH, s_tunerGapPx,
			s_tunerLayoutPct, s_tunerFeatherPx,
			s_tunerFontPct, s_tunerMinBars);
		InvalidateUguiLayoutCache();
		DamageHistogramPanelUgui.TearDown();
	}

	private static void DrawTuner()
	{
		var r = s_tunerRect;
		const float pad = 10f;
		const float rowH = 28f;
		const float labelW = 136f;
		const float valW = 46f;
		var sw = r.width - labelW - valW - pad * 3f;

		if (s_tunerTitleStyle == null)
		{
			s_tunerTitleStyle = new GUIStyle(GUI.skin.label);
			s_tunerTitleStyle.fontSize = 13;
			s_tunerTitleStyle.fontStyle = FontStyle.Bold;
			s_tunerTitleStyle.normal.textColor = new Color(0.92f, 0.92f, 0.96f, 1f);
		}
		if (s_tunerRowStyle == null)
		{
			s_tunerRowStyle = new GUIStyle(GUI.skin.label);
			s_tunerRowStyle.fontSize = 12;
			s_tunerRowStyle.normal.textColor = new Color(0.76f, 0.76f, 0.82f, 1f);
		}

		var oldC = GUI.color;
		GUI.color = new Color(0.07f, 0.07f, 0.10f, 0.97f);
		GUI.DrawTexture(r, Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.color = new Color(0.45f, 0.45f, 0.58f, 0.8f);
		GUI.DrawTexture(new Rect(r.x, r.y, r.width, 1f), Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.DrawTexture(new Rect(r.x, r.yMax - 1f, r.width, 1f), Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.DrawTexture(new Rect(r.x, r.y, 1f, r.height), Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.DrawTexture(new Rect(r.xMax - 1f, r.y, 1f, r.height), Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.color = oldC;

		GUI.Label(new Rect(r.x + pad, r.y + 5f, r.width - 44f, 22f), "Histogram Tuner  (F9)", s_tunerTitleStyle);
		if (GUI.Button(new Rect(r.xMax - 30f, r.y + 4f, 26f, 20f), "X"))
			s_tunerOpen = false;

		var y = r.y + 31f;
		oldC = GUI.color;
		GUI.color = new Color(0.35f, 0.35f, 0.48f, 0.6f);
		GUI.DrawTexture(new Rect(r.x + pad, y - 2f, r.width - pad * 2f, 1f), Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.color = oldC;

		void Row(string label, ref int val, int lo, int hi, string unit)
		{
			GUI.Label(new Rect(r.x + pad, y, labelW, 20f), label, s_tunerRowStyle);
			var nv = Mathf.RoundToInt(GUI.HorizontalSlider(
				new Rect(r.x + pad + labelW, y + 4f, sw, 14f), val, lo, hi));
			GUI.Label(new Rect(r.x + pad + labelW + sw + 4f, y, valW, 20f), nv + unit, s_tunerRowStyle);
			if (nv != val) { val = nv; OnTunerChanged(); }
			y += rowH;
		}

		Row("Chart Width",    ref s_tunerChartW,    80,  600, "px");
		Row("Chart Height",   ref s_tunerChartH,    32,  400, "px");
		Row("Gap",            ref s_tunerGapPx,      0,   80, "px");
		Row("Font Scale",     ref s_tunerFontPct,   50,  300, "%");
		Row("Min Axis Bars",  ref s_tunerMinBars,    0,   30, "");
		Row("Layout Scale",   ref s_tunerLayoutPct, 80,  200, "%");
		Row("Edge Feather",   ref s_tunerFeatherPx,  8,  120, "px");

		y += 2f;
		oldC = GUI.color;
		GUI.color = new Color(0.35f, 0.35f, 0.48f, 0.6f);
		GUI.DrawTexture(new Rect(r.x + pad, y - 2f, r.width - pad * 2f, 1f), Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.color = oldC;
		y += 4f;

		if (GUI.Button(new Rect(r.x + pad, y, 108f, 24f), "Save Config"))
			SaveTunerConfig();

		if (!string.IsNullOrEmpty(s_tunerSaveMsg) && Time.realtimeSinceStartup < s_tunerSaveMsgExpiry)
		{
			oldC = GUI.color;
			GUI.color = new Color(0.4f, 1f, 0.4f, 1f);
			GUI.Label(new Rect(r.x + pad + 116f, y + 4f, 150f, 20f), s_tunerSaveMsg, s_tunerRowStyle);
			GUI.color = oldC;
		}

		var ev = Event.current;
		var titleHit = new Rect(r.x, r.y, r.width - 33f, 28f);
		if (ev.type == EventType.MouseDown && titleHit.Contains(ev.mousePosition))
		{
			s_tunerDragging = true;
			s_tunerDragOffset = ev.mousePosition - new Vector2(r.x, r.y);
			ev.Use();
		}
		else if (ev.type == EventType.MouseDrag && s_tunerDragging)
		{
			var np = ev.mousePosition - s_tunerDragOffset;
			s_tunerRect = new Rect(np.x, np.y, s_tunerRect.width, s_tunerRect.height);
			ev.Use();
		}
		else if (ev.type == EventType.MouseUp)
		{
			s_tunerDragging = false;
		}
	}

	private static void SaveTunerConfig()
	{
		try
		{
			var path = LauncherConfigReader.GetCanonicalModSettingsPath();
			LauncherConfigReader.TryLoad();
			var json = "{\n"
				+ "  \"damageHistogramChartWidthPx\": " + s_tunerChartW + ",\n"
				+ "  \"damageHistogramChartHeightPx\": " + s_tunerChartH + ",\n"
				+ "  \"damageHistogramGapPx\": " + s_tunerGapPx + ",\n"
				+ "  \"damageHistogramFontScalePercent\": " + s_tunerFontPct + ",\n"
				+ "  \"damageHistogramMinBars\": " + s_tunerMinBars + ",\n"
				+ "  \"damageHistogramPanelUguiLayoutPercent\": " + s_tunerLayoutPct + ",\n"
				+ "  \"damageHistogramPanelUguiEdgeFeatherPx\": " + s_tunerFeatherPx + "\n"
				+ "}";
			var activePath = LauncherConfigReader.LastResolvedModSettingsPath;
			var existingJson = activePath == null ? null : System.IO.File.ReadAllText(activePath);
			if (!ManagedModSettingsJson.TryMergeObjects(existingJson, json, out var mergedJson, out var mergeDiagnostic))
				throw new System.IO.InvalidDataException("Tuner settings merge refused: " + mergeDiagnostic);

			var dlv = System.IO.Path.GetDirectoryName(path);
			if (!string.IsNullOrEmpty(dlv))
				System.IO.Directory.CreateDirectory(dlv);
			System.IO.File.WriteAllText(path, mergedJson);
			LauncherConfigReader.InvalidateCache();
			DamageHistogramSettings.InvalidateCache();
			InvalidateUguiLayoutCache();
			DamageHistogramPanelUgui.TearDown();
			s_tunerSaveMsg = "Saved!";
			s_tunerSaveMsgExpiry = Time.realtimeSinceStartup + 3f;
		}
		catch (Exception ex)
		{
			s_tunerSaveMsg = "Save failed";
			s_tunerSaveMsgExpiry = Time.realtimeSinceStartup + 5f;
			Plugin.LogSource?.LogError("Tuner save: " + ex.Message);
		}
	}

	private static void DrawRectFilled(Rect r, Color c)
	{
		var prev = GUI.color;
		GUI.color = c;
		GUI.DrawTexture(r, Texture2D.whiteTexture, ScaleMode.StretchToFill);
		GUI.color = prev;
	}

	private static void DrawRectOutline(Rect r, Color c)
	{
		DrawRectFilled(new Rect(r.x, r.y, r.width, 1f), c);
		DrawRectFilled(new Rect(r.x, r.yMax - 1f, r.width, 1f), c);
		DrawRectFilled(new Rect(r.x, r.y, 1f, r.height), c);
		DrawRectFilled(new Rect(r.xMax - 1f, r.y, 1f, r.height), c);
	}
}

internal static class DamageHistogramForecastRecorder
{
	[ThreadStatic] private static int _bdwuNesting;
	private static MethodInfo s_retaliationForecastMethod;
	private static bool s_loggedForecastPatchSummary;

	// Input cache: skip rebuilding histograms when bdwu fires every frame for the same hover target.
	private static IntPtr s_lastCasterPtr;
	private static IntPtr s_lastTargetPtr;
	private static float s_lastDmgMult;
	private static int s_lastCgau;
	private static int s_lastCgav;
	private static bool s_haveLastRecord;
	private static bool s_loggedParamsSkip;
	private static bool s_loggedForecastSkip;
	private static bool s_loggedAtkStackSkip;
	private static bool s_loggedDefStackSkip;
	private static bool s_loggedRecord;
	private static bool s_loggedNullResultFallback;
	private static bool s_loggedNullResultFailure;
	private static bool s_loggedRetalSkip;
	private static bool s_loggedRetalTriggerSkip;
	private static bool s_loggedRetalTriggerUnresolved;
	private static bool s_loggedKillCap;

	internal static void InvalidateInputCache()
	{
		s_haveLastRecord = false;
	}

	internal static void TryRegisterForecastPatches(Harmony harmony)
	{
		if (harmony == null)
		{
			return;
		}

		var postfix = new HarmonyMethod(typeof(DamageHistogramForecastRecorder).GetMethod(
			nameof(AfterForecastCalculated),
			BindingFlags.Static | BindingFlags.NonPublic));
		var patched = 0;
		foreach (var method in ResolveForecastMethods())
		{
			try
			{
				harmony.Patch(method, postfix: postfix);
				patched++;
				s_retaliationForecastMethod ??= method;
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning("Damage histogram forecast patch failed for "
					+ method.DeclaringType?.FullName + "." + method.Name + ": " + ex.Message);
			}
		}
		if (!s_loggedForecastPatchSummary)
		{
			s_loggedForecastPatchSummary = true;
			Plugin.LogSource?.LogInfo("Damage histogram forecast calculator patches applied: " + patched);
		}
	}

	internal static void TryRegisterPanelPatches(Harmony harmony)
	{
		if (harmony == null)
		{
			return;
		}

		try
		{
			var show = ResolveForecastPanelShowMethod();
			if (show != null)
			{
				harmony.Patch(
					show,
					postfix: new HarmonyMethod(typeof(DamageHistogramForecastPanelShowPatch).GetMethod(
						nameof(DamageHistogramForecastPanelShowPatch.Postfix),
						BindingFlags.Static | BindingFlags.NonPublic)));
				var parameters = show.GetParameters();
				var argType = parameters.Length == 0 ? "none" : parameters[0].ParameterType.Name;
				Plugin.LogSource?.LogInfo("Damage histogram panel Show patch target: "
					+ show.DeclaringType?.FullName + "." + show.Name + "(" + argType + ")");
			}
			else
			{
				Plugin.LogSource?.LogWarning("Damage histogram panel Show patch target not found.");
			}

			var hide = typeof(BhHealDamageForecastPanel).GetMethod(
				nameof(BhHealDamageForecastPanel.Hide),
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
				null,
				Type.EmptyTypes,
				null);
			if (hide != null)
			{
				harmony.Patch(
					hide,
					postfix: new HarmonyMethod(typeof(DamageHistogramForecastPanelHidePatch).GetMethod(
						nameof(DamageHistogramForecastPanelHidePatch.Postfix),
						BindingFlags.Static | BindingFlags.NonPublic)));
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Damage histogram panel patch registration failed: " + ex.Message);
		}
	}

	private static MethodInfo[] ResolveForecastMethods()
	{
		var result = new System.Collections.Generic.List<MethodInfo>();
		var seen = new System.Collections.Generic.HashSet<string>();
		foreach (var typeName in GameSymbols.BattleForecast.CalculatorTypeHints)
		{
			var type = ResolveLoadedType(typeName);
			if (type == null)
			{
				continue;
			}
			AddForecastMethods(type, result, seen);
		}

		if (result.Count == 0)
		{
			foreach (var type in EnumerateLoadedTypes())
			{
				if (!type.IsAbstract || !type.IsSealed)
				{
					continue;
				}
				AddForecastMethods(type, result, seen);
			}
		}
		if (result.Count > 0)
		{
			var names = new System.Text.StringBuilder();
			for (var i = 0; i < result.Count; i++)
			{
				if (i > 0)
				{
					names.Append(", ");
				}
				names.Append(result[i].DeclaringType?.FullName).Append(".").Append(result[i].Name);
			}
			Plugin.LogSource?.LogInfo("Damage histogram forecast calculator targets: " + names);
		}
		return result.ToArray();
	}

	private static void AddForecastMethods(
		Type type,
		System.Collections.Generic.List<MethodInfo> result,
		System.Collections.Generic.HashSet<string> seen)
	{
		MethodInfo[] methods;
		try
		{
			methods = type.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
		}
		catch
		{
			return;
		}

		foreach (var method in methods)
		{
			if (!IsForecastCalculatorMethod(method))
			{
				continue;
			}
			var key = method.Module.ModuleVersionId.ToString("N") + ":" + method.MetadataToken;
			if (seen.Add(key))
			{
				result.Add(method);
			}
		}
	}

	private static bool IsForecastCalculatorMethod(MethodInfo method)
	{
		ParameterInfo[] parameters;
		try
		{
			parameters = method.GetParameters();
		}
		catch
		{
			return false;
		}
		return parameters.Length == 2
		    && parameters[0].ParameterType == typeof(DamageUiParams)
		    && parameters[1].ParameterType == typeof(bool)
		    && DamageDistribution.ForecastReader.CanResolveType(method.ReturnType);
	}

	private static Type ResolveLoadedType(string name)
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type type = null;
			try
			{
				type = assembly.GetType(name, throwOnError: false);
			}
			catch
			{
			}
			if (type != null)
			{
				return type;
			}
		}

		foreach (var type in EnumerateLoadedTypes())
		{
			if (type.Name == name || type.FullName == name)
			{
				return type;
			}
		}
		return null;
	}

	private static System.Collections.Generic.IEnumerable<Type> EnumerateLoadedTypes()
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try
			{
				types = assembly.GetTypes();
			}
			catch (ReflectionTypeLoadException ex)
			{
				types = ex.Types;
			}
			catch
			{
				continue;
			}

			foreach (var type in types)
			{
				if (type != null)
				{
					yield return type;
				}
			}
		}
	}

	private static MethodInfo ResolveForecastPanelShowMethod()
	{
		foreach (var method in typeof(BhHealDamageForecastPanel).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			var parameters = method.GetParameters();
			if (parameters.Length == 1
			    && method.ReturnType == typeof(void)
			    && DamageDistribution.ForecastReader.CanResolveType(parameters[0].ParameterType))
			{
				return method;
			}
		}
		return null;
	}

	private static void AfterForecastCalculated(DamageUiParams a, bool b, object __result, MethodBase __originalMethod)
	{
		if (!DamageHistogramSettings.ShouldApplyPatches())
		{
			return;
		}
		if (_bdwuNesting > 0)
		{
			return;
		}
		_ = b;
		if (__originalMethod is MethodInfo method)
		{
			s_retaliationForecastMethod ??= method;
		}
		var result = __result;
		if (result == null && __originalMethod is MethodInfo originalMethod)
		{
			result = TryRecomputeForecastForNullPostfixResult(originalMethod, a, b);
		}
		Record(a, result);
	}

	private static object TryRecomputeForecastForNullPostfixResult(MethodInfo method, DamageUiParams a, bool b)
	{
		if (method == null || a == null)
		{
			return null;
		}
		try
		{
			_bdwuNesting++;
			var result = method.Invoke(null, new object[] { a, b });
			if (result != null)
			{
				LogOnce(ref s_loggedNullResultFallback,
					"Damage histogram recorder: Harmony postfix result was null; reused guarded forecast invocation.");
			}
			else
			{
				LogOnce(ref s_loggedNullResultFailure,
					"Damage histogram recorder: guarded forecast invocation also returned null.");
			}
			return result;
		}
		catch (Exception ex)
		{
			LogOnce(ref s_loggedNullResultFailure,
				"Damage histogram recorder: guarded forecast invocation failed: " + ex.Message);
			return null;
		}
		finally
		{
			_bdwuNesting--;
		}
	}

	internal static void Record(DamageUiParams a, object __result)
	{
		if (_bdwuNesting > 0)
		{
			return;
		}
		try
		{
			if (__result == null)
			{
				return;
			}
			RecordCore(a, __result);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Damage histogram recording failed (hover preview skipped): " + ex);
		}
	}

	private static void RecordCore(DamageUiParams a, object __result)
	{
		// Do not require ESideCastType.Unit: many UIs call bdwu/oez for hero abilities, spells, etc.
		// (Shipped v0.1.0 was Unit-only; that matches “nothing on screen” in common cases.)
		if (!TryReadDamageUiParams(a, out var caster, out var castSource, out var target, out var dmgMult, out var sideCastType))
		{
			LogOnce(ref s_loggedParamsSkip, "Damage histogram record skipped: DamageUiParams members did not resolve.");
			return;
		}
		if (!DamageDistribution.ForecastReader.TryRead(__result, out var forecastValues))
		{
			LogOnce(ref s_loggedForecastSkip, "Damage histogram record skipped: forecast DTO members did not resolve on " + __result.GetType().FullName + ".");
			return;
		}
		if (
			__result == null
			|| forecastValues.DamageMin < 0
			|| dmgMult <= 0f
		)
		{
			return;
		}
		_ = TryGetIl2CppPointer(caster, out var cPtr);
		_ = TryGetIl2CppPointer(target, out var tPtr);
		var cgau = forecastValues.DamageMin;
		var cgav = forecastValues.DamageMax;
		if (s_haveLastRecord
		    && cPtr == s_lastCasterPtr
		    && tPtr == s_lastTargetPtr
		    && dmgMult == s_lastDmgMult
		    && cgau == s_lastCgau
		    && cgav == s_lastCgav)
		{
			return;
		}
		s_lastCasterPtr = cPtr;
		s_lastTargetPtr = tPtr;
		s_lastDmgMult = dmgMult;
		s_lastCgau = cgau;
		s_lastCgav = cgav;
		s_haveLastRecord = true;
		// For most skills, pass battle Units so kill mapping can mirror game rules (bcba/UnitData).
		// Blocklisted casts (e.g. Basic Summon Swarm) skip Units to avoid native AVs on some targets.
		var useUnitKillMap = !DamageHistogramCastBlocklist.IsForecastOnlyKillStackMapping(castSource);
		var uAtk = useUnitKillMap
			? TryGetBattleUnit(cPtr)
			: null;
		var uDef = useUnitKillMap
			? TryGetBattleUnit(tPtr)
			: null;
		var convolutionMaxUnits = DamageHistogramSettings.ConvolutionMaxUnits();
		var atkStacks = SafeStackCount(caster);
		if (atkStacks <= 0)
		{
			LogOnce(ref s_loggedAtkStackSkip, "Damage histogram record skipped: attacker stack count resolved to 0 for " + caster.GetType().FullName + ".");
			return;
		}
		var defStackHint = SafeStackCount(target);
		var forwardContext = useUnitKillMap
			? new DamageDistribution.DamageReceiverContext(target, uDef, forecastValues)
			: null;
		var defCapInfo = forwardContext != null
			? DamageDistribution.ResolveKillCap(forecastValues, forwardContext, defStackHint)
			: null;
		var defStacks = defCapInfo != null && defCapInfo.IsDefensible
			? defCapInfo.SelectedCap
			: defStackHint;
		if (defCapInfo != null)
		{
			LogOnce(ref s_loggedKillCap, "Damage histogram kill-cap: " + defCapInfo.ToDiagnosticString() + ".");
		}
		if (defStacks <= 0 && forecastValues.KillMax > 0)
		{
			LogOnce(ref s_loggedDefStackSkip, "Damage histogram record skipped: defender kill cap unresolved for " + target.GetType().FullName + ".");
			return;
		}
		var luck = LuckCritMixture.CopyLuckDistributionOrDefault();
		var noCrit = LuckCritMixture.TryGetDisableCrits();
		var atkStats = TryBajpDyt(caster);
		var defStats = TryBajpDyx(target);
		var snap = DamageDistribution.BuildKillHistogram(
			__result,
			atkStacks,
			defStacks,
			convolutionMaxUnits,
			atkStats,
			luck,
			noCrit,
			forwardContext);
		var retalHist = new DamageDistribution.HistogramSnapshot(Array.Empty<float>(), 0, 0);
		var hasRetal = false;
		if (ShouldComputeRetaliation(caster, target, castSource, sideCastType))
		{
			var rf = TryComputeRetaliationForecast(a);
			if (rf == null)
			{
				LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed forecast returned null.");
			}
			else if (!DamageDistribution.ForecastReader.TryRead(rf, out var retalValues))
			{
				LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed forecast DTO members did not resolve on " + rf.GetType().FullName + ".");
			}
			else if (retalValues.DamageMin < 0)
			{
				LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed forecast had negative min damage " + retalValues.DamageMin + ".");
			}
			else if (!RetalForecastHasDamage(rf))
			{
				LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed forecast damage range was " + retalValues.DamageMin + "-" + retalValues.DamageMax + ".");
			}
			else
			{
				var attackerContext = useUnitKillMap
					? new DamageDistribution.DamageReceiverContext(caster, uAtk, retalValues)
					: null;
				if (attackerContext != null)
				{
					_ = DamageDistribution.ResolveKillCap(retalValues, attackerContext, atkStacks);
				}
				retalHist = DamageDistribution.BuildMarginalizedRetaliationKillHistogram(
					__result,
					rf,
					defStacks,
					atkStacks,
					convolutionMaxUnits,
					atkStats,
					defStats,
					luck,
					noCrit,
					forwardContext,
					attackerContext);
				hasRetal = !retalHist.IsEmpty;
			}
		}
		else
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: sideCastType=" + sideCastType
				+ ", casterType=" + (caster?.GetType().FullName ?? "?")
				+ ", targetType=" + (target?.GetType().FullName ?? "?") + ".");
		}
		DamageHistogramState.SetForward(snap, retalHist, hasRetal);
		LogOnce(ref s_loggedRecord, "Damage histogram recorded: dmg=" + cgau + "-" + cgav
			+ ", dtoKills=" + forecastValues.KillMin + "-" + forecastValues.KillMax
			+ ", atkStacks=" + atkStacks
			+ ", defStacks=" + defStacks
			+ (defCapInfo != null ? ", capSource=" + defCapInfo.SelectedCapSource : "")
			+ ", bins=" + snap.Probabilities.Length
			+ ", killRange=" + snap.MinOutcome + "-" + snap.MaxOutcome
			+ ", retal=" + hasRetal
			+ (hasRetal ? ", retalKillRange=" + retalHist.MinOutcome + "-" + retalHist.MaxOutcome : "")
			+ ".");
	}

	private static void LogOnce(ref bool flag, string message)
	{
		if (flag)
		{
			return;
		}
		flag = true;
		Plugin.LogSource?.LogInfo(message);
	}

	private static bool TryReadDamageUiParams(
		DamageUiParams p,
		out object caster,
		out object castSource,
		out object target,
		out float dmgMult,
		out ESideCastType sideCastType)
	{
		caster = null;
		castSource = null;
		target = null;
		dmgMult = 0f;
		sideCastType = default;
		if (p == null)
		{
			return false;
		}
		caster = ReadMember(p, GameSymbols.DamageForecast.ParamsCaster);
		castSource = ReadMember(p, GameSymbols.DamageForecast.ParamsCastSource);
		target = ReadMember(p, GameSymbols.DamageForecast.ParamsTarget);
		var dmg = ReadMember(p, GameSymbols.DamageForecast.ParamsDmgMult);
		var side = ReadMember(p, GameSymbols.DamageForecast.ParamsSideCastType);
		if (caster == null || target == null || dmg == null || side == null)
		{
			return false;
		}
		try
		{
			dmgMult = Convert.ToSingle(dmg);
			sideCastType = side is ESideCastType typedSide
				? typedSide
				: (ESideCastType)Convert.ToInt32(side);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static object ReadMember(object source, string name)
	{
		if (source == null || string.IsNullOrEmpty(name))
		{
			return null;
		}
		try
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var type = source.GetType();
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				return property.GetValue(source, null);
			}
			var field = type.GetField(name, flags);
			return field?.GetValue(source);
		}
		catch
		{
			return null;
		}
	}

	private static int SafeStackCount(object obj)
	{
		if (obj == null)
		{
			return 0;
		}
		try
		{
			foreach (var name in GameSymbols.DamageKill.StackCountGetter.NameHints)
			{
				var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
				if (method == null)
				{
					continue;
				}
				var value = method.Invoke(obj, Array.Empty<object>());
				if (value != null)
				{
					return Convert.ToInt32(value);
				}
			}
		}
		catch
		{
		}
		if (DamageKillMapping.TryGetAliveCreatureCount(obj, out var stacks)
		    && stacks > 0)
		{
			return stacks;
		}
		return 0;
	}

	private static object ReadUnitDataMember(object obj)
	{
		foreach (var name in GameSymbols.DamageKill.UnitDataFields)
		{
			var value = ReadMember(obj, name);
			if (value != null)
			{
				return value;
			}
		}
		foreach (var name in GameSymbols.DamageKill.UnitDataGetter.NameHints)
		{
			try
			{
				var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
				if (method == null)
				{
					continue;
				}
				var value = method.Invoke(obj, Array.Empty<object>());
				if (value != null)
				{
					return value;
				}
			}
			catch
			{
			}
		}
		return null;
	}

	private static UnitStat TryBajpDyt(object c)
	{
		return TryResolveCombatStats(c);
	}

	private static UnitStat TryBajpDyx(object t)
	{
		return TryResolveCombatStats(t);
	}

	private static UnitStat TryResolveCombatStats(object obj)
	{
		if (obj == null)
			return null;

		if (DamageKillMapping.TryGetCombatStats(obj, out var stats))
		{
			return stats;
		}

		try
		{
			foreach (var name in GameSymbols.DamageKill.UnitStatsGetter.NameHints)
			{
				var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
				var stat = method?.Invoke(obj, Array.Empty<object>()) as UnitStat;
				if (stat != null)
				{
					return stat;
				}
			}
		}
		catch
		{
		}
		return null;
	}

	private static bool TryGetIl2CppPointer(object value, out IntPtr ptr)
	{
		ptr = IntPtr.Zero;
		try
		{
			if (value is Il2CppObjectBase obj)
			{
				ptr = obj.Pointer;
				return ptr != IntPtr.Zero;
			}
		}
		catch
		{
		}
		return false;
	}

	private static bool ShouldComputeRetaliation(object caster, object target, object castSource, ESideCastType sideCastType)
	{
		if (sideCastType == ESideCastType.Magic
		    || sideCastType == ESideCastType.HeroAbility
		    || sideCastType == ESideCastType.Trap)
		{
			return false;
		}
		if (!DamageHistogramCastSourceInfo.TryReadPrimaryTriggerCounter(castSource, out var triggerCounter, out var triggerSource))
		{
			LogOnce(ref s_loggedRetalTriggerUnresolved, "Damage histogram retaliation skipped: primary cast-source triggerCounter did not resolve for "
				+ (castSource?.GetType().FullName ?? "?") + ".");
			return false;
		}
		if (!triggerCounter)
		{
			LogOnce(ref s_loggedRetalTriggerSkip, "Damage histogram retaliation skipped: primary cast-source triggerCounter=false via "
				+ (triggerSource ?? "?") + ".");
			return false;
		}
		var o = TryGetIl2CppPointer(caster, out var casterPtr)
			? TryGetBattleUnit(casterPtr)
			: null;
		var t = TryGetIl2CppPointer(target, out var targetPtr)
			? TryGetBattleUnit(targetPtr)
			: null;
		return o != null && t != null;
	}

	private static bool RetalForecastHasDamage(object retal)
	{
		if (retal == null)
		{
			return false;
		}
		try
		{
			return DamageDistribution.ForecastReader.TryRead(retal, out var values)
			       && (values.DamageMax > 0 || values.DamageMin > 0);
		}
		catch
		{
			return false;
		}
	}

	private static Unit TryGetBattleUnit(IntPtr ptr)
	{
		if (ptr == IntPtr.Zero)
		{
			return null;
		}
		try
		{
			return new Unit(ptr);
		}
		catch
		{
			return null;
		}
	}

	private static object TryComputeRetaliationForecast(DamageUiParams forwardParams)
	{
		if (forwardParams == null || s_retaliationForecastMethod == null)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: missing forward params or forecast method.");
			return null;
		}
		if (!TryReadDamageUiParams(
			    forwardParams,
			    out var caster,
			    out _,
			    out var target,
			    out var dmgMult,
			    out _))
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: forward params did not reread.");
			return null;
		}

		if (!TryGetIl2CppPointer(target, out var retalCasterPtr)
		    || retalCasterPtr == IntPtr.Zero
		    || !TryGetIl2CppPointer(caster, out var retalTargetPtr)
		    || retalTargetPtr == IntPtr.Zero)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed unit pointers did not resolve.");
			return null;
		}
		var retalCaster = TryGetBattleUnit(retalCasterPtr);
		var retalTarget = TryGetBattleUnit(retalTargetPtr);
		if (retalCaster == null || retalTarget == null)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: concrete Unit rewrap failed.");
			return null;
		}

		var retalSource = TryInvokeNoArg(retalCaster, GameSymbols.DamageRetaliation.CasterSourceGetter.NameHints);
		if (retalSource == null)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: defender cast source getter returned null.");
			return null;
		}

		var retalParams = TryCreateDamageUiParams(
			retalCaster,
			retalSource,
			retalTarget,
			dmgMult,
			ESideCastType.Unit,
			0);
		if (retalParams == null)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed DamageUiParams construction failed.");
			return null;
		}
		try
		{
			_bdwuNesting++;
			return s_retaliationForecastMethod.Invoke(null, new object[] { retalParams, true });
		}
		catch (Exception ex)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed forecast invocation failed: " + ex.Message);
			return null;
		}
		finally
		{
			_bdwuNesting--;
		}
	}

	private static object TryCreateDamageUiParams(
		object caster,
		object castSource,
		object target,
		float dmgMult,
		ESideCastType sideCastType,
		int pathLength)
	{
		try
		{
			var boxed = new DamageUiParams();
			if (!TryWriteMember(boxed, GameSymbols.DamageForecast.ParamsCaster, caster)
			    || !TryWriteMember(boxed, GameSymbols.DamageForecast.ParamsCastSource, castSource)
			    || !TryWriteMember(boxed, GameSymbols.DamageForecast.ParamsTarget, target)
			    || !TryWriteMember(boxed, GameSymbols.DamageForecast.ParamsDmgMult, dmgMult)
			    || !TryWriteMember(boxed, GameSymbols.DamageForecast.ParamsSideCastType, sideCastType)
			    || !TryWriteMember(boxed, GameSymbols.DamageForecast.ParamsPathLength, pathLength))
			{
				LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed DamageUiParams member map failed "
					+ "caster=" + (caster?.GetType().FullName ?? "?")
					+ ", source=" + (castSource?.GetType().FullName ?? "?")
					+ ", target=" + (target?.GetType().FullName ?? "?") + ".");
				return null;
			}
			return boxed;
		}
		catch (Exception ex)
		{
			LogOnce(ref s_loggedRetalSkip, "Damage histogram retaliation skipped: reversed DamageUiParams construction failed: " + ex.Message);
		}
		return null;
	}

	private static bool TryWriteMember(object target, string name, object value)
	{
		if (target == null || string.IsNullOrEmpty(name))
		{
			return false;
		}
		try
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var type = target.GetType();
			var property = type.GetProperty(name, flags);
			if (property != null && property.CanWrite && property.GetIndexParameters().Length == 0)
			{
				if (!TryCoerceMemberValue(value, property.PropertyType, out var coerced))
				{
					return false;
				}
				property.SetValue(target, coerced, null);
				return true;
			}
			var field = type.GetField(name, flags);
			if (field != null)
			{
				if (!TryCoerceMemberValue(value, field.FieldType, out var coerced))
				{
					return false;
				}
				field.SetValue(target, coerced);
				return true;
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogDebug("Damage histogram DamageUiParams member write failed: " + name + ": " + ex.Message);
		}
		return false;
	}

	private static bool TryCoerceMemberValue(object value, Type targetType, out object coerced)
	{
		coerced = value;
		if (targetType == null)
		{
			return false;
		}
		if (value == null)
		{
			return !targetType.IsValueType;
		}
		if (targetType.IsInstanceOfType(value))
		{
			return true;
		}
		try
		{
			if (targetType.IsEnum)
			{
				coerced = Enum.ToObject(targetType, Convert.ToInt32(value));
				return true;
			}
			if (targetType == typeof(float))
			{
				coerced = Convert.ToSingle(value);
				return true;
			}
			if (targetType == typeof(int))
			{
				coerced = Convert.ToInt32(value);
				return true;
			}
			if (value is Il2CppObjectBase obj && obj.Pointer != IntPtr.Zero)
			{
				var ctor = targetType.GetConstructor(
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					new[] { typeof(IntPtr) },
					null);
				if (ctor != null)
				{
					coerced = ctor.Invoke(new object[] { obj.Pointer });
					return coerced != null;
				}
			}
		}
		catch
		{
		}
		return false;
	}

	private static object TryInvokeNoArg(object instance, string[] names)
	{
		if (instance == null || names == null)
		{
			return null;
		}
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
			{
				continue;
			}
			try
			{
				var method = instance.GetType().GetMethod(
					name,
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					Type.EmptyTypes,
					null);
				var value = method?.Invoke(instance, Array.Empty<object>());
				if (value != null)
				{
					return value;
				}
			}
			catch
			{
			}
		}
		return null;
	}
}

#if PLAYTEST_HISTOGRAM_LEGACY_SYMBOLS
// Legacy attribute patch replaced by DamageHistogramForecastRecorder.TryRegisterForecastPatches.
internal static class DamageHistogramBdwuPatch
{
	private static bool Prepare()
	{
		return true;
	}

	// Il2Cpp method parameter names in metadata are a, b — these MUST match for HarmonyX to wire the postfix.
	private static void Postfix(DamageUiParams a, bool b, object __result)
	{
		if (!DamageHistogramSettings.ShouldApplyPatches())
		{
			return;
		}
		_ = b;
		DamageHistogramForecastRecorder.Record(a, __result);
	}
}

// Legacy attribute patch replaced by DamageHistogramForecastRecorder.TryRegisterForecastPatches.
internal static class DamageHistogramEjzOezPatch
{
	private static bool Prepare()
	{
		return true;
	}

	private static void Postfix(DamageUiParams a, bool b, object __result)
	{
		if (!DamageHistogramSettings.ShouldApplyPatches())
		{
			return;
		}
		_ = b;
		DamageHistogramForecastRecorder.Record(a, __result);
	}
}

#endif

#if PLAYTEST_HISTOGRAM_LEGACY_SYMBOLS
[HarmonyPatch(
	typeof(BhHealDamageForecastPanel),
	nameof(BhHealDamageForecastPanel.Show),
	new[] { typeof(object) })]
#endif
internal static class DamageHistogramForecastPanelShowPatch
{
	internal static void Postfix(BhHealDamageForecastPanel __instance)
	{
		if (!DamageHistogramSettings.ShouldApplyPatches())
		{
			return;
		}
		if ((object)__instance == null)
		{
			return;
		}
		try
		{
			var counterVisible = TryReadCounterIndicatorVisible(__instance);
			if (DamageHistogramState.s_hadFirstForecastShow
			    && counterVisible != DamageHistogramState.s_lastCounterIndicatorVisible)
			{
				DamageHistogramState.PmfViewToken++;
			}
			else if (!DamageHistogramState.s_hadFirstForecastShow)
			{
				DamageHistogramState.s_hadFirstForecastShow = true;
			}
			DamageHistogramState.s_lastCounterIndicatorVisible = counterVisible;
			DamageHistogramState.TooltipRetaliationRowVisible = counterVisible;
		}
		catch
		{
			DamageHistogramState.TooltipRetaliationRowVisible = false;
		}
		RectTransform val;
		try
		{
			val = TryInvokeFirstRectTransform(__instance, GameSymbols.DamageForecastPanel.PanelRectGetter.NameHints);
		}
		catch
		{
			val = null;
		}
		if (val == null)
		{
			var t = __instance.transform;
			val = t is RectTransform rt
				? rt
				: null;
		}
		DamageHistogramState.SetPanelRect(val);
		DamageHistogramGameChrome.TryCaptureFromPanel(__instance);
	}

	private static bool TryReadCounterIndicatorVisible(BhHealDamageForecastPanel panel)
	{
		try
		{
			var unitInfo = panel.GetComponentInParent<BhBattleUnitInfoView>(true);
			if (unitInfo == null)
			{
				return false;
			}
			foreach (var name in GameSymbols.DamageForecastPanel.CounterIndicatorFields)
			{
				var indicator = TryReadGameObjectFieldOrProperty(unitInfo, name);
				if (indicator != null)
				{
					return indicator.activeInHierarchy;
				}
			}
		}
		catch
		{
		}
		return false;
	}

	private static GameObject TryReadGameObjectFieldOrProperty(object instance, string name)
	{
		if (instance == null
		    || string.IsNullOrEmpty(name))
		{
			return null;
		}
		try
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var type = instance.GetType();
			var field = type.GetField(name, flags);
			if (field != null)
			{
				return field.GetValue(instance) as GameObject;
			}
			var property = type.GetProperty(name, flags);
			if (property != null)
			{
				return property.GetValue(instance, null) as GameObject;
			}
		}
		catch
		{
		}
		return null;
	}

	private static RectTransform TryInvokeFirstRectTransform(object instance, string[] names)
	{
		if (names == null)
		{
			return null;
		}
		foreach (var name in names)
		{
			var rt = TryInvokeRectTransform(instance, name);
			if (rt != null)
			{
				return rt;
			}
		}
		return null;
	}

	private static RectTransform TryInvokeRectTransform(object instance, string name)
	{
		try
		{
			var method = instance.GetType().GetMethod(
				name,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
				null,
				Type.EmptyTypes,
				null);
			return method?.Invoke(instance, Array.Empty<object>()) as RectTransform;
		}
		catch
		{
			return null;
		}
	}

	private static bool TryGetIl2CppPointer(object value, out IntPtr ptr)
	{
		ptr = IntPtr.Zero;
		try
		{
			if (value is Il2CppObjectBase obj)
			{
				ptr = obj.Pointer;
				return ptr != IntPtr.Zero;
			}
		}
		catch
		{
		}
		return false;
	}
}

internal static class DamageHistogramForecastPanelHidePatch
{
	internal static void Postfix()
	{
		if (!DamageHistogramSettings.ShouldApplyPatches())
		{
			return;
		}
		DamageHistogramState.ClearPanelAnchor();
	}
}
