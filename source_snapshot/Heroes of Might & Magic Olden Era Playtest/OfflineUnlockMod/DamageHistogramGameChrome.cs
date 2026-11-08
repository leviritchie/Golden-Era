using System;
using BepInEx;
using Hex.Session.Battle;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// uGUI sample from <see cref="BhHealDamageForecastPanel"/> (frame + font); title row uses Unicode only in IMGUI.
/// </summary>
internal static class DamageHistogramGameChrome
{
	private static bool _loggedSuccess;
	private static bool _loggedFailure;

	internal static void TryCaptureFromPanel(BhHealDamageForecastPanel panel)
	{
		if (panel == null)
		{
			return;
		}

		try
		{
			CapturePanelFonts(panel);

			var images = panel.GetComponentsInChildren<Image>(true);
			if (images == null
			    || images.Length == 0)
			{
				OnceLogFailure("Damage histogram chrome: forecast panel has no uGUI Image components (yet).");
				return;
			}

			Image best = null;
			var bestArea = 0f;
			for (var i = 0; i < images.Length; i++)
			{
				var im = images[i];
				if (im == null
				    || im.sprite == null)
				{
					continue;
				}

				var w = 1f;
				var h = 1f;
				try
				{
					if (im.rectTransform != null)
					{
						var r = im.rectTransform.rect;
						w = Mathf.Max(1f, r.width);
						h = Mathf.Max(1f, r.height);
					}
				}
				catch
				{
					// keep defaults
				}

				var area = w * h;
				if (area >= bestArea)
				{
					bestArea = area;
					best = im;
				}
			}

			if (best == null
			    || best.sprite == null)
			{
				OnceLogFailure("Damage histogram chrome: Images found but none with a non-null sprite.");
				return;
			}

			var sp = best.sprite;
			DamageHistogramState.CachedDamagePanelFrameSprite = sp;
			if (!_loggedSuccess)
			{
				_loggedSuccess = true;
				Plugin.LogSource?.LogInfo(
					"Damage histogram chrome: cached largest frame-like Image (sprite=" + sp.name
					+ ", imageCount=" + images.Length
					+ ", border=" + sp.border
					+ ").");
			}
		}
		catch (Exception ex)
		{
			OnceLogFailure("Damage histogram chrome probe failed: " + ex.Message);
		}
	}

	/// <summary>Best-effort match to battle-forecast text: prefer legacy <see cref="Text"/>.<see cref="Text.font"/>,
	/// else sample <see cref="TextMeshProUGUI"/> size.</summary>
	private static void CapturePanelFonts(BhHealDamageForecastPanel panel)
	{
		if (panel == null)
		{
			return;
		}
		try
		{
			Font fromLegacy = null;
			var uis = panel.GetComponentsInChildren<Text>(true);
			if (uis != null)
			{
				for (var i = 0; i < uis.Length; i++)
				{
					var t = uis[i];
					if (t == null
					    || t.font == null
					    || !t.enabled
					    || !t.gameObject.activeInHierarchy)
					{
						continue;
					}
					if (t.font != null
					    && t.fontSize >= 6
					    && t.fontSize < 200)
					{
						fromLegacy = t.font;
						DamageHistogramState.CachedPreviewTmpFontSize = t.fontSize;
						DamageHistogramState.CachedPreviewFontFromGame = true;
						break;
					}
				}
			}
			DamageHistogramState.CachedPreviewGuiFont = fromLegacy;

			var bestInBand = 0f;
			TextMeshProUGUI inBandPicked = null;
			var bestAny = 0f;
			TextMeshProUGUI anyPicked = null;
			var tmpList = panel.GetComponentsInChildren<TextMeshProUGUI>(true);
			if (tmpList != null
			    && tmpList.Length != 0)
			{
				for (var j = 0; j < tmpList.Length; j++)
				{
					var tmp = tmpList[j];
					if (tmp == null
					    || !tmp.enabled
					    || !tmp.gameObject.activeInHierarchy)
					{
						continue;
					}
					var fs = (float)tmp.fontSize;
					if (fs < 6f
					    || fs > 200f)
					{
						continue;
					}
					if (fs > bestAny)
					{
						bestAny = fs;
						anyPicked = tmp;
					}
					if (fs >= 8f
					    && fs <= 32f
					    && fs > bestInBand)
					{
						bestInBand = fs;
						inBandPicked = tmp;
					}
				}
			}
			var bestPicked = inBandPicked != null
				? inBandPicked
				: anyPicked;
			if (fromLegacy == null
			    && bestPicked != null)
			{
				var fs = Mathf.RoundToInt((float)bestPicked.fontSize);
				if (fs >= 6
				    && fs < 200)
				{
					DamageHistogramState.CachedPreviewTmpFontSize = fs;
					DamageHistogramState.CachedPreviewFontFromGame = true;
				}
			}
		}
		catch
		{
			// best-effort only
		}
	}

	private static void OnceLogFailure(string message)
	{
		if (_loggedFailure)
		{
			return;
		}
		_loggedFailure = true;
		Plugin.LogSource?.LogInfo(message);
	}
}
