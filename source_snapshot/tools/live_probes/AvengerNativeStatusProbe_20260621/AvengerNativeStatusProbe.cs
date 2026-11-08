using System;
using System.Collections;
using System.Reflection;
using System.Text;

public static class AvengerNativeStatusProbe
{
    private static readonly string[] NativeAvengerSids =
    {
        "skill_faction_homm3_rampart_ability_avenger_rank_1_effect",
        "skill_faction_homm3_rampart_ability_avenger_rank_2_effect",
        "skill_faction_homm3_rampart_ability_avenger_rank_3_effect",
        "skill_faction_homm3_rampart_ability_avenger_rank_2_decay_effect",
    };

    private static readonly string[] CustomAvengerSids =
    {
        "homm3_law_marker_avenger_intensity",
    };

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

            var registryType = mod.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry", throwOnError: false)
                ?? mod.GetType("Homm3BattleUnitLawOwnerRegistry", throwOnError: false);
            var adapterType = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter", throwOnError: false)
                ?? mod.GetType("Homm3BuffDebuffNativeAdapter", throwOnError: false);
            if (registryType == null || adapterType == null)
                return "{\"ok\":false,\"error\":\"required runtime types were not found\",\"registryType\":" + Json(registryType?.FullName) + ",\"adapterType\":" + Json(adapterType?.FullName) + "}";

            var unitMapField = registryType.GetField("UnitKeyToUnit", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            var queryMethod = adapterType.GetMethod("TryQueryAnyBuffSidFromReceiver", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            if (unitMapField == null || queryMethod == null)
                return "{\"ok\":false,\"error\":\"required members were not found\",\"unitMapField\":" + Json(unitMapField?.Name) + ",\"queryMethod\":" + Json(queryMethod?.Name) + "}";

            var units = unitMapField.GetValue(null) as IEnumerable;
            if (units == null)
                return "{\"ok\":false,\"error\":\"UnitKeyToUnit did not expose an enumerable\"}";

            var scanned = 0;
            var nativeMatches = 0;
            var customMatches = 0;
            var queryFailures = 0;
            var matchEntries = new StringBuilder();
            var failureSamples = new StringBuilder();
            matchEntries.Append('[');
            failureSamples.Append('[');

            foreach (var pair in units)
            {
                scanned++;
                var unitKey = ReadIntMember(pair, "Key", -1);
                var unit = ReadMember(pair, "Value");
                var native = Query(queryMethod, unit, NativeAvengerSids);
                var custom = Query(queryMethod, unit, CustomAvengerSids);
                if (!native.QueryKnown)
                {
                    AppendFailureSample(failureSamples, queryFailures, unitKey, unit, native.FailReason);
                    queryFailures++;
                }
                if (native.HasSid)
                {
                    AppendMatch(matchEntries, nativeMatches + customMatches, unitKey, unit, "native", native.Info);
                    nativeMatches++;
                }
                if (custom.HasSid)
                {
                    AppendMatch(matchEntries, nativeMatches + customMatches, unitKey, unit, "custom", custom.Info);
                    customMatches++;
                }
            }

            matchEntries.Append(']');
            failureSamples.Append(']');
            return "{"
                + "\"ok\":true,"
                + "\"proof\":\"native Avenger SID query over all registered battle unit receivers\","
                + "\"scannedUnits\":" + scanned + ","
                + "\"nativeMatches\":" + nativeMatches + ","
                + "\"customMatches\":" + customMatches + ","
                + "\"queryFailures\":" + queryFailures + ","
                + "\"nativeSids\":" + JsonArray(NativeAvengerSids) + ","
                + "\"customSids\":" + JsonArray(CustomAvengerSids) + ","
                + "\"matches\":" + matchEntries + ","
                + "\"failureSamples\":" + failureSamples
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
        var result = queryMethod.Invoke(null, args);
        var queryKnown = result is bool value && value;
        var info = args[2];
        var failReason = args[3]?.ToString();
        var infoText = info?.ToString();
        var hasSid = ReadBoolMember(info, "HasSid", false);
        if (!hasSid && infoText != null && infoText.IndexOf("hasSid=True", StringComparison.Ordinal) >= 0)
            hasSid = true;
        return new QueryResult(queryKnown, hasSid, infoText, failReason);
    }

    private static void AppendMatch(StringBuilder builder, int index, int unitKey, object unit, string source, string info)
    {
        if (index > 0)
            builder.Append(',');
        builder.Append('{');
        builder.Append("\"unitKey\":").Append(unitKey).Append(',');
        builder.Append("\"unitType\":").Append(Json(unit?.GetType().FullName)).Append(',');
        builder.Append("\"source\":").Append(Json(source)).Append(',');
        builder.Append("\"info\":").Append(Json(info));
        builder.Append('}');
    }

    private static void AppendFailureSample(StringBuilder builder, int failureIndex, int unitKey, object unit, string failReason)
    {
        if (failureIndex >= 5)
            return;
        if (failureIndex > 0)
            builder.Append(',');
        builder.Append('{');
        builder.Append("\"unitKey\":").Append(unitKey).Append(',');
        builder.Append("\"unitType\":").Append(Json(unit?.GetType().FullName)).Append(',');
        builder.Append("\"failure\":").Append(Json(failReason));
        builder.Append('}');
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

    private static string JsonArray(string[] values)
    {
        var builder = new StringBuilder();
        builder.Append('[');
        for (var i = 0; i < values.Length; i++)
        {
            if (i > 0)
                builder.Append(',');
            builder.Append(Json(values[i]));
        }
        builder.Append(']');
        return builder.ToString();
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
                case '\\':
                    builder.Append("\\\\");
                    break;
                case '"':
                    builder.Append("\\\"");
                    break;
                case '\r':
                    builder.Append("\\r");
                    break;
                case '\n':
                    builder.Append("\\n");
                    break;
                case '\t':
                    builder.Append("\\t");
                    break;
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
