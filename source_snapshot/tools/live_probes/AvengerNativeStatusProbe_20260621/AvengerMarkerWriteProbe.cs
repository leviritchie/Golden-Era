using System;
using System.Collections;
using System.Reflection;
using System.Text;

public static class AvengerMarkerWriteProbe
{
    private const string CustomMarkerSid = "homm3_law_marker_avenger_intensity";

    public static string Run()
    {
        return Run(null);
    }

    public static string Run(string requestJson)
    {
        try
        {
            var mod = FindAssembly("OfflineUnlockMod");
            if (mod == null)
                return "{\"ok\":false,\"error\":\"OfflineUnlockMod assembly not loaded\"}";

            var registryType = mod.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry", false)
                ?? mod.GetType("Homm3BattleUnitLawOwnerRegistry", false);
            var adapterType = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter", false)
                ?? mod.GetType("Homm3BuffDebuffNativeAdapter", false);
            if (registryType == null || adapterType == null)
                return "{\"ok\":false,\"error\":\"required runtime types were not found\"}";

            var unitMapField = registryType.GetField("UnitKeyToUnit", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            var queryMethod = adapterType.GetMethod("TryQueryAnyBuffSidFromReceiver", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            var addMethod = ResolveAddMethod(adapterType, "TryAddBuffSidFromReceiver");
            if (unitMapField == null || queryMethod == null || addMethod == null)
                return "{\"ok\":false,\"error\":\"required members were not found\",\"unitMapField\":" + Json(unitMapField?.Name) + ",\"queryMethod\":" + Json(queryMethod?.Name) + ",\"addMethod\":" + Json(addMethod?.Name) + "}";

            var units = unitMapField.GetValue(null) as IEnumerable;
            if (units == null)
                return "{\"ok\":false,\"error\":\"UnitKeyToUnit did not expose an enumerable\"}";

            var requestedKey = ParseUnitKey(requestJson);
            var scanned = 0;
            var queryable = 0;
            var targetKey = -1;
            object targetUnit = null;
            QueryResult targetBefore = default;
            foreach (var pair in units)
            {
                scanned++;
                var unitKey = ReadIntMember(pair, "Key", -1);
                var unit = ReadMember(pair, "Value");
                if (requestedKey >= 0 && unitKey != requestedKey)
                    continue;
                var before = Query(queryMethod, unit, new[] { CustomMarkerSid });
                if (!before.QueryKnown)
                    continue;
                queryable++;
                targetKey = unitKey;
                targetUnit = unit;
                targetBefore = before;
                if (requestedKey >= 0)
                    break;
            }

            if (targetUnit == null)
                return "{\"ok\":false,\"error\":\"no queryable registered battle receiver found\",\"requestedUnitKey\":" + requestedKey + ",\"scannedUnits\":" + scanned + ",\"queryableUnits\":" + queryable + "}";

            var addArgs = new object[] { targetUnit, CustomMarkerSid, targetUnit, 1, 2, 0, true, null, null };
            var addReturned = false;
            string addException = null;
            try
            {
                var raw = addMethod.Invoke(null, addArgs);
                addReturned = raw is bool boolean && boolean;
            }
            catch (TargetInvocationException ex)
            {
                addException = ex.InnerException?.GetType().FullName + ": " + ex.InnerException?.Message;
            }
            catch (Exception ex)
            {
                addException = ex.GetType().FullName + ": " + ex.Message;
            }

            var addInfo = addArgs[7]?.ToString();
            var addFailure = addArgs[8]?.ToString();
            var after = Query(queryMethod, targetUnit, new[] { CustomMarkerSid });

            return "{"
                + "\"ok\":true,"
                + "\"proof\":\"volatile native-dispatched custom Avenger marker add\","
                + "\"sid\":" + Json(CustomMarkerSid) + ","
                + "\"requestedUnitKey\":" + requestedKey + ","
                + "\"targetUnitKey\":" + targetKey + ","
                + "\"targetUnitType\":" + Json(targetUnit.GetType().FullName) + ","
                + "\"scannedUnits\":" + scanned + ","
                + "\"queryableUnits\":" + queryable + ","
                + "\"beforeQueryKnown\":" + (targetBefore.QueryKnown ? "true" : "false") + ","
                + "\"beforeHasSid\":" + (targetBefore.HasSid ? "true" : "false") + ","
                + "\"beforeInfo\":" + Json(targetBefore.Info) + ","
                + "\"beforeFailure\":" + Json(targetBefore.FailReason) + ","
                + "\"addReturned\":" + (addReturned ? "true" : "false") + ","
                + "\"addInfo\":" + Json(addInfo) + ","
                + "\"addFailure\":" + Json(addFailure) + ","
                + "\"addException\":" + Json(addException) + ","
                + "\"afterQueryKnown\":" + (after.QueryKnown ? "true" : "false") + ","
                + "\"afterHasSid\":" + (after.HasSid ? "true" : "false") + ","
                + "\"afterInfo\":" + Json(after.Info) + ","
                + "\"afterFailure\":" + Json(after.FailReason)
                + "}";
        }
        catch (Exception ex)
        {
            return "{\"ok\":false,\"error\":\"probe failed\",\"exception\":" + Json(ex.GetType().FullName) + ",\"message\":" + Json(ex.Message) + "}";
        }
    }

    private static MethodInfo ResolveAddMethod(Type adapterType, string name)
    {
        foreach (var method in adapterType.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
        {
            if (!string.Equals(method.Name, name, StringComparison.Ordinal))
                continue;
            if (method.GetParameters().Length == 9)
                return method;
        }
        return null;
    }

    private static int ParseUnitKey(string requestJson)
    {
        if (string.IsNullOrWhiteSpace(requestJson))
            return -1;
        var keyIndex = requestJson.IndexOf("unitKey", StringComparison.OrdinalIgnoreCase);
        if (keyIndex < 0)
            return -1;
        var colon = requestJson.IndexOf(':', keyIndex);
        if (colon < 0)
            return -1;
        var i = colon + 1;
        while (i < requestJson.Length && char.IsWhiteSpace(requestJson[i]))
            i++;
        var start = i;
        while (i < requestJson.Length && (char.IsDigit(requestJson[i]) || requestJson[i] == '-'))
            i++;
        if (i <= start)
            return -1;
        return int.TryParse(requestJson.Substring(start, i - start), out var value) ? value : -1;
    }

    private static Assembly FindAssembly(string simpleName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            if (string.Equals(assembly.GetName().Name, simpleName, StringComparison.Ordinal))
                return assembly;
        }
        return null;
    }

    private static QueryResult Query(MethodInfo queryMethod, object unit, string[] sids)
    {
        if (unit == null)
            return new QueryResult(false, false, null, "unit was null");
        var args = new object[] { unit, sids, null, null };
        var raw = queryMethod.Invoke(null, args);
        var queryKnown = raw is bool boolean && boolean;
        var info = args[2];
        var infoText = info?.ToString();
        var hasSid = ReadBoolMember(info, "HasSid", false);
        if (!hasSid && infoText != null && infoText.IndexOf("hasSid=True", StringComparison.Ordinal) >= 0)
            hasSid = true;
        return new QueryResult(queryKnown, hasSid, infoText, args[3]?.ToString());
    }

    private static object ReadMember(object value, string name)
    {
        if (value == null)
            return null;
        var type = value.GetType();
        var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (field != null)
            return field.GetValue(value);
        var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        return property?.GetValue(value, null);
    }

    private static int ReadIntMember(object value, string name, int fallback)
    {
        var raw = ReadMember(value, name);
        return raw is int number ? number : fallback;
    }

    private static bool ReadBoolMember(object value, string name, bool fallback)
    {
        if (value == null)
            return fallback;
        var type = value.GetType();
        var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (field != null && field.GetValue(value) is bool fieldValue)
            return fieldValue;
        var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (property != null && property.GetValue(value, null) is bool propertyValue)
            return propertyValue;
        return fallback;
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

    private readonly struct QueryResult
    {
        internal readonly bool QueryKnown;
        internal readonly bool HasSid;
        internal readonly string Info;
        internal readonly string FailReason;

        internal QueryResult(bool queryKnown, bool hasSid, string info, string failReason)
        {
            QueryKnown = queryKnown;
            HasSid = hasSid;
            Info = info;
            FailReason = failReason;
        }
    }
}
