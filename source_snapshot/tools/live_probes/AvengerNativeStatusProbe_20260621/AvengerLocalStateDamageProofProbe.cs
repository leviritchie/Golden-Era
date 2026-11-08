using System;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using HarmonyLib;

public static class AvengerLocalStateDamageProofProbe
{
    private const string ExactDamageMethodName = "Method_Public_Virtual_Void_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_InterfacePublicAbstractbaBoaObVobabaObInUnique_ObjectPublicCacodaCaObceObceUnique_Int32_EMechType_Boolean_Single_Boolean_0";
    private static bool _installed;
    private static bool _mutated;
    private static int _observedDamageEvents;
    private static string _lastResult;

    public static string Run()
    {
        try
        {
            if (_installed)
                return StatusJson("already installed");

            var unitType = FindType("Hex.Session.Battle.Unit");
            if (unitType == null)
                return "{\"ok\":false,\"error\":\"Hex.Session.Battle.Unit type not found\"}";
            var damageMethod = unitType.GetMethod(ExactDamageMethodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (damageMethod == null)
                return "{\"ok\":false,\"error\":\"exact damage method not found\",\"method\":" + Json(ExactDamageMethodName) + "}";

            var prefix = typeof(AvengerLocalStateDamageProofProbe).GetMethod(nameof(PrefixDamage), BindingFlags.Static | BindingFlags.NonPublic);
            var harmony = new Harmony("codex.avenger.localstate.damageproof.20260621");
            harmony.Patch(damageMethod, prefix: new HarmonyMethod(prefix) { priority = Priority.First });
            _installed = true;
            Log("HoMM3 volatile Avenger local-state damage proof installed: method=" + damageMethod.DeclaringType.FullName + "." + damageMethod.Name + ". Next positive damage event will be locally marked and doubled once.");
            return StatusJson("installed");
        }
        catch (Exception ex)
        {
            return "{\"ok\":false,\"error\":\"install failed\",\"exception\":" + Json(ex.GetType().FullName) + ",\"message\":" + Json(ex.Message) + "}";
        }
    }

    private static void PrefixDamage(object __instance, MethodBase __originalMethod, object[] __args)
    {
        try
        {
            _observedDamageEvents++;
            if (_mutated)
                return;
            if (__instance == null || __args == null || __args.Length != 8 || !(__args[3] is int oldDamage) || oldDamage <= 0)
                return;

            var mark = TryMarkLocal(__instance);
            if (!mark.Ok)
            {
                _lastResult = "mark failed: " + mark.FailReason;
                Log("HoMM3 volatile Avenger local-state damage proof skipped: " + _lastResult + "; receiver=" + Describe(__instance) + ".");
                return;
            }
            var require = TryRequireLocal(__instance);
            if (!require.Ok)
            {
                _lastResult = "require failed: " + require.FailReason;
                Log("HoMM3 volatile Avenger local-state damage proof skipped: " + _lastResult + "; receiver=" + Describe(__instance) + ".");
                return;
            }

            var delta = Math.Max(1, oldDamage);
            var newDamage = checked(oldDamage + delta);
            __args[3] = newDamage;
            _mutated = true;
            _lastResult = "mutated receiverKey=" + RuntimeHelpers.GetHashCode(__instance)
                          + " config=" + BestConfigSid(__instance)
                          + " oldDamage=" + oldDamage
                          + " delta=" + delta
                          + " newDamage=" + newDamage
                          + " oldMarkCount=" + mark.OldCount
                          + " newMarkCount=" + mark.NewCount
                          + " requiredMarkCount=" + require.MarkCount;
            Log("HoMM3 volatile Avenger local-state damage proof applied: " + _lastResult + "; method=" + (__originalMethod?.DeclaringType?.FullName ?? "null") + "." + (__originalMethod?.Name ?? "null") + ".");
        }
        catch (Exception ex)
        {
            _lastResult = "exception: " + ex.GetType().Name + ": " + ex.Message;
            Log("HoMM3 volatile Avenger local-state damage proof failed closed: " + _lastResult + ".");
        }
    }

    public static string Status()
    {
        return StatusJson("status");
    }

    private static MarkResult TryMarkLocal(object unit)
    {
        var mod = FindAssembly("OfflineUnlockMod");
        var stateType = mod?.GetType("OfflineUnlockMod.Homm3BattleLocalLawState", false) ?? mod?.GetType("Homm3BattleLocalLawState", false);
        var method = stateType?.GetMethod("TryMarkRampartAvengerTarget", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (method == null)
            return new MarkResult(false, 0, 0, "TryMarkRampartAvengerTarget not found");
        var args = new object[] { unit, 0, 0, null, false, 99, "volatile local-state damage proof" };
        var raw = method.Invoke(null, args);
        var ok = raw is bool boolean && boolean;
        return new MarkResult(ok, args[1] is int oldCount ? oldCount : 0, args[2] is int newCount ? newCount : 0, args[3]?.ToString());
    }

    private static RequireResult TryRequireLocal(object unit)
    {
        var mod = FindAssembly("OfflineUnlockMod");
        var stateType = mod?.GetType("OfflineUnlockMod.Homm3BattleLocalLawState", false) ?? mod?.GetType("Homm3BattleLocalLawState", false);
        var method = stateType?.GetMethod("TryRequireRampartAvengerMark", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (method == null)
            return new RequireResult(false, 0, "TryRequireRampartAvengerMark not found");
        var args = new object[] { unit, 0, null };
        var raw = method.Invoke(null, args);
        var ok = raw is bool boolean && boolean;
        return new RequireResult(ok, args[1] is int markCount ? markCount : 0, args[2]?.ToString());
    }

    private static string StatusJson(string state)
    {
        return "{"
            + "\"ok\":true,"
            + "\"state\":" + Json(state) + ","
            + "\"installed\":" + (_installed ? "true" : "false") + ","
            + "\"mutated\":" + (_mutated ? "true" : "false") + ","
            + "\"observedDamageEvents\":" + _observedDamageEvents + ","
            + "\"lastResult\":" + Json(_lastResult)
            + "}";
    }

    private static Assembly FindAssembly(string simpleName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            if (string.Equals(assembly.GetName().Name, simpleName, StringComparison.Ordinal))
                return assembly;
        return null;
    }

    private static Type FindType(string fullName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            var type = assembly.GetType(fullName, false);
            if (type != null)
                return type;
        }
        return null;
    }

    private static string BestConfigSid(object unit)
    {
        var logic = ReadFirst(unit, new[] { "Method_Public_get_UnitLogicConfig_0", "chgu", "bewi", "<chgu>k__BackingField", "chfz", "bevj", "chjp", "chez", "chbv", "cgha" });
        var sid = ReadFirst(logic, new[] { "configSid", "sid", "id", "unitSid", "cngz", "scs", "cnhd", "sef", "get_configSid", "get_configId", "GetConfigId" });
        return sid?.ToString() ?? "unknown";
    }

    private static object ReadFirst(object value, string[] names)
    {
        if (value == null)
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
        var prop = type.GetProperty(name, flags);
        if (prop != null && prop.GetIndexParameters().Length == 0)
        {
            try { return prop.GetValue(value, null); } catch { }
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

    private static void Log(string message)
    {
        try
        {
            var mod = FindAssembly("OfflineUnlockMod");
            var pluginType = mod?.GetType("OfflineUnlockMod.Plugin", false) ?? mod?.GetType("Plugin", false);
            var logSource = pluginType?.GetProperty("LogSource", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null, null)
                ?? pluginType?.GetField("LogSource", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
            var logInfo = logSource?.GetType().GetMethod("LogInfo", new[] { typeof(object) });
            if (logInfo != null)
            {
                logInfo.Invoke(logSource, new object[] { message });
                return;
            }
        }
        catch { }
        Console.WriteLine(message);
    }

    private static string Describe(object value)
    {
        if (value == null)
            return "null";
        return value.GetType().FullName + "#" + RuntimeHelpers.GetHashCode(value);
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

    private readonly struct MarkResult
    {
        internal readonly bool Ok;
        internal readonly int OldCount;
        internal readonly int NewCount;
        internal readonly string FailReason;
        internal MarkResult(bool ok, int oldCount, int newCount, string failReason)
        {
            Ok = ok;
            OldCount = oldCount;
            NewCount = newCount;
            FailReason = failReason;
        }
    }

    private readonly struct RequireResult
    {
        internal readonly bool Ok;
        internal readonly int MarkCount;
        internal readonly string FailReason;
        internal RequireResult(bool ok, int markCount, string failReason)
        {
            Ok = ok;
            MarkCount = markCount;
            FailReason = failReason;
        }
    }
}
