using System;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

public static class TownCursorOverUi20260722
{
	private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

	public static string Run()
	{
		var sb = new StringBuilder();
		try
		{
			AppendCursorRayCast(sb);
			AppendPanel("CanvasCityPanel", sb);
			AppendPanel("CanvasCityTechHUDPanel", sb);
			AppendPanel("CityNavigation", sb);
			AppendPanel("GarnisonPanel", sb);
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "exception=" + ex.GetType().Name + ":" + ex.Message;
		}
	}

	private static void AppendCursorRayCast(StringBuilder sb)
	{
		sb.Append("CursorRayCast=");
		var t = FindTypeEndsWith(".CursorRayCast") ?? FindType("CursorRayCast");
		if (t == null)
		{
			sb.Append("missing");
			return;
		}
		sb.Append(t.FullName);
		foreach (var name in new[] { "IsOverUI", "isOverCityBuilding", "isOverDragAndDrop", "IsOverGameObject" })
		{
			object val = null;
			var p = t.GetProperty(name, All);
			if (p != null && p.GetIndexParameters().Length == 0)
			{
				try { val = p.GetValue(null, null); }
				catch (Exception ex) { val = "fail:" + ex.GetType().Name; }
			}
			else
			{
				var f = t.GetField(name, All) ?? t.GetField(name + "_", All) ?? t.GetField("isOverUI", All);
				if (name == "IsOverUI")
					f = t.GetField("isOverUI", All) ?? f;
				if (f != null && f.IsStatic)
				{
					try { val = f.GetValue(null); }
					catch (Exception ex) { val = "fail:" + ex.GetType().Name; }
				}
			}
			sb.Append(' ').Append(name).Append('=').Append(val == null ? "?" : val.ToString());
		}
	}

	private static void AppendPanel(string name, StringBuilder sb)
	{
		sb.Append(" | ").Append(name).Append('=');
		GameObject go = null;
		if (name == "GarnisonPanel")
		{
			var city = GameObject.Find("CanvasCityPanel");
			if (city != null)
			{
				var tr = city.transform.Find("GarnisonPanel");
				if (tr != null)
					go = tr.gameObject;
			}
		}
		else
		{
			go = GameObject.Find(name);
		}
		if (go == null)
		{
			sb.Append("missing");
			return;
		}
		sb.Append("active=").Append(go.activeInHierarchy);
		var canvas = go.GetComponent<Canvas>();
		if (canvas != null)
			sb.Append(" canvas(en=").Append(canvas.enabled).Append(",ov=").Append(canvas.overrideSorting).Append(",ord=").Append(canvas.sortingOrder).Append(')');
		else
			sb.Append(" canvas=null");
		var ray = go.GetComponent<GraphicRaycaster>();
		sb.Append(" ray=").Append(ray == null ? "null" : ("en=" + ray.enabled));
		var graphics = go.GetComponentsInChildren<Graphic>(true);
		var rayOn = 0;
		var rayOnActive = 0;
		var interactElements = 0;
		var interactActive = 0;
		Type interactType = FindTypeEndsWith(".BhUiInteractElement");
		if (graphics != null)
		{
			for (var i = 0; i < graphics.Length; i++)
			{
				var g = graphics[i];
				if (g == null || !g.raycastTarget)
					continue;
				rayOn++;
				if (g.isActiveAndEnabled && g.gameObject.activeInHierarchy)
					rayOnActive++;
			}
		}
		if (interactType != null)
		{
			var comps = go.GetComponentsInChildren<Component>(true);
			if (comps != null)
			{
				for (var i = 0; i < comps.Length; i++)
				{
					var c = comps[i];
					if (c == null || c.GetType() != interactType)
						continue;
					interactElements++;
					var b = c as Behaviour;
					if (b != null && b.isActiveAndEnabled && b.gameObject.activeInHierarchy)
						interactActive++;
				}
			}
		}
		sb.Append(" raycastGraphicsActive=").Append(rayOnActive).Append('/').Append(rayOn);
		sb.Append(" BhUiInteractElementActive=").Append(interactActive).Append('/').Append(interactElements);
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
		return null;
	}

	private static Type FindTypeEndsWith(string suffix)
	{
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
				var full = t.FullName ?? "";
				if (full.EndsWith(suffix, StringComparison.Ordinal))
					return t;
			}
		}
		return null;
	}
}
