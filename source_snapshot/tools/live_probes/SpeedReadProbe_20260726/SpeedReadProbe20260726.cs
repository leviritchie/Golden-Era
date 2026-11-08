using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726d
{
	public static string Run(string requestJson)
	{
		var sb = new StringBuilder();
		sb.Append("{\"ok\":true");
		try
		{
			var unit = FindUnit();
			if (unit == null)
				return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var stats = unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null).Invoke(unit, null);
			var before = DumpStats(stats);
			var mod = FindAsm("OfflineUnlockMod");
			var adapter = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter");
			MethodInfo add = null;
			foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
			{
				if (m.Name != "TryAddBuffSidFromReceiver") continue;
				var ps = m.GetParameters();
				if (ps.Length == 9 && ps[7].ParameterType.IsByRef) { add = m; break; }
			}
			var sid = "magic_haste_effect_1";
			if (requestJson != null && requestJson.Contains("custom"))
				sid = "homm3_factory_split_assembly_speed_1";
			var args = new object[] { unit, sid, unit, 1, 99, 1, true, null, null };
			var ok = add.Invoke(null, args);
			// refresh mgr Unit hooks
			object mgr = null;
			foreach (var name in new[] { "Method_Public_Virtual_Final_New_get_ObjectPublicDi2StLi1ObceInLi1Unique_0", "cnyb", "bbds" })
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
					if (!m.Name.StartsWith("Method_Public_Void_Unit")) continue;
					try { m.Invoke(mgr, new object[] { unit }); refresh.Append(m.Name).Append("(ok);"); }
					catch (Exception ex) { refresh.Append(m.Name).Append("(ERR);"); }
				}
			}
			var stats2 = unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null).Invoke(unit, null);
			var after = DumpStats(stats2);
			var changed = new Dictionary<string, string>();
			foreach (var kv in after)
			{
				before.TryGetValue(kv.Key, out var b);
				if (b != kv.Value)
					changed[kv.Key] = (b ?? "null") + "->" + kv.Value;
			}
			sb.Append(",\"sid\":\"").Append(sid).Append("\",\"add\":").Append(ok.ToString().ToLowerInvariant());
			sb.Append(",\"addFail\":\"").Append((args[8] ?? "").ToString().Replace("\"","'")).Append("\"");
			sb.Append(",\"refresh\":\"").Append(refresh.ToString().Replace("\"","'")).Append("\"");
			sb.Append(",\"beforeSpeed\":").Append(before.ContainsKey("get_speed") ? before["get_speed"] : "null");
			sb.Append(",\"afterSpeed\":").Append(after.ContainsKey("get_speed") ? after["get_speed"] : "null");
			sb.Append(",\"beforeSpeedPerc\":").Append(before.ContainsKey("get_speedPerc") ? before["get_speedPerc"] : "null");
			sb.Append(",\"afterSpeedPerc\":").Append(after.ContainsKey("get_speedPerc") ? after["get_speedPerc"] : "null");
			sb.Append(",\"changed\":{");
			var first = true;
			foreach (var kv in changed)
			{
				if (!first) sb.Append(',');
				first = false;
				sb.Append("\"").Append(kv.Key).Append("\":\"").Append(kv.Value).Append("\"");
			}
			sb.Append("}}");
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\"","'") + "\"}";
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
			if (!m.Name.StartsWith("get_")) continue;
			try { map[m.Name] = Convert.ToString(m.Invoke(stats, null), System.Globalization.CultureInfo.InvariantCulture); }
			catch { }
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
	static Assembly FindAsm(string n) { foreach (var a in AppDomain.CurrentDomain.GetAssemblies()) if (a.GetName().Name == n) return a; return null; }
}
