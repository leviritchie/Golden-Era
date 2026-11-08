using System;
using System.Collections;
using System.Reflection;
using System.Text;

public static class BattleRosterProbe
{
    private static readonly string[] UnitLogicMembers =
    {
        "Method_Public_get_UnitLogicConfig_0", "chgu", "bewi", "<chgu>k__BackingField", "_chgu_k__BackingField",
        "chfz", "bevj", "<chfz>k__BackingField", "_chfz_k__BackingField", "chjp", "<chjp>k__BackingField",
        "_chjp_k__BackingField", "chez", "chbv", "cgha", "beye"
    };

    private static readonly string[] UnitDataMembers =
    {
        "Method_Public_get_UnitData_0", "<chjr>k__BackingField", "chjr", "beyi", "chgw", "bewm", "chfb", "chgb"
    };

    private static readonly string[] SidMembers =
    {
        "configSid", "sid", "id", "unitSid", "baseSid", "upgradeSid", "cngz", "scs", "cnhd", "sef", "get_configSid", "get_configId", "GetConfigId"
    };

    private static readonly string[] FactionMembers = { "fraction", "faction", "get_fraction", "get_faction" };
    private static readonly string[] TierMembers = { "tier", "get_tier" };
    private static readonly string[] StackMembers = { "count", "stackCount", "amount", "currentCount", "get_count", "get_stackCount" };

    public static string Run()
    {
        try
        {
            var mod = FindAssembly("OfflineUnlockMod");
            if (mod == null)
                return "{\"ok\":false,\"error\":\"OfflineUnlockMod assembly not loaded\"}";
            var registryType = mod.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry", false) ?? mod.GetType("Homm3BattleUnitLawOwnerRegistry", false);
            var unitMapField = registryType?.GetField("UnitKeyToUnit", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            var units = unitMapField?.GetValue(null) as IEnumerable;
            if (units == null)
                return "{\"ok\":false,\"error\":\"UnitKeyToUnit unavailable\"}";

            var total = 0;
            var unitCount = 0;
            var entries = new StringBuilder();
            entries.Append('[');
            foreach (var pair in units)
            {
                total++;
                var unit = ReadMember(pair, "Value");
                if (unit == null || unit.GetType().FullName != "Hex.Session.Battle.Unit")
                    continue;
                var key = ReadIntMember(pair, "Key", -1);
                var logic = ReadFirstMember(unit, UnitLogicMembers);
                var data = ReadFirstMember(unit, UnitDataMembers);
                if (unitCount > 0)
                    entries.Append(',');
                entries.Append('{');
                entries.Append("\"unitKey\":").Append(key).Append(',');
                entries.Append("\"unitType\":").Append(Json(unit.GetType().FullName)).Append(',');
                entries.Append("\"logicType\":").Append(Json(logic?.GetType().FullName)).Append(',');
                entries.Append("\"configSid\":").Append(Json(ReadStringish(ReadFirstMember(logic, SidMembers)))).Append(',');
                entries.Append("\"faction\":").Append(Json(ReadStringish(ReadFirstMember(logic, FactionMembers)))).Append(',');
                entries.Append("\"tier\":").Append(Json(ReadStringish(ReadFirstMember(logic, TierMembers)))).Append(',');
                entries.Append("\"dataType\":").Append(Json(data?.GetType().FullName)).Append(',');
                entries.Append("\"stack\":").Append(Json(ReadStringish(ReadFirstMember(data, StackMembers))));
                entries.Append('}');
                unitCount++;
                if (unitCount >= 160)
                    break;
            }
            entries.Append(']');
            return "{\"ok\":true,\"totalRegistryEntries\":" + total + ",\"battleUnitsReturned\":" + unitCount + ",\"units\":" + entries + "}";
        }
        catch (Exception ex)
        {
            return "{\"ok\":false,\"error\":\"probe failed\",\"exception\":" + Json(ex.GetType().FullName) + ",\"message\":" + Json(ex.Message) + "}";
        }
    }

    private static Assembly FindAssembly(string simpleName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            if (string.Equals(assembly.GetName().Name, simpleName, StringComparison.Ordinal))
                return assembly;
        return null;
    }

    private static object ReadFirstMember(object value, string[] names)
    {
        if (value == null || names == null)
            return null;
        foreach (var name in names)
        {
            var result = ReadMember(value, name);
            if (result != null)
                return result;
        }
        return null;
    }

    private static object ReadMember(object value, string name)
    {
        if (value == null || string.IsNullOrWhiteSpace(name))
            return null;
        var type = value.GetType();
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        var property = type.GetProperty(name, flags);
        if (property != null && property.GetIndexParameters().Length == 0)
        {
            try { return property.GetValue(value, null); } catch { }
        }
        var field = type.GetField(name, flags);
        if (field != null)
        {
            try { return field.GetValue(value); } catch { }
        }
        var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
        if (method != null && method.ReturnType != typeof(void))
        {
            try { return method.Invoke(value, null); } catch { }
        }
        return null;
    }

    private static int ReadIntMember(object value, string name, int fallback)
    {
        var raw = ReadMember(value, name);
        return raw is int number ? number : fallback;
    }

    private static string ReadStringish(object value)
    {
        if (value == null)
            return null;
        if (value is string text)
            return text;
        return value.ToString();
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
