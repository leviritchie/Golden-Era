using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726f
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var before = SnapshotAllStatSlots(unit, flags);

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
			var args = new object[] { unit, sid, unit, 1, 99, 1, true, null, null };
			var ok = add.Invoke(null, args);

			// Call every zero-arg UnitStat-returning method (possible rebuilds).
			var rebuild = new StringBuilder();
			foreach (var m in unit.GetType().GetMethods(flags))
			{
				if (m.GetParameters().Length != 0) continue;
				if (m.ReturnType == null || m.ReturnType.Name != "UnitStat") continue;
				if (!m.Name.StartsWith("Method_", StringComparison.Ordinal) && m.Name != "get_stats" && m.Name.Length > 8)
					continue;
				try
				{
					var ret = m.Invoke(unit, null);
					rebuild.Append(m.Name).Append("=").Append(ret == null ? "null" : "ok").Append(';');
				}
				catch (Exception ex)
				{
					rebuild.Append(m.Name).Append("=ERR:").Append(ex.GetType().Name).Append(';');
				}
			}

			// Also try short recovered names if present on this build.
			foreach (var name in new[] { "beyk", "beym", "bbcl", "bbcm", "get_stats" })
			{
				var m = unit.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m == null) { rebuild.Append(name).Append("=MISS;"); continue; }
				try
				{
					var ret = m.Invoke(unit, null);
					rebuild.Append(name).Append("=").Append(ret == null ? "null" : ret.GetType().Name).Append(';');
				}
				catch (Exception ex)
				{
					rebuild.Append(name).Append("=ERR:").Append(ex.GetType().Name).Append(';');
				}
			}

			// Try bbgx(int) for a small enum range if present.
			foreach (var m in unit.GetType().GetMethods(flags))
			{
				if (m.Name != "bbgx" && !m.Name.Contains("bbgx")) continue;
				var ps = m.GetParameters();
				if (ps.Length != 1 || ps[0].ParameterType != typeof(int)) continue;
				for (var i = 0; i < 16; i++)
				{
					try
					{
						var v = m.Invoke(unit, new object[] { i });
						rebuild.Append(m.Name).Append('(').Append(i).Append(")=").Append(v).Append(';');
					}
					catch { /* ignore */ }
				}
			}

			var after = SnapshotAllStatSlots(unit, flags);
			var changed = Diff(before, after);
			var catalog = CatalogStatAccessors(unit, flags);

			return "{"
				+ "\"ok\":true"
				+ ",\"sid\":\"" + sid + "\""
				+ ",\"add\":" + ((ok is bool b && b) ? "true" : "false")
				+ ",\"addFail\":\"" + (args[8] ?? "").ToString().Replace("\"", "'") + "\""
				+ ",\"rebuild\":\"" + rebuild.ToString().Replace("\\", "/").Replace("\"", "'") + "\""
				+ ",\"catalog\":\"" + catalog.Replace("\\", "/").Replace("\"", "'") + "\""
				+ ",\"before\":" + ToJson(before)
				+ ",\"after\":" + ToJson(after)
				+ ",\"changed\":" + ToJson(changed)
				+ "}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static Dictionary<string, string> SnapshotAllStatSlots(object unit, BindingFlags flags)
	{
		var map = new Dictionary<string, string>();
		foreach (var m in unit.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (m.ReturnType == null || m.ReturnType.Name != "UnitStat") continue;
			object stats;
			try { stats = m.Invoke(unit, null); }
			catch { continue; }
			if (stats == null)
			{
				map[m.Name + ".null"] = "1";
				continue;
			}
			ReadSpeed(stats, m.Name, map);
		}
		foreach (var f in unit.GetType().GetFields(flags))
		{
			if (f.FieldType == null || f.FieldType.Name != "UnitStat") continue;
			object stats;
			try { stats = f.GetValue(unit); }
			catch { continue; }
			if (stats == null)
			{
				map[f.Name + ".null"] = "1";
				continue;
			}
			ReadSpeed(stats, "field:" + f.Name, map);
		}
		return map;
	}

	static void ReadSpeed(object stats, string prefix, Dictionary<string, string> map)
	{
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[] { "get_speed", "get_speedPerc", "get_initiative", "get_offence", "get_defence" })
		{
			var m = stats.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (m == null) continue;
			try
			{
				map[prefix + "." + name] = Convert.ToString(m.Invoke(stats, null), CultureInfo.InvariantCulture);
			}
			catch { }
		}
		// identity of UnitStat instance
		try
		{
			var ptrProp = stats.GetType().GetProperty("Pointer", BindingFlags.Instance | BindingFlags.Public);
			if (ptrProp != null)
				map[prefix + ".ptr"] = Convert.ToString(ptrProp.GetValue(stats), CultureInfo.InvariantCulture);
		}
		catch { }
	}

	static string CatalogStatAccessors(object unit, BindingFlags flags)
	{
		var sb = new StringBuilder();
		foreach (var m in unit.GetType().GetMethods(flags))
		{
			if (m.ReturnType == null || m.ReturnType.Name != "UnitStat") continue;
			sb.Append(m.Name).Append('(');
			var first = true;
			foreach (var p in m.GetParameters())
			{
				if (!first) sb.Append(',');
				first = false;
				sb.Append(p.ParameterType.Name);
			}
			sb.Append(");");
		}
		foreach (var f in unit.GetType().GetFields(flags))
		{
			if (f.FieldType == null || f.FieldType.Name != "UnitStat") continue;
			sb.Append("F:").Append(f.Name).Append(';');
		}
		return sb.ToString();
	}

	static Dictionary<string, string> Diff(Dictionary<string, string> before, Dictionary<string, string> after)
	{
		var d = new Dictionary<string, string>();
		foreach (var kv in after)
		{
			before.TryGetValue(kv.Key, out var b);
			if (b == kv.Value) continue;
			d[kv.Key] = (b ?? "null") + "->" + kv.Value;
		}
		foreach (var kv in before)
		{
			if (after.ContainsKey(kv.Key)) continue;
			d[kv.Key] = kv.Value + "->missing";
		}
		return d;
	}

	static string ToJson(Dictionary<string, string> map)
	{
		var sb = new StringBuilder();
		sb.Append('{');
		var first = true;
		foreach (var kv in map)
		{
			if (!first) sb.Append(',');
			first = false;
			sb.Append('"').Append(kv.Key.Replace("\"", "'")).Append("\":\"").Append((kv.Value ?? "").Replace("\"", "'")).Append('"');
		}
		sb.Append('}');
		return sb.ToString();
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
