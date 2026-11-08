using System;
using System.Collections;
using System.Reflection;
using System.Text;

public static class AvengerUiTextProbe
{
    public static string Run()
    {
        return Run(null);
    }

    public static string Run(string requestJson)
    {
        try
        {
            var objectType = FindType("UnityEngine.Object");
            if (objectType == null)
                return "{\"ok\":false,\"error\":\"UnityEngine.Object type not found\"}";

            var findObjects = ResolveGenericFindObjectsOfType(objectType);
            if (findObjects == null)
                return "{\"ok\":false,\"error\":\"UnityEngine.Object.FindObjectsOfType<T>() not found\"}";

            var typeNames = new[] { "TMPro.TextMeshProUGUI", "TMPro.TextMeshPro", "UnityEngine.UI.Text" };
            var scanned = 0;
            var matches = 0;
            var entries = new StringBuilder();
            entries.Append('[');

            foreach (var typeName in typeNames)
            {
                var textType = FindType(typeName);
                if (textType == null)
                    continue;
                var components = findObjects.MakeGenericMethod(textType).Invoke(null, null) as IEnumerable;
                if (components == null)
                    continue;
                foreach (var component in components)
                {
                    scanned++;
                    var text = ReadStringProperty(component, "text");
                    if (text == null || text.IndexOf("Avenger", StringComparison.OrdinalIgnoreCase) < 0)
                        continue;
                    if (matches > 0)
                        entries.Append(',');
                    var gameObject = ReadProperty(component, "gameObject");
                    entries.Append('{');
                    entries.Append("\"componentType\":").Append(Json(component.GetType().FullName)).Append(',');
                    entries.Append("\"activeInHierarchy\":").Append(ReadBoolProperty(gameObject, "activeInHierarchy", false) ? "true" : "false").Append(',');
                    entries.Append("\"gameObjectName\":").Append(Json(ReadStringProperty(gameObject, "name"))).Append(',');
                    entries.Append("\"path\":").Append(Json(BuildPath(ReadProperty(gameObject, "transform")))).Append(',');
                    entries.Append("\"text\":").Append(Json(text));
                    entries.Append('}');
                    matches++;
                }
            }

            entries.Append(']');
            return "{"
                + "\"ok\":true,"
                + "\"proof\":\"active Unity UI text components containing Avenger\","
                + "\"scannedTextComponents\":" + scanned + ","
                + "\"matches\":" + matches + ","
                + "\"items\":" + entries
                + "}";
        }
        catch (TargetInvocationException ex)
        {
            return "{\"ok\":false,\"error\":\"target invocation failed\",\"exception\":" + Json(ex.InnerException?.GetType().FullName) + ",\"message\":" + Json(ex.InnerException?.Message) + "}";
        }
        catch (Exception ex)
        {
            return "{\"ok\":false,\"error\":\"probe failed\",\"exception\":" + Json(ex.GetType().FullName) + ",\"message\":" + Json(ex.Message) + "}";
        }
    }

    private static MethodInfo ResolveGenericFindObjectsOfType(Type objectType)
    {
        foreach (var method in objectType.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
        {
            if (!string.Equals(method.Name, "FindObjectsOfType", StringComparison.Ordinal))
                continue;
            if (!method.IsGenericMethodDefinition)
                continue;
            if (method.GetGenericArguments().Length != 1)
                continue;
            if (method.GetParameters().Length == 0)
                return method;
        }
        return null;
    }

    private static Type FindType(string fullName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            var type = assembly.GetType(fullName, throwOnError: false);
            if (type != null)
                return type;
        }
        return null;
    }

    private static string BuildPath(object transform)
    {
        if (transform == null)
            return null;
        var names = new string[96];
        var count = 0;
        var current = transform;
        while (current != null && count < names.Length)
        {
            names[count++] = ReadStringProperty(current, "name") ?? "<unnamed>";
            current = ReadProperty(current, "parent");
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

    private static object ReadProperty(object value, string name)
    {
        if (value == null)
            return null;
        var property = value.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        return property?.GetValue(value, null);
    }

    private static string ReadStringProperty(object value, string name)
    {
        return ReadProperty(value, name) as string;
    }

    private static bool ReadBoolProperty(object value, string name, bool fallback)
    {
        var raw = ReadProperty(value, name);
        return raw is bool boolean ? boolean : fallback;
    }

    private static string Json(string value)
    {
        if (value == null)
            return "null";
        var builder = new StringBuilder(value.Length + 2);
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
        builder.Append('"');
        return builder.ToString();
    }
}

