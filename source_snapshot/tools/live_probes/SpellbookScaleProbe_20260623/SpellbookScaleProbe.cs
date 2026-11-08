using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public static class SpellbookScaleProbe
{
    public static string Run()
    {
        var root = GameObject.Find("SpellBook");
        if (root == null)
            return "{\"ok\":false,\"error\":\"SpellBook GameObject not found\"}";

        var rects = root.GetComponentsInChildren<RectTransform>(true);
        var builder = new StringBuilder(64 * 1024);
        builder.Append('{');
        builder.Append("\"ok\":true,");
        builder.Append("\"screen\":{");
        Field(builder, "width", Screen.width).Append(',');
        Field(builder, "height", Screen.height);
        builder.Append("},");
        builder.Append("\"root\":");
        AppendTransform(builder, root.transform);
        builder.Append(',');
        builder.Append("\"items\":[");

        var emitted = 0;
        for (var i = 0; i < rects.Length; i++)
        {
            var rect = rects[i];
            if (rect == null)
                continue;
            var path = PathOf(rect);
            if (!ShouldKeep(path))
                continue;
            if (emitted > 0)
                builder.Append(',');
            AppendRect(builder, rect, path);
            emitted++;
        }

        builder.Append("],");
        Field(builder, "matchedRectCount", emitted).Append(',');
        Field(builder, "totalSpellBookRectCount", rects.Length);
        builder.Append('}');
        return builder.ToString();
    }

    private static bool ShouldKeep(string path)
    {
        if (string.IsNullOrEmpty(path))
            return false;
        if (path == "SpellBook/Root/MAGIC BOOK" ||
            path == "SpellBook/Root/ManaCanvas" ||
            path == "SpellBook/Root/MAGIC BOOK/Spread A" ||
            path == "SpellBook/Root/MAGIC BOOK/Spread B" ||
            path == "SpellBook/Root/MAGIC BOOK/Spread A/MagicBook" ||
            path == "SpellBook/Root/MAGIC BOOK/Spread B/MagicBook" ||
            path == "SpellBook/Root/MAGIC BOOK/Spread A/MagicBook/SPELL ROWS" ||
            path == "SpellBook/Root/MAGIC BOOK/Spread B/MagicBook/SPELL ROWS")
            return true;
        return path.IndexOf("/SPELL ROWS/ROW ", StringComparison.Ordinal) >= 0 &&
            (path.EndsWith("/SPELL", StringComparison.Ordinal) ||
             path.EndsWith("/SPELL (2)", StringComparison.Ordinal) ||
             path.EndsWith("/SPELL (3)", StringComparison.Ordinal) ||
             path.EndsWith("/SPELL (4)", StringComparison.Ordinal) ||
             path.EndsWith("/SPELL (5)", StringComparison.Ordinal) ||
             path.EndsWith("/SPELL (6)", StringComparison.Ordinal) ||
             path.EndsWith("/SPELL (7)", StringComparison.Ordinal) ||
             path.EndsWith("/GameObject", StringComparison.Ordinal) ||
             path.EndsWith("/Image (1)", StringComparison.Ordinal) ||
             path.EndsWith("/hud-label-numbers", StringComparison.Ordinal) ||
             path.EndsWith("/MANA", StringComparison.Ordinal));
    }

    private static void AppendRect(StringBuilder builder, RectTransform rect, string path)
    {
        builder.Append('{');
        Text(builder, "path", path).Append(',');
        Text(builder, "name", rect.name).Append(',');
        Field(builder, "activeSelf", rect.gameObject.activeSelf).Append(',');
        Field(builder, "activeInHierarchy", rect.gameObject.activeInHierarchy).Append(',');
        Vec2(builder, "anchoredPosition", rect.anchoredPosition).Append(',');
        Vec2(builder, "sizeDelta", rect.sizeDelta).Append(',');
        Vec2(builder, "anchorMin", rect.anchorMin).Append(',');
        Vec2(builder, "anchorMax", rect.anchorMax).Append(',');
        Vec2(builder, "pivot", rect.pivot).Append(',');
        Rect(builder, "rect", rect.rect).Append(',');
        Vec3(builder, "localScale", rect.localScale).Append(',');
        Vec3(builder, "lossyScale", rect.lossyScale).Append(',');
        Vec3(builder, "localPosition", rect.localPosition).Append(',');
        Vec3(builder, "worldPosition", rect.position);

        var canvas = rect.GetComponent<Canvas>();
        if (canvas != null)
        {
            builder.Append(',');
            AppendCanvas(builder, canvas);
        }

        var scaler = rect.GetComponent<CanvasScaler>();
        if (scaler != null)
        {
            builder.Append(',');
            AppendCanvasScaler(builder, scaler);
        }

        var image = rect.GetComponent<Image>();
        if (image != null)
        {
            builder.Append(',');
            AppendImage(builder, image);
        }

        var text = rect.GetComponent<TMP_Text>();
        if (text != null)
        {
            builder.Append(',');
            AppendText(builder, text);
        }

        builder.Append('}');
    }

    private static void AppendTransform(StringBuilder builder, Transform transform)
    {
        builder.Append('{');
        Text(builder, "path", PathOf(transform)).Append(',');
        Vec3(builder, "localScale", transform.localScale).Append(',');
        Vec3(builder, "lossyScale", transform.lossyScale).Append(',');
        Vec3(builder, "localPosition", transform.localPosition).Append(',');
        Vec3(builder, "worldPosition", transform.position);
        builder.Append('}');
    }

    private static void AppendCanvas(StringBuilder builder, Canvas canvas)
    {
        builder.Append("\"canvas\":{");
        Text(builder, "renderMode", canvas.renderMode.ToString()).Append(',');
        Field(builder, "scaleFactor", canvas.scaleFactor).Append(',');
        Field(builder, "referencePixelsPerUnit", canvas.referencePixelsPerUnit).Append(',');
        Field(builder, "overrideSorting", canvas.overrideSorting).Append(',');
        Field(builder, "sortingOrder", canvas.sortingOrder);
        builder.Append('}');
    }

    private static void AppendCanvasScaler(StringBuilder builder, CanvasScaler scaler)
    {
        builder.Append("\"canvasScaler\":{");
        Text(builder, "uiScaleMode", scaler.uiScaleMode.ToString()).Append(',');
        Vec2(builder, "referenceResolution", scaler.referenceResolution).Append(',');
        Text(builder, "screenMatchMode", scaler.screenMatchMode.ToString()).Append(',');
        Field(builder, "matchWidthOrHeight", scaler.matchWidthOrHeight).Append(',');
        Field(builder, "scaleFactor", scaler.scaleFactor).Append(',');
        Field(builder, "referencePixelsPerUnit", scaler.referencePixelsPerUnit);
        builder.Append('}');
    }

    private static void AppendImage(StringBuilder builder, Image image)
    {
        builder.Append("\"image\":{");
        Field(builder, "enabled", image.enabled).Append(',');
        Text(builder, "sprite", image.sprite != null ? image.sprite.name : null);
        if (image.sprite != null)
        {
            builder.Append(',');
            Rect(builder, "spriteRect", image.sprite.rect);
            if (image.sprite.texture != null)
            {
                builder.Append(',');
                Field(builder, "textureWidth", image.sprite.texture.width).Append(',');
                Field(builder, "textureHeight", image.sprite.texture.height);
            }
        }
        builder.Append('}');
    }

    private static void AppendText(StringBuilder builder, TMP_Text text)
    {
        builder.Append("\"text\":{");
        Field(builder, "enabled", text.enabled).Append(',');
        Field(builder, "fontSize", text.fontSize).Append(',');
        Field(builder, "fontSizeMin", text.fontSizeMin).Append(',');
        Field(builder, "fontSizeMax", text.fontSizeMax).Append(',');
        Field(builder, "enableAutoSizing", text.enableAutoSizing).Append(',');
        Text(builder, "value", text.text);
        builder.Append('}');
    }

    private static string PathOf(Transform transform)
    {
        if (transform == null)
            return null;
        var names = new string[96];
        var count = 0;
        var current = transform;
        while (current != null && count < names.Length)
        {
            names[count++] = current.name;
            current = current.parent;
        }
        var builder = new StringBuilder();
        for (var i = count - 1; i >= 0; i--)
        {
            if (builder.Length > 0)
                builder.Append('/');
            builder.Append(names[i]);
        }
        return builder.ToString();
    }

    private static StringBuilder Text(StringBuilder builder, string name, string value)
    {
        builder.Append('"').Append(name).Append("\":");
        if (value == null)
            return builder.Append("null");
        builder.Append('"');
        foreach (var ch in value)
        {
            switch (ch)
            {
                case '\\': builder.Append("\\\\"); break;
                case '"': builder.Append("\\\""); break;
                case '\r': builder.Append("\\r"); break;
                case '\n': builder.Append("\\n"); break;
                case '\t': builder.Append("\\t"); break;
                default:
                    if (ch < ' ')
                        builder.Append("\\u").Append(((int)ch).ToString("x4"));
                    else
                        builder.Append(ch);
                    break;
            }
        }
        return builder.Append('"');
    }

    private static StringBuilder Field(StringBuilder builder, string name, bool value)
    {
        builder.Append('"').Append(name).Append("\":").Append(value ? "true" : "false");
        return builder;
    }

    private static StringBuilder Field(StringBuilder builder, string name, int value)
    {
        builder.Append('"').Append(name).Append("\":").Append(value.ToString(CultureInfo.InvariantCulture));
        return builder;
    }

    private static StringBuilder Field(StringBuilder builder, string name, float value)
    {
        builder.Append('"').Append(name).Append("\":").Append(value.ToString("R", CultureInfo.InvariantCulture));
        return builder;
    }

    private static StringBuilder Vec2(StringBuilder builder, string name, Vector2 value)
    {
        builder.Append('"').Append(name).Append("\":{");
        Field(builder, "x", value.x).Append(',');
        Field(builder, "y", value.y);
        return builder.Append('}');
    }

    private static StringBuilder Vec3(StringBuilder builder, string name, Vector3 value)
    {
        builder.Append('"').Append(name).Append("\":{");
        Field(builder, "x", value.x).Append(',');
        Field(builder, "y", value.y).Append(',');
        Field(builder, "z", value.z);
        return builder.Append('}');
    }

    private static StringBuilder Rect(StringBuilder builder, string name, Rect value)
    {
        builder.Append('"').Append(name).Append("\":{");
        Field(builder, "x", value.x).Append(',');
        Field(builder, "y", value.y).Append(',');
        Field(builder, "width", value.width).Append(',');
        Field(builder, "height", value.height);
        return builder.Append('}');
    }
}
