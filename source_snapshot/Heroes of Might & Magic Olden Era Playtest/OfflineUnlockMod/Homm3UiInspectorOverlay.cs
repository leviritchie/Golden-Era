using System;
using System.Collections.Generic;
using System.Text;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class Homm3UiInspectorOverlayBootstrap
{
	private const string GoName = "Homm3UiInspectorOverlay";
	private static bool _registered;
	private static bool _attached;

	internal static void Ensure()
	{
		if (_attached)
			return;
		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3UiInspectorOverlayBehaviour>();
				_registered = true;
			}

			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<Homm3UiInspectorOverlayBehaviour>() == null)
				Plugin.LogSource?.LogError("HOMM3_UI_INSPECTOR bootstrap: AddComponent returned null.");
			UnityObject.DontDestroyOnLoad(go);
			_attached = true;
			Plugin.LogSource?.LogInfo("HOMM3_UI_INSPECTOR bootstrap: registered IMGUI host. Press F8 to toggle.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("HOMM3_UI_INSPECTOR bootstrap failed: " + ex);
		}
	}
}

internal static class Homm3UiInspectorContextRegistry
{
	private sealed class Entry
	{
		internal string Surface;
		internal string Detail;
		internal int Frame;
	}

	private static readonly Dictionary<int, Entry> Entries = new();

	internal static void Record(GameObject go, string surface, string detail)
	{
		if (!go)
			return;
		Entries[go.GetInstanceID()] = new Entry
		{
			Surface = Clean(surface),
			Detail = Clean(detail),
			Frame = Time.frameCount
		};
	}

	internal static string FindNearest(GameObject go)
	{
		for (var cur = go ? go.transform : null; cur != null; cur = cur.parent)
		{
			if (Entries.TryGetValue(cur.gameObject.GetInstanceID(), out var entry))
				return entry.Surface + " frame=" + entry.Frame + " " + entry.Detail;
		}
		return null;
	}

	private static string Clean(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "?";
		return value.Replace('\r', ' ').Replace('\n', ' ').Trim();
	}
}

public sealed class Homm3UiInspectorOverlayBehaviour : MonoBehaviour
{
	private struct TargetInfo
	{
		internal GameObject GameObject;
		internal Rect ScreenRect;
		internal string Source;
		internal string Report;
	}

	private static bool s_enabled;
	private static TargetInfo s_hover;
	private static TargetInfo s_pinned;
	private static bool s_hasHover;
	private static bool s_hasPinned;
	private static GUIStyle s_panelStyle;
	private static GUIStyle s_labelStyle;
	private static GUIStyle s_smallStyle;
	private static Texture2D s_borderTexture;
	private static int s_styleScaleBucket = -1;
	private static int s_lastRefreshFrame = -1;
	private static readonly Il2CppSystem.Collections.Generic.List<RaycastResult> RaycastResults = new();

	private const string GrepKey = "HOMM3_UI_INSPECTOR";

	private void OnGUI()
	{
		var evt = Event.current;
		if (evt != null && evt.type == EventType.KeyDown)
		{
			if (evt.keyCode == KeyCode.F8)
			{
				s_enabled = !s_enabled;
				if (!s_enabled)
				{
					s_hasHover = false;
					s_hasPinned = false;
				}
				Plugin.LogSource?.LogInfo(GrepKey + " toggle enabled=" + s_enabled);
				evt.Use();
				return;
			}
			if (s_enabled && evt.keyCode == KeyCode.F7)
			{
				LogCurrent();
				evt.Use();
				return;
			}
		}

		if (!s_enabled)
			return;

		EnsureStyles();
		if (Event.current.type == EventType.Repaint || s_lastRefreshFrame != Time.frameCount)
		{
			s_lastRefreshFrame = Time.frameCount;
			s_hasHover = TryBuildTarget(Input.mousePosition, out s_hover);
		}

		if (evt != null && evt.type == EventType.MouseDown && evt.button == 0)
		{
			if (s_hasHover)
			{
				s_pinned = s_hover;
				s_hasPinned = true;
				LogCurrent();
			}
			evt.Use();
		}

		var target = s_hasPinned ? s_pinned : s_hover;
		if (target.GameObject)
			DrawBorder(target.ScreenRect, s_hasPinned ? Color.cyan : Color.yellow);
		DrawPanel(target);
	}

	private static void EnsureStyles()
	{
		var bucket = Mathf.RoundToInt(UiScale() * 100f);
		if (s_panelStyle != null && s_styleScaleBucket == bucket)
			return;
		s_styleScaleBucket = bucket;
		var scale = UiScale();
		var padX = Mathf.RoundToInt(10f * scale);
		var padY = Mathf.RoundToInt(8f * scale);
		var padding = new RectOffset();
		padding.left = padX;
		padding.right = padX;
		padding.top = padY;
		padding.bottom = padY;
		s_panelStyle = new GUIStyle(GUI.skin.box)
		{
			alignment = TextAnchor.UpperLeft,
			padding = padding,
			wordWrap = true,
			fontSize = Mathf.RoundToInt(13f * scale)
		};
		s_panelStyle.normal.textColor = Color.white;
		s_labelStyle = new GUIStyle(GUI.skin.label)
		{
			alignment = TextAnchor.UpperLeft,
			wordWrap = true,
			fontSize = Mathf.RoundToInt(13f * scale)
		};
		s_labelStyle.normal.textColor = Color.white;
		s_smallStyle = new GUIStyle(s_labelStyle) { fontSize = Mathf.RoundToInt(11f * scale) };
		s_borderTexture = Texture2D.whiteTexture;
	}

	private static bool TryBuildTarget(Vector2 mousePosition, out TargetInfo info)
	{
		info = default;
		var go = Raycast(mousePosition, out var source) ?? FindSmallestRectUnderCursor(mousePosition, out source);
		if (!go)
			return false;

		var rectTransform = go.GetComponent<RectTransform>();
		info.GameObject = go;
		info.Source = source;
		info.ScreenRect = rectTransform ? ToGuiRect(rectTransform) : new Rect(Input.mousePosition.x, Screen.height - Input.mousePosition.y, 16f, 16f);
		info.Report = BuildReport(go, source);
		return true;
	}

	private static GameObject Raycast(Vector2 mousePosition, out string source)
	{
		source = "raycast:none";
		var current = EventSystem.current;
		if (!current)
			return null;
		try
		{
			RaycastResults.Clear();
			var data = new PointerEventData(current) { position = mousePosition };
			current.RaycastAll(data, RaycastResults);
			if (RaycastResults.Count <= 0)
				return null;
			var result = RaycastResults[0];
			source = "raycast:" + RaycastResults.Count;
			return result.gameObject;
		}
		catch (Exception ex)
		{
			source = "raycast:error:" + ex.GetType().Name;
			return null;
		}
	}

	private static GameObject FindSmallestRectUnderCursor(Vector2 mousePosition, out string source)
	{
		source = "rect-scan:none";
		GameObject best = null;
		var bestArea = float.MaxValue;
		try
		{
			var all = UnityObject.FindObjectsOfType<RectTransform>();
			foreach (var rt in all)
			{
				if (!rt || !rt.gameObject.activeInHierarchy)
					continue;
				if (!RectTransformUtility.RectangleContainsScreenPoint(rt, mousePosition))
					continue;
				var r = ToGuiRect(rt);
				var area = Mathf.Max(1f, r.width) * Mathf.Max(1f, r.height);
				if (area < bestArea)
				{
					bestArea = area;
					best = rt.gameObject;
				}
			}
			if (best)
				source = "rect-scan";
		}
		catch (Exception ex)
		{
			source = "rect-scan:error:" + ex.GetType().Name;
		}
		return best;
	}

	private static string BuildReport(GameObject go, string source)
	{
		var sb = new StringBuilder(4096);
		sb.AppendLine("F8 close | click pin | F7 log");
		sb.AppendLine("source: " + source + (s_hasPinned ? " | pinned" : ""));
		sb.AppendLine("path: " + GetPath(go.transform));
		sb.AppendLine("active: self=" + go.activeSelf + " hierarchy=" + go.activeInHierarchy + " layer=" + go.layer);
		var context = Homm3UiInspectorContextRegistry.FindNearest(go);
		if (!string.IsNullOrWhiteSpace(context))
			sb.AppendLine("known-context: " + context);

		AppendRect(sb, go);
		AppendCanvas(sb, go);
		AppendComponents(sb, go);
		AppendGraphicDetails(sb, go);
		AppendAncestorComponents(sb, go);
		AppendChildGraphicsUnderCursor(sb, go);
		return sb.ToString();
	}

	private static void AppendRect(StringBuilder sb, GameObject go)
	{
		var rt = go.GetComponent<RectTransform>();
		if (!rt)
			return;
		var r = ToGuiRect(rt);
		sb.AppendLine("rect: x=" + F(r.x) + " y=" + F(r.y) + " w=" + F(r.width) + " h=" + F(r.height));
		sb.AppendLine("anchors: min=" + V2(rt.anchorMin) + " max=" + V2(rt.anchorMax) + " pivot=" + V2(rt.pivot));
	}

	private static void AppendCanvas(StringBuilder sb, GameObject go)
	{
		var canvas = go.GetComponentInParent<Canvas>();
		if (!canvas)
			return;
		sb.AppendLine("canvas: " + GetPath(canvas.transform) + " mode=" + canvas.renderMode + " order=" + canvas.sortingOrder + " override=" + canvas.overrideSorting);
		var raycaster = canvas.GetComponent<GraphicRaycaster>();
		if (raycaster)
			sb.AppendLine("raycaster: enabled=" + raycaster.enabled + " blocking=" + raycaster.blockingObjects + " ignoreReversed=" + raycaster.ignoreReversedGraphics);
	}

	private static void AppendComponents(StringBuilder sb, GameObject go)
	{
		sb.AppendLine("components:");
		try
		{
			var comps = go.GetComponents<Component>();
			foreach (var comp in comps)
			{
				if (!comp)
					continue;
				sb.AppendLine("  " + comp.GetIl2CppType().FullName + " enabled=" + EnabledState(comp));
			}
		}
		catch (Exception ex)
		{
			sb.AppendLine("  <component read failed: " + ex.GetType().Name + ">");
		}
	}

	private static void AppendGraphicDetails(StringBuilder sb, GameObject go)
	{
		var graphic = go.GetComponent<Graphic>();
		if (graphic)
			sb.AppendLine("graphic: " + graphic.GetIl2CppType().Name + " enabled=" + graphic.enabled + " raycastTarget=" + graphic.raycastTarget + " color=" + ColorText(graphic.color));
		var img = go.GetComponent<Image>();
		if (img)
			sb.AppendLine("image: sprite=" + NameOf(img.sprite) + " tex=" + NameOf(img.sprite ? img.sprite.texture : null) + " type=" + img.type + " preserve=" + img.preserveAspect);
		var raw = go.GetComponent<RawImage>();
		if (raw)
			sb.AppendLine("rawImage: tex=" + NameOf(raw.texture) + " uv=" + raw.uvRect);
		var tmp = go.GetComponent<TMP_Text>();
		if (tmp)
			sb.AppendLine("tmp: text=\"" + Trim(tmp.text, 180) + "\" font=" + NameOf(tmp.font) + " size=" + F(tmp.fontSize));
		var legacyText = go.GetComponent<Text>();
		if (legacyText)
			sb.AppendLine("text: text=\"" + Trim(legacyText.text, 180) + "\" font=" + NameOf(legacyText.font) + " size=" + legacyText.fontSize);
		var selectable = go.GetComponent<Selectable>();
		if (selectable)
			sb.AppendLine("selectable: interactable=" + selectable.interactable + " transition=" + selectable.transition + " targetGraphic=" + NameOf(selectable.targetGraphic));
	}

	private static void AppendAncestorComponents(StringBuilder sb, GameObject go)
	{
		sb.AppendLine("ancestor ui scripts:");
		var logged = 0;
		for (var cur = go.transform.parent; cur != null && logged < 8; cur = cur.parent)
		{
			var summary = ComponentSummary(cur.gameObject, onlyInteresting: true);
			if (string.IsNullOrWhiteSpace(summary))
				continue;
			sb.AppendLine("  " + cur.name + ": " + summary);
			logged++;
		}
		if (logged == 0)
			sb.AppendLine("  <none>");
	}

	private static void AppendChildGraphicsUnderCursor(StringBuilder sb, GameObject go)
	{
		sb.AppendLine("child graphics under cursor:");
		var mouse = Input.mousePosition;
		var count = 0;
		AppendChildGraphicsRecursive(sb, go.transform, mouse, 0, ref count);
		if (count == 0)
			sb.AppendLine("  <none>");
	}

	private static void AppendChildGraphicsRecursive(StringBuilder sb, Transform root, Vector2 mouse, int depth, ref int count)
	{
		if (depth > 4 || count >= 16)
			return;
		for (var i = 0; i < root.childCount && count < 16; i++)
		{
			var child = root.GetChild(i);
			var rt = child.GetComponent<RectTransform>();
			if (rt && child.gameObject.activeInHierarchy && RectTransformUtility.RectangleContainsScreenPoint(rt, mouse))
			{
				var graphic = child.GetComponent<Graphic>();
				if (graphic)
				{
					sb.AppendLine("  " + GetPath(child) + " :: " + DescribeGraphic(child.gameObject));
					count++;
				}
			}
			AppendChildGraphicsRecursive(sb, child, mouse, depth + 1, ref count);
		}
	}

	private static string ComponentSummary(GameObject go, bool onlyInteresting)
	{
		try
		{
			var parts = new List<string>();
			var comps = go.GetComponents<Component>();
			foreach (var comp in comps)
			{
				if (!comp)
					continue;
				var name = comp.GetIl2CppType().Name;
				if (onlyInteresting && IsBoringComponent(name))
					continue;
				parts.Add(name);
				if (parts.Count >= 6)
					break;
			}
			return string.Join(", ", parts);
		}
		catch
		{
			return "?";
		}
	}

	private static string DescribeGraphic(GameObject go)
	{
		var graphic = go.GetComponent<Graphic>();
		var img = go.GetComponent<Image>();
		var raw = go.GetComponent<RawImage>();
		var tmp = go.GetComponent<TMP_Text>();
		if (img)
			return "Image sprite=" + NameOf(img.sprite) + " raycastTarget=" + img.raycastTarget + " color=" + ColorText(img.color);
		if (raw)
			return "RawImage texture=" + NameOf(raw.texture) + " raycastTarget=" + raw.raycastTarget + " color=" + ColorText(raw.color);
		if (tmp)
			return "TMP text=\"" + Trim(tmp.text, 80) + "\" raycastTarget=" + tmp.raycastTarget;
		return graphic ? graphic.GetIl2CppType().Name + " raycastTarget=" + graphic.raycastTarget : ComponentSummary(go, onlyInteresting: false);
	}

	private static bool IsBoringComponent(string name)
	{
		return string.Equals(name, "RectTransform", StringComparison.Ordinal)
			|| string.Equals(name, "CanvasRenderer", StringComparison.Ordinal)
			|| string.Equals(name, "Image", StringComparison.Ordinal)
			|| string.Equals(name, "RawImage", StringComparison.Ordinal)
			|| string.Equals(name, "TextMeshProUGUI", StringComparison.Ordinal)
			|| string.Equals(name, "Text", StringComparison.Ordinal);
	}

	private static Rect ToGuiRect(RectTransform rt)
	{
		var corners = new Il2CppStructArray<Vector3>(4);
		rt.GetWorldCorners(corners);
		var minX = float.MaxValue;
		var minY = float.MaxValue;
		var maxX = float.MinValue;
		var maxY = float.MinValue;
		for (var i = 0; i < 4; i++)
		{
			var p = RectTransformUtility.WorldToScreenPoint(null, corners[i]);
			minX = Mathf.Min(minX, p.x);
			maxX = Mathf.Max(maxX, p.x);
			minY = Mathf.Min(minY, p.y);
			maxY = Mathf.Max(maxY, p.y);
		}
		return new Rect(minX, Screen.height - maxY, maxX - minX, maxY - minY);
	}

	private static void DrawPanel(TargetInfo target)
	{
		var scale = UiScale();
		var margin = Mathf.Round(12f * scale);
		var inner = Mathf.Round(10f * scale);
		var width = Mathf.Min(620f * scale, Screen.width - margin * 2f);
		var height = Mathf.Min(520f * scale, Screen.height - margin * 2f);
		var text = target.GameObject ? target.Report : "F8 close | no UI target under cursor";
		GUI.Box(new Rect(margin, margin, width, height), GUIContent.none, s_panelStyle);
		GUI.Label(
			new Rect(margin + inner, margin + inner * 0.8f, width - inner * 2f, height - inner * 1.6f),
			text,
			text.Length > 1800 ? s_smallStyle : s_labelStyle);
	}

	private static void DrawBorder(Rect rect, Color color)
	{
		if (rect.width <= 0f || rect.height <= 0f)
			return;
		var t = Mathf.Clamp(2f * UiScale(), 1f, 5f);
		var old = GUI.color;
		GUI.color = color;
		GUI.DrawTexture(new Rect(rect.x, rect.y, rect.width, t), s_borderTexture);
		GUI.DrawTexture(new Rect(rect.x, rect.yMax - t, rect.width, t), s_borderTexture);
		GUI.DrawTexture(new Rect(rect.x, rect.y, t, rect.height), s_borderTexture);
		GUI.DrawTexture(new Rect(rect.xMax - t, rect.y, t, rect.height), s_borderTexture);
		GUI.color = old;
	}

	private static void LogCurrent()
	{
		var target = s_hasPinned ? s_pinned : s_hover;
		if (!target.GameObject)
		{
			Plugin.LogSource?.LogInfo(GrepKey + " no target");
			return;
		}
		Plugin.LogSource?.LogInfo(GrepKey + " pinned=" + s_hasPinned + "\n" + target.Report);
	}

	private static string GetPath(Transform t)
	{
		if (!t)
			return "?";
		var stack = new Stack<string>();
		for (var cur = t; cur != null; cur = cur.parent)
			stack.Push(cur.name);
		return string.Join("/", stack);
	}

	private static string EnabledState(Component comp)
	{
		if (comp is Behaviour b)
			return b.enabled.ToString();
		if (comp is Renderer r)
			return r.enabled.ToString();
		return "n/a";
	}

	private static string NameOf(UnityObject obj)
	{
		return obj ? obj.name : "<null>";
	}

	private static string Trim(string text, int max)
	{
		if (string.IsNullOrEmpty(text))
			return "";
		text = text.Replace('\r', ' ').Replace('\n', ' ');
		if (text.Length <= max)
			return text;
		return text.Substring(0, max - 3) + "...";
	}

	private static string F(float value)
	{
		return value.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture);
	}

	private static string V2(Vector2 value)
	{
		return "(" + F(value.x) + "," + F(value.y) + ")";
	}

	private static string ColorText(Color color)
	{
		return "(" + F(color.r) + "," + F(color.g) + "," + F(color.b) + "," + F(color.a) + ")";
	}

	private static float UiScale()
	{
		return Mathf.Clamp(Screen.height / 1080f, 0.65f, 2.25f);
	}
}
