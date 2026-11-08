using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726j
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var stats = GetStats(unit, flags);
			var before = Snapshot(stats);
			var notes = new StringBuilder();

			// Prefer additive apply of haste config delta onto current get_stats.
			EnsureHaste(unit, notes);
			var deltaSpeed = ReadHasteConfigSpeed(unit, flags, notes);
			var setSpeed = stats.GetType().GetMethod("set_speed", flags, null, new[] { typeof(int) }, null);
			var speedBefore = GetInt(stats, "get_speed");
			if (setSpeed == null) return "{\"ok\":false,\"error\":\"no set_speed\"}";
			setSpeed.Invoke(stats, new object[] { speedBefore + deltaSpeed });
			var after = Snapshot(GetStats(unit, flags));
			var speedAfter = GetInt(GetStats(unit, flags), "get_speed");

			// Enumerate UnitStat binary ops for a native additive candidate (diagnostic).
			var ops = new StringBuilder();
			foreach (var m in stats.GetType().GetMethods(flags))
			{
				var ps = m.GetParameters();
				if (ps.Length != 1 || ps[0].ParameterType.Name != "UnitStat") continue;
				ops.Append(m.Name).Append("->").Append(m.ReturnType?.Name ?? "void").Append(';');
			}

			return "{"
				+ "\"ok\":true"
				+ ",\"deltaSpeed\":" + deltaSpeed
				+ ",\"speedBefore\":" + speedBefore
				+ ",\"speedAfter\":" + speedAfter
				+ ",\"expected\":" + (speedBefore + deltaSpeed)
				+ ",\"speedMatched\":" + (speedAfter == speedBefore + deltaSpeed ? "true" : "false")
				+ ",\"before\":" + before
				+ ",\"after\":" + after
				+ ",\"otherStatsUnchanged\":" + (OtherUnchanged(before, after) ? "true" : "false")
				+ ",\"unitStatOps\":\"" + ops.ToString().Replace("\"", "'") + "\""
				+ ",\"notes\":\"" + notes.ToString().Replace("\\", "/").Replace("\"", "'") + "\""
				+ "}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static void EnsureHaste(object unit, StringBuilder notes)
	{
		var mod = FindAsm("OfflineUnlockMod");
		var adapter = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter");
		MethodInfo add = null;
		foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
		{
			if (m.Name != "TryAddBuffSidFromReceiver") continue;
			var ps = m.GetParameters();
			if (ps.Length == 9 && ps[7].ParameterType.IsByRef) { add = m; break; }
		}
		var args = new object[] { unit, "magic_haste_effect_1", unit, 1, 99, 1, true, null, null };
		var ok = add.Invoke(null, args);
		notes.Append("add=").Append(ok).Append(';');
	}

	static int ReadHasteConfigSpeed(object unit, BindingFlags flags, StringBuilder notes)
	{
		object mgr = null;
		foreach (var m in unit.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if ((m.ReturnType?.Name ?? "").IndexOf("Di2StLi1", StringComparison.Ordinal) < 0) continue;
			try { mgr = m.Invoke(unit, null); if (mgr != null) break; } catch { }
		}
		object buff = null;
		foreach (var m in mgr.GetType().GetMethods(flags))
		{
			var ps = m.GetParameters();
			if (ps.Length != 1 || ps[0].ParameterType != typeof(string)) continue;
			if ((m.ReturnType?.Name ?? "").IndexOf("List", StringComparison.Ordinal) < 0) continue;
			try
			{
				var list = m.Invoke(mgr, new object[] { "magic_haste_effect_1" });
				var getItem = list?.GetType().GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
				buff = getItem?.Invoke(list, new object[] { 0 });
				if (buff != null) break;
			}
			catch { }
		}
		var cfg = buff.GetType().GetProperty("config", flags).GetValue(buff);
		var data = cfg.GetType().GetProperty("data", flags).GetValue(cfg);
		var delta = data.GetType().GetProperty("stats", flags).GetValue(data);
		var sp = GetInt(delta, "get_speed");
		notes.Append("configSpeed=").Append(sp).Append(';');
		return sp;
	}

	static string Snapshot(object stats)
	{
		var sb = new StringBuilder();
		sb.Append('{');
		var first = true;
		foreach (var name in new[] { "get_speed", "get_initiative", "get_offence", "get_defence", "get_speedPerc" })
		{
			if (!first) sb.Append(',');
			first = false;
			sb.Append('"').Append(name).Append("\":").Append(GetInt(stats, name));
		}
		sb.Append('}');
		return sb.ToString();
	}

	static bool OtherUnchanged(string beforeJson, string afterJson)
	{
		// crude: initiative/offence/defence same
		try
		{
			// parse minimally
			return Extract(beforeJson, "get_initiative") == Extract(afterJson, "get_initiative")
				&& Extract(beforeJson, "get_offence") == Extract(afterJson, "get_offence")
				&& Extract(beforeJson, "get_defence") == Extract(afterJson, "get_defence");
		}
		catch { return false; }
	}

	static int Extract(string json, string key)
	{
		var idx = json.IndexOf('"' + key + '"', StringComparison.Ordinal);
		if (idx < 0) return int.MinValue;
		var colon = json.IndexOf(':', idx);
		var end = colon + 1;
		while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '-')) end++;
		return int.Parse(json.Substring(colon + 1, end - colon - 1), CultureInfo.InvariantCulture);
	}

	static object GetStats(object unit, BindingFlags flags)
	{
		return unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null).Invoke(unit, null);
	}

	static int GetInt(object o, string getter)
	{
		if (o == null) return -999;
		var m = o.GetType().GetMethod(getter, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		if (m == null) return -998;
		return Convert.ToInt32(m.Invoke(o, null));
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
