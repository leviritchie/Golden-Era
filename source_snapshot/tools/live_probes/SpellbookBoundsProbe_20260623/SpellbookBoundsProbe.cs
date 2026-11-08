using System;
using System.Globalization;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public static class SpellbookBoundsProbe
{
    public static string Run()
    {
        var root = GameObject.Find("SpellBook");
        if (root == null)
            return "{\"ok\":false,\"error\":\"SpellBook GameObject not found\"}";
        var b = new StringBuilder(64 * 1024);
        b.Append('{');
        Field(b, "ok", true).Append(',');
        b.Append("\"screen\":{"); Field(b, "width", Screen.width).Append(','); Field(b, "height", Screen.height); b.Append("},");
        b.Append("\"cameras\":["); AppendCameras(b); b.Append("],");
        b.Append("\"rects\":[");
        var paths = new[] {
            "SpellBook", "SpellBook/Root", "SpellBook/Root/MAGIC BOOK", "SpellBook/Root/MAGIC BOOK/Spread A", "SpellBook/Root/MAGIC BOOK/Spread A/MagicBook", "SpellBook/Root/MAGIC BOOK/Spread A/MagicBook/SPELL ROWS",
            "SpellBook/Root/MAGIC BOOK/Spread B", "SpellBook/Root/MAGIC BOOK/Spread B/MagicBook", "SpellBook/Root/MAGIC BOOK/Spread B/MagicBook/SPELL ROWS", "SpellBook/Root/ManaCanvas" };
        var rects = root.GetComponentsInChildren<RectTransform>(true);
        var emitted = 0;
        for (var i = 0; i < paths.Length; i++)
        {
            var rt = FindPath(rects, paths[i]);
            if (rt == null) continue;
            if (emitted++ > 0) b.Append(',');
            AppendRect(b, rt);
        }
        b.Append("],\"renderers\":["); AppendRenderers(b, root); b.Append("],");
        b.Append("\"components\":["); AppendComponentSummary(b, root); b.Append(']');
        b.Append('}');
        return b.ToString();
    }

    private static RectTransform FindPath(RectTransform[] rects, string path)
    {
        for (var i = 0; i < rects.Length; i++)
            if (rects[i] != null && string.Equals(PathOf(rects[i]), path, StringComparison.Ordinal))
                return rects[i];
        return null;
    }

    private static void AppendRect(StringBuilder b, RectTransform rt)
    {
        b.Append('{');
        Text(b, "path", PathOf(rt)).Append(',');
        Field(b, "activeSelf", rt.gameObject.activeSelf).Append(',');
        Field(b, "activeInHierarchy", rt.gameObject.activeInHierarchy).Append(',');
        Vec2(b, "sizeDelta", rt.sizeDelta).Append(',');
        RectVal(b, "rect", rt.rect).Append(',');
        Vec2(b, "anchoredPosition", rt.anchoredPosition).Append(',');
        Vec3(b, "localScale", rt.localScale).Append(',');
        Vec3(b, "lossyScale", rt.lossyScale).Append(',');
        Vec3(b, "worldPosition", rt.position).Append(',');
        b.Append("\"screenRect\":"); AppendRectScreenBounds(b, rt);
        var cg = rt.GetComponent<CanvasGroup>();
        if (cg != null) { b.Append(",\"canvasGroup\":{"); Field(b, "alpha", cg.alpha).Append(','); Field(b, "interactable", cg.interactable).Append(','); Field(b, "blocksRaycasts", cg.blocksRaycasts); b.Append('}'); }
        var canvas = rt.GetComponent<Canvas>();
        if (canvas != null) { b.Append(",\"canvas\":{"); Text(b, "renderMode", canvas.renderMode.ToString()).Append(','); Field(b, "scaleFactor", canvas.scaleFactor).Append(','); Field(b, "sortingOrder", canvas.sortingOrder); b.Append('}'); }
        var scaler = rt.GetComponent<CanvasScaler>();
        if (scaler != null) { b.Append(",\"canvasScaler\":{"); Text(b, "uiScaleMode", scaler.uiScaleMode.ToString()).Append(','); Vec2(b, "referenceResolution", scaler.referenceResolution).Append(','); Field(b, "scaleFactor", scaler.scaleFactor); b.Append('}'); }
        b.Append('}');
    }

    private static void AppendCameras(StringBuilder b)
    {
        var cameras = Camera.allCameras;
        var emitted = 0;
        for (var i = 0; i < cameras.Length; i++)
        {
            var cam = cameras[i]; if (cam == null) continue;
            if (emitted++ > 0) b.Append(',');
            b.Append('{'); Text(b, "name", cam.name).Append(','); Text(b, "path", PathOf(cam.transform)).Append(','); Field(b, "enabled", cam.enabled).Append(','); Field(b, "depth", cam.depth).Append(','); Field(b, "orthographic", cam.orthographic).Append(','); Field(b, "orthographicSize", cam.orthographicSize).Append(','); Field(b, "fieldOfView", cam.fieldOfView).Append(','); RectVal(b, "pixelRect", cam.pixelRect); b.Append('}');
        }
    }

    private static void AppendRenderers(StringBuilder b, GameObject root)
    {
        var renderers = root.GetComponentsInChildren<Renderer>(true);
        var camera = Camera.main; if (camera == null && Camera.allCameras.Length > 0) camera = Camera.allCameras[0];
        var emitted = 0;
        for (var i = 0; i < renderers.Length; i++)
        {
            var r = renderers[i]; if (r == null) continue;
            if (emitted++ > 0) b.Append(',');
            b.Append('{'); Text(b, "path", PathOf(r.transform)).Append(','); Field(b, "enabled", r.enabled).Append(','); Field(b, "activeInHierarchy", r.gameObject.activeInHierarchy).Append(','); BoundsVal(b, "bounds", r.bounds);
            if (camera != null) { b.Append(",\"screenRect\":"); AppendBoundsScreenRect(b, r.bounds, camera); }
            b.Append('}');
        }
    }

    private static void AppendComponentSummary(StringBuilder b, GameObject root)
    {
        var comps = root.GetComponentsInChildren<Component>(true);
        var emitted = 0;
        for (var i = 0; i < comps.Length; i++)
        {
            var c = comps[i]; if (c == null) continue;
            var name = c.GetType().Name;
            if (name.IndexOf("Book", StringComparison.OrdinalIgnoreCase) < 0 && name.IndexOf("Magic", StringComparison.OrdinalIgnoreCase) < 0) continue;
            if (emitted++ > 0) b.Append(',');
            b.Append('{'); Text(b, "type", c.GetType().FullName).Append(','); Text(b, "path", PathOf(c.transform)); b.Append('}');
        }
    }

    private static void AppendRectScreenBounds(StringBuilder b, RectTransform rt)
    {
        var corners = new Vector3[4]; rt.GetWorldCorners(corners);
        var cam = ResolveRectCamera(rt);
        AppendScreenBounds(b, corners, cam);
    }

    private static Camera ResolveRectCamera(RectTransform rt)
    {
        var canvas = rt.GetComponentInParent<Canvas>();
        if (canvas != null && canvas.renderMode != RenderMode.ScreenSpaceOverlay)
            return canvas.worldCamera != null ? canvas.worldCamera : Camera.main;
        return null;
    }

    private static void AppendBoundsScreenRect(StringBuilder b, Bounds bounds, Camera cam)
    {
        var pts = new Vector3[8]; var n = 0;
        for (var ix = -1; ix <= 1; ix += 2) for (var iy = -1; iy <= 1; iy += 2) for (var iz = -1; iz <= 1; iz += 2)
            pts[n++] = bounds.center + Vector3.Scale(bounds.extents, new Vector3(ix, iy, iz));
        AppendScreenBounds(b, pts, cam);
    }

    private static void AppendScreenBounds(StringBuilder b, Vector3[] points, Camera cam)
    {
        var minX = float.PositiveInfinity; var minY = float.PositiveInfinity; var maxX = float.NegativeInfinity; var maxY = float.NegativeInfinity;
        for (var i = 0; i < points.Length; i++)
        {
            var p = cam != null ? cam.WorldToScreenPoint(points[i]) : points[i];
            minX = Mathf.Min(minX, p.x); minY = Mathf.Min(minY, p.y); maxX = Mathf.Max(maxX, p.x); maxY = Mathf.Max(maxY, p.y);
        }
        b.Append('{'); Field(b, "x", minX).Append(','); Field(b, "y", minY).Append(','); Field(b, "width", maxX - minX).Append(','); Field(b, "height", maxY - minY); b.Append('}');
    }

    private static string PathOf(Transform t)
    {
        if (t == null) return null; var names = new string[128]; var count = 0; var cur = t;
        while (cur != null && count < names.Length) { names[count++] = cur.name; cur = cur.parent; }
        var b = new StringBuilder(); for (var i = count - 1; i >= 0; i--) { if (b.Length > 0) b.Append('/'); b.Append(names[i]); } return b.ToString();
    }

    private static StringBuilder Text(StringBuilder b, string name, string value) { b.Append('"').Append(name).Append("\":"); if (value == null) return b.Append("null"); b.Append('"'); foreach (var ch in value) { if (ch == '\\') b.Append("\\\\"); else if (ch == '"') b.Append("\\\""); else if (ch == '\r') b.Append("\\r"); else if (ch == '\n') b.Append("\\n"); else if (ch == '\t') b.Append("\\t"); else b.Append(ch); } return b.Append('"'); }
    private static StringBuilder Field(StringBuilder b, string name, bool value) { b.Append('"').Append(name).Append("\":").Append(value ? "true" : "false"); return b; }
    private static StringBuilder Field(StringBuilder b, string name, int value) { b.Append('"').Append(name).Append("\":").Append(value.ToString(CultureInfo.InvariantCulture)); return b; }
    private static StringBuilder Field(StringBuilder b, string name, float value) { b.Append('"').Append(name).Append("\":").Append(value.ToString("R", CultureInfo.InvariantCulture)); return b; }
    private static StringBuilder Vec2(StringBuilder b, string name, Vector2 v) { b.Append('"').Append(name).Append("\":{"); Field(b, "x", v.x).Append(','); Field(b, "y", v.y); return b.Append('}'); }
    private static StringBuilder Vec3(StringBuilder b, string name, Vector3 v) { b.Append('"').Append(name).Append("\":{"); Field(b, "x", v.x).Append(','); Field(b, "y", v.y).Append(','); Field(b, "z", v.z); return b.Append('}'); }
    private static StringBuilder RectVal(StringBuilder b, string name, Rect r) { b.Append('"').Append(name).Append("\":{"); Field(b, "x", r.x).Append(','); Field(b, "y", r.y).Append(','); Field(b, "width", r.width).Append(','); Field(b, "height", r.height); return b.Append('}'); }
    private static StringBuilder BoundsVal(StringBuilder b, string name, Bounds v) { b.Append('"').Append(name).Append("\":{"); Vec3(b, "center", v.center).Append(','); Vec3(b, "size", v.size).Append(','); Vec3(b, "extents", v.extents); return b.Append('}'); }
}
