using System;
using System.Reflection;
using Hex.Session.Hud;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

/// <summary>
/// Live proof: Split Assembly tooltip pump ticks, hover hit at meter center, forced show.
/// </summary>
public static class SplitAssemblyTooltipProof20260726
{
	public static string Run(string requestJson)
	{
		try
		{
			GameObject meters = null;
			var all = Resources.FindObjectsOfTypeAll<GameObject>();
			for (var i = 0; i < all.Length; i++)
			{
				var candidate = all[i];
				if (candidate == null || candidate.name != "HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS")
					continue;
				if (!candidate.activeInHierarchy)
					continue;
				meters = candidate;
				break;
			}
			if (!meters)
				return Fail("no active HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS");

			var rt = meters.GetComponent<RectTransform>();
			if (!rt)
				return Fail("meter RectTransform missing");

			var panel = Object.FindObjectOfType<BhHeroHUDPanel>();
			var panelKey = panel ? panel.GetInstanceID() : 0;

			var corners = new Vector3[4];
			rt.GetWorldCorners(corners);
			var centerWorld = (corners[0] + corners[2]) * 0.5f;
			var centerScreen = RectTransformUtility.WorldToScreenPoint(null, centerWorld);
			var insideCenter = RectTransformUtility.RectangleContainsScreenPoint(rt, centerScreen);
			var insideMouse = RectTransformUtility.RectangleContainsScreenPoint(rt, Input.mousePosition);

			var mod = FindAssembly("OfflineUnlockMod");
			var hudType = mod != null ? mod.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyArmyStripHud", false) : null;
			var pumpTicks = ReadStaticInt(hudType, "HoverPumpTicks");
			var lastHoverKey = ReadStaticInt(hudType, "LastHoverOwnerKey");
			var tooltipVisible = ReadStaticBool(hudType, "TooltipVisible");

			var ownerKey = panelKey;
			var viewLookupOk = false;
			var viewsField = hudType != null
				? hudType.GetField("ViewsByElement", BindingFlags.Static | BindingFlags.NonPublic)
				: null;
			if (viewsField != null)
			{
				var dict = viewsField.GetValue(null) as System.Collections.IDictionary;
				if (dict != null)
				{
					viewLookupOk = dict.Contains(ownerKey);
					if (!viewLookupOk)
					{
						foreach (var key in dict.Keys)
						{
							ownerKey = (int)key;
							viewLookupOk = true;
							break;
						}
					}
				}
			}

			var forceOk = false;
			var forceErr = "";
			try
			{
				var show = hudType != null
					? hudType.GetMethod(
						"ShowTooltipForOwner",
						BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
					: null;
				if (show == null)
					forceErr = "ShowTooltipForOwner missing";
				else
				{
					show.Invoke(null, new object[] { ownerKey });
					forceOk = true;
				}
			}
			catch (Exception ex)
			{
				forceErr = ex.GetType().Name + ": " + ex.Message;
			}

			GameObject tipGo = null;
			for (var i = 0; i < all.Length; i++)
			{
				var candidate = all[i];
				if (candidate != null && candidate.name == "HOMM3_FACTORY_SPLIT_ASSEMBLY_TOOLTIP")
				{
					tipGo = candidate;
					break;
				}
			}

			var tooltipActive = tipGo != null && tipGo.activeInHierarchy;
			var tooltipTextLen = 0;
			var tooltipWorld = "0,0,0";
			var tooltipPath = "";
			if (tipGo != null)
			{
				tooltipPath = BuildPath(tipGo.transform);
				var wp = tipGo.transform.position;
				tooltipWorld = wp.x + "," + wp.y + "," + wp.z;
				var tmp = tipGo.GetComponentInChildren<TMPro.TextMeshProUGUI>(true);
				if (tmp != null && !string.IsNullOrEmpty(tmp.text))
					tooltipTextLen = tmp.text.Length;
			}

			return "{"
			       + "\"ok\":true"
			       + ",\"metersPath\":" + Json(BuildPath(meters.transform))
			       + ",\"ownerKey\":" + ownerKey
			       + ",\"panelInstanceId\":" + panelKey
			       + ",\"viewLookupOk\":" + (viewLookupOk ? "true" : "false")
			       + ",\"hoverPumpTicks\":" + pumpTicks
			       + ",\"lastHoverOwnerKey\":" + lastHoverKey
			       + ",\"tooltipVisibleFlag\":" + (tooltipVisible ? "true" : "false")
			       + ",\"insideMouse\":" + (insideMouse ? "true" : "false")
			       + ",\"insideCenter\":" + (insideCenter ? "true" : "false")
			       + ",\"centerScreen\":" + Json(centerScreen.x + "," + centerScreen.y)
			       + ",\"mouse\":" + Json(Input.mousePosition.x + "," + Input.mousePosition.y)
			       + ",\"forceShowOk\":" + (forceOk ? "true" : "false")
			       + ",\"forceShowErr\":" + Json(forceErr)
			       + ",\"tooltipActive\":" + (tooltipActive ? "true" : "false")
			       + ",\"tooltipPath\":" + Json(tooltipPath)
			       + ",\"tooltipWorld\":" + Json(tooltipWorld)
			       + ",\"tooltipTextLen\":" + tooltipTextLen
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static int ReadStaticInt(Type type, string name)
	{
		if (type == null)
			return 0;
		try
		{
			var field = type.GetField(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			return field != null ? (int)field.GetValue(null) : 0;
		}
		catch
		{
			return 0;
		}
	}

	private static bool ReadStaticBool(Type type, string name)
	{
		if (type == null)
			return false;
		try
		{
			var field = type.GetField(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			return field != null && (bool)field.GetValue(null);
		}
		catch
		{
			return false;
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

	private static Assembly FindAssembly(string name)
	{
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		for (var i = 0; i < assemblies.Length; i++)
		{
			var asm = assemblies[i];
			if (asm != null && string.Equals(asm.GetName().Name, name, StringComparison.OrdinalIgnoreCase))
				return asm;
		}
		return null;
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
