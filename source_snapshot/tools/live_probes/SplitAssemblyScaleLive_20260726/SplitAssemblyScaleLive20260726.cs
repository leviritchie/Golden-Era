using System;
using UnityEngine;
using UnityEngine.UI;

/// <summary>Live tweak: scale production Split Assembly meters ~3x for layout review.</summary>
public static class SplitAssemblyScaleLive20260726
{
	private const string OverlayName = "HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS";
	private const float ScaleFactor = 3f;

	public static string Run(string requestJson)
	{
		try
		{
			GameObject meters = null;
			var all = Resources.FindObjectsOfTypeAll<GameObject>();
			for (var i = 0; i < all.Length; i++)
			{
				var candidate = all[i];
				if (candidate == null || candidate.name != OverlayName)
					continue;
				if (!candidate.activeInHierarchy)
					continue;
				meters = candidate;
				break;
			}
			if (!meters)
				return Fail("no active " + OverlayName);

			var root = meters.GetComponent<RectTransform>();
			if (!root)
				return Fail("meter RectTransform missing");

			var beforeScale = root.localScale;
			var beforeSize = root.sizeDelta;
			var beforePos = root.anchoredPosition;
			var beforeLossy = root.lossyScale;

			root.localScale = new Vector3(ScaleFactor, ScaleFactor, 1f);

			// Widen hit plate so hover/tooltip review still tracks the visible chrome.
			var hit = meters.GetComponent<Image>();
			if (hit)
				hit.raycastTarget = true;

			var afterLossy = root.lossyScale;
			return "{"
			       + "\"ok\":true"
			       + ",\"path\":" + Json(BuildPath(meters.transform))
			       + ",\"scaleFactor\":" + ScaleFactor.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
			       + ",\"beforeLocalScale\":" + Json(beforeScale.x + "," + beforeScale.y)
			       + ",\"afterLocalScale\":" + Json(root.localScale.x + "," + root.localScale.y)
			       + ",\"beforeSizeDelta\":" + Json(beforeSize.x + "x" + beforeSize.y)
			       + ",\"afterSizeDelta\":" + Json(root.sizeDelta.x + "x" + root.sizeDelta.y)
			       + ",\"anchoredPosition\":" + Json(beforePos.x + "," + beforePos.y)
			       + ",\"beforeLossy\":" + Json(beforeLossy.x + "," + beforeLossy.y)
			       + ",\"afterLossy\":" + Json(afterLossy.x + "," + afterLossy.y)
			       + ",\"note\":\"volatile live scale only; restart restores production size\""
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static string BuildPath(Transform t)
	{
		if (!t)
			return "";
		var path = t.name;
		var cur = t.parent;
		while (cur != null)
		{
			path = cur.name + "/" + path;
			cur = cur.parent;
		}
		return path;
	}

	private static string Json(string value)
	{
		if (value == null)
			return "null";
		return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}

	private static string Fail(string message)
	{
		return "{\"ok\":false,\"error\":" + Json(message) + "}";
	}
}
