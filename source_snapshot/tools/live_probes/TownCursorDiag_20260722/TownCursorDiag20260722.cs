using System;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;

public static class TownCursorDiag20260722
{
	private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

	public static string Run()
	{
		var sb = new StringBuilder(4096);
		try
		{
			var scene = SceneManager.GetActiveScene();
			sb.Append("activeScene=").Append(scene.name ?? "?");
			sb.Append(" loadedScenes=");
			for (var i = 0; i < SceneManager.sceneCount; i++)
			{
				var s = SceneManager.GetSceneAt(i);
				if (i > 0)
					sb.Append(',');
				sb.Append(s.name ?? "?").Append('(').Append(s.isLoaded ? "loaded" : "unloaded").Append(')');
			}

			AppendCursor(sb);
			AppendGarrison(sb);
			AppendCanvasCityPanel(sb);
			AppendAllCityPanels(sb);
			AppendOverUi(sb);
			AppendTechHudRaycasts(sb);
			AppendCityInteractCursorHint(sb);
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "exception=" + ex.GetType().Name + ":" + ex.Message + " stack=" + (ex.StackTrace ?? "");
		}
	}

	private static void AppendCursor(StringBuilder sb)
	{
		sb.Append(" | cursor=");
		var cipType = FindType("MonoBehaviourPublicSocomaSobaedObSobxInUnique") ?? FindType("cip");
		if (cipType == null)
		{
			sb.Append("cipTypeMissing");
			return;
		}
		sb.Append("type=").Append(cipType.FullName ?? cipType.Name);

		object singleton = null;
		foreach (var m in cipType.GetMethods(All))
		{
			if (!m.IsStatic || m.GetParameters().Length != 0)
				continue;
			if (m.ReturnType != cipType)
				continue;
			try
			{
				singleton = m.Invoke(null, null);
				if (singleton != null)
				{
					sb.Append(" singletonVia=").Append(m.Name);
					break;
				}
			}
			catch
			{
			}
		}
		if (singleton == null)
		{
			sb.Append(" singleton=null");
			return;
		}

		foreach (var m in cipType.GetMethods(All))
		{
			if (m.IsStatic || m.GetParameters().Length != 0)
				continue;
			var rt = m.ReturnType;
			if (rt == null)
				continue;
			var rtn = rt.FullName ?? rt.Name ?? "";
			if (!rtn.EndsWith("ECursor", StringComparison.Ordinal))
				continue;
			try
			{
				var val = m.Invoke(singleton, null);
				sb.Append(" ECursorVia=").Append(m.Name).Append(" value=").Append(val == null ? "null" : val.ToString());
				if (val != null)
					sb.Append(" ordinal=").Append(Convert.ToInt32(val));
			}
			catch (Exception ex)
			{
				sb.Append(" ECursorFail=").Append(ex.GetType().Name).Append(':').Append(ex.Message);
			}
		}

		foreach (var f in cipType.GetFields(All))
		{
			if (f.IsStatic)
				continue;
			var ft = f.FieldType;
			var ftn = ft == null ? "" : (ft.FullName ?? ft.Name ?? "");
			if (!ftn.EndsWith("ECursor", StringComparison.Ordinal))
				continue;
			try
			{
				var val = f.GetValue(singleton);
				sb.Append(" ECursorField=").Append(f.Name).Append(" value=").Append(val == null ? "null" : val.ToString());
				if (val != null)
					sb.Append(" ordinal=").Append(Convert.ToInt32(val));
			}
			catch
			{
			}
		}
	}

	private static void AppendGarrison(StringBuilder sb)
	{
		sb.Append(" | garrison=");
		Transform found = null;
		var city = GameObject.Find("CanvasCityPanel");
		if (city != null)
		{
			var t = city.transform.Find("GarnisonPanel");
			if (t != null)
				found = t;
		}
		if (found == null)
		{
			sb.Append("missing");
			return;
		}

		sb.Append("path=").Append(PathOf(found));
		sb.Append(" active=").Append(found.gameObject.activeInHierarchy);
		sb.Append(" sibling=").Append(found.GetSiblingIndex());
		sb.Append(" parentChildCount=").Append(found.parent == null ? -1 : found.parent.childCount);
		AppendBehaviourSummary(sb, found.gameObject, "ownCanvas", "UnityEngine.Canvas");
		AppendBehaviourSummary(sb, found.gameObject, "ownRaycaster", "UnityEngine.UI.GraphicRaycaster");

		var nestedCanvases = FindComponentsInChildrenByTypeName(found.gameObject, "UnityEngine.Canvas", true);
		sb.Append(" nestedCanvasCount=").Append(nestedCanvases.Count);
		for (var i = 0; i < nestedCanvases.Count && i < 6; i++)
		{
			var c = nestedCanvases[i];
			if (c == null)
				continue;
			sb.Append(" nested[").Append(i).Append("]=").Append(PathOf(c.transform));
			AppendCanvasProps(sb, c);
		}

		if (found.parent != null)
		{
			sb.Append(" siblings=");
			for (var i = 0; i < found.parent.childCount && i < 24; i++)
			{
				var ch = found.parent.GetChild(i);
				if (i > 0)
					sb.Append(',');
				sb.Append(i).Append(':').Append(ch == null ? "?" : ch.name);
			}
		}
	}

	private static void AppendCanvasCityPanel(StringBuilder sb)
	{
		sb.Append(" | cityPanel=");
		var go = GameObject.Find("CanvasCityPanel");
		if (go == null)
		{
			sb.Append("missing");
			return;
		}
		sb.Append("active=").Append(go.activeInHierarchy);
		AppendBehaviourSummary(sb, go, "canvas", "UnityEngine.Canvas");
		AppendBehaviourSummary(sb, go, "raycaster", "UnityEngine.UI.GraphicRaycaster");
		AppendBehaviourSummary(sb, go, "cg", "UnityEngine.CanvasGroup");
	}

	private static void AppendBehaviourSummary(StringBuilder sb, GameObject go, string label, string typeName)
	{
		sb.Append(' ').Append(label).Append('=');
		var c = FindComponentByTypeName(go, typeName);
		if (c == null)
		{
			sb.Append(FindType(typeName) == null ? "typeMissing" : "null");
			return;
		}
		if (string.Equals(typeName, "UnityEngine.Canvas", StringComparison.Ordinal))
		{
			AppendCanvasProps(sb, c);
			return;
		}
		if (string.Equals(typeName, "UnityEngine.CanvasGroup", StringComparison.Ordinal))
		{
			sb.Append("{alpha=").Append(ReadProp(c, "alpha"))
				.Append(",blocks=").Append(ReadProp(c, "blocksRaycasts"))
				.Append(",interactable=").Append(ReadProp(c, "interactable"))
				.Append('}');
			return;
		}
		sb.Append("{en=").Append(ReadProp(c, "enabled")).Append('}');
	}

	private static void AppendCanvasProps(StringBuilder sb, Component canvas)
	{
		sb.Append("{en=").Append(ReadProp(canvas, "enabled"))
			.Append(",ov=").Append(ReadProp(canvas, "overrideSorting"))
			.Append(",ord=").Append(ReadProp(canvas, "sortingOrder"))
			.Append(",mode=").Append(ReadProp(canvas, "renderMode"))
			.Append('}');
	}

	private static object ReadProp(object target, string name)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		var prop = type.GetProperty(name, All);
		if (prop != null && prop.GetIndexParameters().Length == 0)
		{
			try { return prop.GetValue(target, null); }
			catch { }
		}
		var field = type.GetField(name, All) ?? type.GetField("m_" + char.ToUpperInvariant(name[0]) + name.Substring(1), All);
		if (field != null)
		{
			try { return field.GetValue(target); }
			catch { }
		}
		return "?";
	}

	
	private static void AppendAllCityPanels(StringBuilder sb)
	{
		sb.Append(" | allCityPanels=");
		var transforms = UnityEngine.Object.FindObjectsOfType<Transform>(true);
		var n = 0;
		for (var i = 0; i < transforms.Length; i++)
		{
			var t = transforms[i];
			if (t == null || t.name != "CanvasCityPanel")
				continue;
			n++;
			sb.Append(" [").Append(n).Append("] path=").Append(PathOf(t))
				.Append(" active=").Append(t.gameObject.activeInHierarchy)
				.Append(" scene=").Append(t.gameObject.scene.name ?? "?")
				.Append(" childCount=").Append(t.childCount)
				.Append(" children=");
			for (var c = 0; c < t.childCount && c < 30; c++)
			{
				var ch = t.GetChild(c);
				if (c > 0) sb.Append(',');
				sb.Append(c).Append(':').Append(ch == null ? "?" : ch.name)
					.Append(ch != null && ch.gameObject.activeInHierarchy ? "" : "(off)");
			}
		}
		sb.Append(" count=").Append(n);
	}

	
	private static void AppendOverUi(StringBuilder sb)
	{
		sb.Append(" | overUI=");
		var t = FindType("CursorRayCast") ?? FindType("Hex.Cursors.CursorRayCast") ?? FindTypeByEndsWith(".CursorRayCast");
		if (t == null)
		{
			sb.Append("typeMissing");
			return;
		}
		sb.Append("type=").Append(t.FullName ?? t.Name);
		foreach (var name in new[] { "IsOverUI", "get_IsOverUI", "isOverUI", "get_isOverUI" })
		{
			var p = t.GetProperty(name, All);
			if (p != null && p.GetIndexParameters().Length == 0)
			{
				try
				{
					sb.Append(' ').Append(name).Append('=').Append(p.GetValue(null, null));
					return;
				}
				catch (Exception ex)
				{
					sb.Append(' ').Append(name).Append("Fail=").Append(ex.GetType().Name);
				}
			}
			var m = t.GetMethod(name, All, null, Type.EmptyTypes, null);
			if (m != null && m.IsStatic)
			{
				try
				{
					sb.Append(' ').Append(name).Append('=').Append(m.Invoke(null, null));
					return;
				}
				catch (Exception ex)
				{
					sb.Append(' ').Append(name).Append("Fail=").Append(ex.GetType().Name);
				}
			}
		}
		foreach (var f in t.GetFields(All))
		{
			if (!f.IsStatic) continue;
			var n = f.Name ?? "";
			if (n.IndexOf("OverUI", StringComparison.OrdinalIgnoreCase) < 0 && n.IndexOf("overUI", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			try { sb.Append(' ').Append(n).Append('=').Append(f.GetValue(null)); }
			catch { }
		}
	}

	private static void AppendTechHudRaycasts(StringBuilder sb)
	{
		sb.Append(" | techHud=");
		var go = GameObject.Find("CanvasCityTechHUDPanel");
		if (go == null)
		{
			sb.Append("missing");
			return;
		}
		sb.Append("active=").Append(go.activeInHierarchy);
		AppendBehaviourSummary(sb, go, "canvas", "UnityEngine.Canvas");
		AppendBehaviourSummary(sb, go, "raycaster", "UnityEngine.UI.GraphicRaycaster");
		AppendBehaviourSummary(sb, go, "cg", "UnityEngine.CanvasGroup");
		var graphics = go.GetComponentsInChildren<UnityEngine.UI.Graphic>(true);
		var total = 0;
		var rayTrue = 0;
		var rayTrueActive = 0;
		var fullBleed = 0;
		if (graphics != null)
		{
			total = graphics.Length;
			for (var i = 0; i < graphics.Length; i++)
			{
				var g = graphics[i];
				if (g == null) continue;
				if (!g.raycastTarget) continue;
				rayTrue++;
				if (g.isActiveAndEnabled && g.gameObject.activeInHierarchy)
					rayTrueActive++;
				var rt = g.transform as RectTransform;
				if (rt != null)
				{
					var r = rt.rect;
					if (r.width >= 1500f && r.height >= 800f)
						fullBleed++;
				}
			}
		}
		sb.Append(" graphics=").Append(total)
			.Append(" raycastTrue=").Append(rayTrue)
			.Append(" raycastTrueActive=").Append(rayTrueActive)
			.Append(" fullBleedRayish=").Append(fullBleed);
		// CityNavigation too
		var nav = GameObject.Find("CityNavigation");
		sb.Append(" | cityNav=");
		if (nav == null) sb.Append("missing");
		else
		{
			sb.Append("active=").Append(nav.activeInHierarchy);
			AppendBehaviourSummary(sb, nav, "canvas", "UnityEngine.Canvas");
			AppendBehaviourSummary(sb, nav, "raycaster", "UnityEngine.UI.GraphicRaycaster");
		}
	}

	private static Type FindTypeByEndsWith(string suffix)
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = asm.GetTypes(); }
			catch { continue; }
			for (var i = 0; i < types.Length; i++)
			{
				var t = types[i];
				if (t == null) continue;
				var full = t.FullName ?? t.Name ?? "";
				if (full.EndsWith(suffix, StringComparison.Ordinal))
					return t;
			}
		}
		return null;
	}

	private static void AppendCityInteractCursorHint(StringBuilder sb)
	{
		sb.Append(" | ECursorHints=");
		var et = FindType("Hex.Cursors.ECursor");
		if (et == null || !et.IsEnum)
		{
			sb.Append("missing");
			return;
		}
		foreach (var name in new[] { "PlayerInteractCity", "HeroInteractCity", "HeroInteractCityRed", "HeroInteractCityGray", "Normal", "Wait" })
		{
			try
			{
				var v = Enum.Parse(et, name);
				sb.Append(name).Append('=').Append(Convert.ToInt32(v)).Append(' ');
			}
			catch
			{
			}
		}
	}

	private static string PathOf(Transform t)
	{
		if (t == null)
			return "";
		var parts = new System.Collections.Generic.List<string>();
		var cur = t;
		var guard = 0;
		while (cur != null && guard++ < 40)
		{
			parts.Add(cur.name ?? "");
			cur = cur.parent;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static Component FindComponentByTypeName(GameObject go, string typeName)
	{
		if (go == null || string.IsNullOrEmpty(typeName))
			return null;
		var comps = go.GetComponents<Component>();
		if (comps == null)
			return null;
		for (var i = 0; i < comps.Length; i++)
		{
			var c = comps[i];
			if (c == null)
				continue;
			var t = c.GetType();
			var full = t.FullName ?? t.Name ?? "";
			if (string.Equals(full, typeName, StringComparison.Ordinal) || string.Equals(t.Name, typeName, StringComparison.Ordinal))
				return c;
			if (full.EndsWith("." + typeName, StringComparison.Ordinal))
				return c;
		}
		return null;
	}

	private static System.Collections.Generic.List<Component> FindComponentsInChildrenByTypeName(GameObject go, string typeName, bool includeInactive)
	{
		var result = new System.Collections.Generic.List<Component>();
		if (go == null)
			return result;
		var comps = go.GetComponentsInChildren<Component>(includeInactive);
		if (comps == null)
			return result;
		for (var i = 0; i < comps.Length; i++)
		{
			var c = comps[i];
			if (c == null)
				continue;
			var t = c.GetType();
			var full = t.FullName ?? t.Name ?? "";
			if (string.Equals(full, typeName, StringComparison.Ordinal)
			    || string.Equals(t.Name, typeName, StringComparison.Ordinal)
			    || full.EndsWith("." + typeName, StringComparison.Ordinal))
			{
				result.Add(c);
			}
		}
		return result;
	}

	private static Type FindType(string name)
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				var t = asm.GetType(name, false);
				if (t != null)
					return t;
			}
			catch
			{
			}
		}
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = asm.GetTypes(); }
			catch { continue; }
			for (var i = 0; i < types.Length; i++)
			{
				var t = types[i];
				if (t == null)
					continue;
				if (string.Equals(t.Name, name, StringComparison.Ordinal) || string.Equals(t.FullName, name, StringComparison.Ordinal))
					return t;
			}
		}
		return null;
	}
}
