using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726e
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var getStats = unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null);
			var before = DumpStats(getStats.Invoke(unit, null));
			var mod = FindAsm("OfflineUnlockMod");
			var adapter = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter");
			MethodInfo add = null;
			foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
			{
				if (m.Name != "TryAddBuffSidFromReceiver") continue;
				var ps = m.GetParameters();
				if (ps.Length == 9 && ps[7].ParameterType.IsByRef) { add = m; break; }
			}
			var sid = (requestJson != null && requestJson.IndexOf("custom", StringComparison.OrdinalIgnoreCase) >= 0)
				? "homm3_factory_split_assembly_speed_1"
				: "magic_haste_effect_1";
			var args = new object[] { unit, sid, unit, 1, 99, 1, true, null, null };
			var ok = add.Invoke(null, args);
			object mgr = null;
			foreach (var name in new[] { "Method_Public_Virtual_Final_New_get_ObjectPublicDi2StLi1ObceInLi1Unique_0" })
			{
				var mm = unit.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (mm != null) { mgr = mm.Invoke(unit, null); if (mgr != null) break; }
			}
			var refresh = new StringBuilder();
			if (mgr != null)
			{
				foreach (var m in mgr.GetType().GetMethods(flags))
				{
					var ps = m.GetParameters();
					if (ps.Length != 1 || !ps[0].ParameterType.IsInstanceOfType(unit) || m.ReturnType != typeof(void)) continue;
					if (!m.Name.StartsWith("Method_Public_Void_Unit", StringComparison.Ordinal)) continue;
					try { m.Invoke(mgr, new object[] { unit }); refresh.Append(m.Name).Append("(ok);"); }
					catch { refresh.Append(m.Name).Append("(ERR);"); }
				}
			}
			var after = DumpStats(getStats.Invoke(unit, null));
			var changed = new StringBuilder();
			var first = true;
			foreach (var kv in after)
			{
				before.TryGetValue(kv.Key, out var prev);
				if (prev == kv.Value) continue;
				if (!first) changed.Append(',');
				first = false;
				changed.Append('"').Append(kv.Key).Append("\":\"").Append(prev ?? "null").Append("->").Append(kv.Value).Append('"');
			}
			var addOk = ok is bool addBool && addBool;
			return "{"
				+ "\"ok\":true"
				+ ",\"sid\":\"" + sid + "\""
				+ ",\"add\":" + (addOk ? "true" : "false")
				+ ",\"addFail\":\"" + (args[8] ?? "").ToString().Replace("\"", "'") + "\""
				+ ",\"refresh\":\"" + refresh.ToString().Replace("\"", "'") + "\""
				+ ",\"beforeSpeed\":" + (before.ContainsKey("get_speed") ? before["get_speed"] : "null")
				+ ",\"afterSpeed\":" + (after.ContainsKey("get_speed") ? after["get_speed"] : "null")
				+ ",\"beforeSpeedPerc\":" + (before.ContainsKey("get_speedPerc") ? before["get_speedPerc"] : "null")
				+ ",\"afterSpeedPerc\":" + (after.ContainsKey("get_speedPerc") ? after["get_speedPerc"] : "null")
				+ ",\"beforeInitiative\":" + (before.ContainsKey("get_initiative") ? before["get_initiative"] : "null")
				+ ",\"afterInitiative\":" + (after.ContainsKey("get_initiative") ? after["get_initiative"] : "null")
				+ ",\"changed\":{" + changed + "}"
				+ "}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "\\\\").Replace("\"", "'") + "\"}";
		}
	}

	static Dictionary<string, string> DumpStats(object stats)
	{
		var map = new Dictionary<string, string>();
		if (stats == null) return map;
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var m in stats.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (m.ReturnType != typeof(int) && m.ReturnType != typeof(float) && m.ReturnType != typeof(double)) continue;
			if (!m.Name.StartsWith("get_", StringComparison.Ordinal)) continue;
			try { map[m.Name] = Convert.ToString(m.Invoke(stats, null), CultureInfo.InvariantCulture); } catch { }
		}
		return map;
	}

	static Unit FindUnit()
	{
		var queues = Object.FindObjectsOfType<BhBattleQueueView>(true);
		if (queues == null) return null;
		foreach (var q in queues)
		{
			if (q == null) continue;
			foreach (var f in q.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
				if (f.GetValue(q) is Unit u) return u;
			foreach (var m in q.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				if (m.GetParameters().Length != 0 || m.ReturnType != typeof(Unit)) continue;
				try { var u = m.Invoke(q, null) as Unit; if (u != null) return u; } catch { }
			}
		}
		return null;
	}

	static Assembly FindAsm(string n)
	{
		foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
			if (a.GetName().Name == n) return a;
		return null;
	}
}
