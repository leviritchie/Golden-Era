using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726k
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

			EnsureHaste(unit, out var delta);
			if (delta == null) return "{\"ok\":false,\"error\":\"no haste delta\"}";
			var deltaSpeed = GetInt(delta, "get_speed");

			var results = new StringBuilder();
			results.Append("{\"ok\":true,\"deltaSpeed\":").Append(deltaSpeed);

			// A) Try short names bfae / bfak / sdw
			results.Append(",\"short\":\"");
			TryUnitVoid(unit, "bfae", flags, results);
			TryUnitBool(unit, "bfak", true, flags, results);
			TryUnitVoid(unit, "bfal", flags, results);
			var stats = GetStats(unit, flags);
			TryStatMerge(stats, delta, "sdw", flags, results);
			TryStatMerge(stats, delta, "sdy", flags, results);
			results.Append('"');

			// B) Try every UnitStat method (UnitStat)->void and measure additive speed change.
			// Restore speed between tries by snapshotting offence/defence/initiative/speed.
			results.Append(",\"trials\":\"");
			var baseline = Snapshot(GetStats(unit, flags));
			foreach (var m in GetStats(unit, flags).GetType().GetMethods(flags))
			{
				var ps = m.GetParameters();
				if (ps.Length < 1 || ps.Length > 2) continue;
				if (ps[0].ParameterType.Name != "UnitStat") continue;
				if (m.ReturnType != typeof(void) && m.ReturnType.Name != "UnitStat") continue;
				if (ps.Length == 2 && ps[1].ParameterType != typeof(bool)) continue;

				// restore baseline speed/offence before each trial via setters
				Restore(unit, baseline, flags);
				var before = GetInt(GetStats(unit, flags), "get_speed");
				var beforeOff = GetInt(GetStats(unit, flags), "get_offence");
				try
				{
					object ret;
					if (ps.Length == 1) ret = m.Invoke(GetStats(unit, flags), new object[] { delta });
					else ret = m.Invoke(GetStats(unit, flags), new object[] { delta, true });
					var after = GetInt(GetStats(unit, flags), "get_speed");
					var afterOff = GetInt(GetStats(unit, flags), "get_offence");
					var kind = after == before + deltaSpeed && afterOff == beforeOff ? "ADD"
						: after == deltaSpeed && afterOff != beforeOff ? "REPLACE"
						: after != before ? "CHANGED" : "SAME";
					results.Append(m.Name).Append(':').Append(kind)
						.Append('(').Append(before).Append("->").Append(after)
						.Append(",off").Append(beforeOff).Append("->").Append(afterOff).Append(");");
				}
				catch (Exception ex)
				{
					results.Append(m.Name).Append("=ERR:").Append(ex.GetType().Name).Append(';');
				}
			}
			results.Append('"');

			// C) After identifying, apply best: prefer ADD method if found, else set_speed additive.
			Restore(unit, baseline, flags);
			var applied = "none";
			MethodInfo addMethod = null;
			foreach (var m in GetStats(unit, flags).GetType().GetMethods(flags))
			{
				var ps = m.GetParameters();
				if (ps.Length != 1 || ps[0].ParameterType.Name != "UnitStat") continue;
				if (m.ReturnType != typeof(void)) continue;
				// probe classify quickly
				Restore(unit, baseline, flags);
				var b = GetInt(GetStats(unit, flags), "get_speed");
				var bo = GetInt(GetStats(unit, flags), "get_offence");
				try
				{
					m.Invoke(GetStats(unit, flags), new object[] { delta });
					var a = GetInt(GetStats(unit, flags), "get_speed");
					var ao = GetInt(GetStats(unit, flags), "get_offence");
					if (a == b + deltaSpeed && ao == bo) { addMethod = m; break; }
				}
				catch { }
			}
			Restore(unit, baseline, flags);
			var speed0 = GetInt(GetStats(unit, flags), "get_speed");
			if (addMethod != null)
			{
				addMethod.Invoke(GetStats(unit, flags), new object[] { delta });
				applied = "sdw-like:" + addMethod.Name;
			}
			else
			{
				// Try bfae by scanning zero-arg voids that change speed after haste present
				foreach (var m in unit.GetType().GetMethods(flags))
				{
					if (m.GetParameters().Length != 0 || m.ReturnType != typeof(void)) continue;
					if (!m.Name.StartsWith("Method_Public_Void", StringComparison.Ordinal) && m.Name.Length > 8)
						continue;
					var b = GetInt(GetStats(unit, flags), "get_speed");
					var bo = GetInt(GetStats(unit, flags), "get_offence");
					try
					{
						m.Invoke(unit, null);
						var a = GetInt(GetStats(unit, flags), "get_speed");
						var ao = GetInt(GetStats(unit, flags), "get_offence");
						if (a == b + deltaSpeed && ao == bo)
						{
							applied = "unitVoid:" + m.Name;
							break;
						}
						if (a != b)
						{
							// undo unwanted change
							Restore(unit, baseline, flags);
						}
					}
					catch { }
				}
				if (applied == "none")
				{
					var set = GetStats(unit, flags).GetType().GetMethod("set_speed", flags, null, new[] { typeof(int) }, null);
					set.Invoke(GetStats(unit, flags), new object[] { speed0 + deltaSpeed });
					applied = "set_speed additive";
				}
			}
			var speed1 = GetInt(GetStats(unit, flags), "get_speed");
			results.Append(",\"applied\":\"").Append(applied).Append('"');
			results.Append(",\"finalSpeed\":").Append(speed1);
			results.Append(",\"finalOffence\":").Append(GetInt(GetStats(unit, flags), "get_offence"));
			results.Append(",\"proof\":").Append(speed1 == speed0 + deltaSpeed ? "true" : "false");
			results.Append(",\"baseline\":").Append(baseline);
			results.Append('}');
			return results.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static void TryUnitVoid(object unit, string name, BindingFlags flags, StringBuilder sb)
	{
		var m = unit.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
		if (m == null) { sb.Append(name).Append("=MISS;"); return; }
		var before = GetInt(GetStats(unit, flags), "get_speed");
		try
		{
			m.Invoke(unit, null);
			var after = GetInt(GetStats(unit, flags), "get_speed");
			sb.Append(name).Append('=').Append(before).Append("->").Append(after).Append(';');
		}
		catch (Exception ex) { sb.Append(name).Append("=ERR:").Append(ex.GetType().Name).Append(';'); }
	}

	static void TryUnitBool(object unit, string name, bool arg, BindingFlags flags, StringBuilder sb)
	{
		var m = unit.GetType().GetMethod(name, flags, null, new[] { typeof(bool) }, null);
		if (m == null) { sb.Append(name).Append("=MISS;"); return; }
		var before = GetInt(GetStats(unit, flags), "get_speed");
		try
		{
			m.Invoke(unit, new object[] { arg });
			var after = GetInt(GetStats(unit, flags), "get_speed");
			sb.Append(name).Append('=').Append(before).Append("->").Append(after).Append(';');
		}
		catch (Exception ex) { sb.Append(name).Append("=ERR:").Append(ex.GetType().Name).Append(';'); }
	}

	static void TryStatMerge(object stats, object delta, string name, BindingFlags flags, StringBuilder sb)
	{
		MethodInfo m = stats.GetType().GetMethod(name, flags, null, new[] { delta.GetType() }, null)
			?? stats.GetType().GetMethod(name, flags, null, new[] { typeof(object) }, null);
		if (m == null)
		{
			foreach (var cand in stats.GetType().GetMethods(flags))
			{
				if (cand.Name != name) continue;
				m = cand; break;
			}
		}
		if (m == null) { sb.Append(name).Append("=MISS;"); return; }
		var before = GetInt(stats, "get_speed");
		try
		{
			var ps = m.GetParameters();
			if (ps.Length == 1) m.Invoke(stats, new object[] { delta });
			else if (ps.Length == 2 && ps[1].ParameterType == typeof(bool)) m.Invoke(stats, new object[] { delta, true });
			var after = GetInt(stats, "get_speed");
			sb.Append(name).Append('=').Append(before).Append("->").Append(after).Append(';');
		}
		catch (Exception ex) { sb.Append(name).Append("=ERR:").Append(ex.GetType().Name).Append(';'); }
	}

	static void EnsureHaste(object unit, out object delta)
	{
		delta = null;
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var mod = FindAsm("OfflineUnlockMod");
		var adapter = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter");
		MethodInfo add = null;
		foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
		{
			if (m.Name != "TryAddBuffSidFromReceiver") continue;
			var ps = m.GetParameters();
			if (ps.Length == 9 && ps[7].ParameterType.IsByRef) { add = m; break; }
		}
		add.Invoke(null, new object[] { unit, "magic_haste_effect_1", unit, 1, 99, 1, true, null, null });
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
		delta = data.GetType().GetProperty("stats", flags).GetValue(data);
	}

	static string Snapshot(object stats)
	{
		return "{"
			+ "\"speed\":" + GetInt(stats, "get_speed")
			+ ",\"initiative\":" + GetInt(stats, "get_initiative")
			+ ",\"offence\":" + GetInt(stats, "get_offence")
			+ ",\"defence\":" + GetInt(stats, "get_defence")
			+ "}";
	}

	static void Restore(object unit, string baselineJson, BindingFlags flags)
	{
		var stats = GetStats(unit, flags);
		Set(stats, "set_speed", Extract(baselineJson, "speed"), flags);
		Set(stats, "set_initiative", Extract(baselineJson, "initiative"), flags);
		Set(stats, "set_offence", Extract(baselineJson, "offence"), flags);
		Set(stats, "set_defence", Extract(baselineJson, "defence"), flags);
	}

	static void Set(object stats, string setter, int value, BindingFlags flags)
	{
		var m = stats.GetType().GetMethod(setter, flags, null, new[] { typeof(int) }, null);
		if (m == null) return;
		m.Invoke(stats, new object[] { value });
	}

	static int Extract(string json, string key)
	{
		var token = "\"" + key + "\":";
		var idx = json.IndexOf(token, StringComparison.Ordinal);
		var start = idx + token.Length;
		var end = start;
		while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '-')) end++;
		return int.Parse(json.Substring(start, end - start), CultureInfo.InvariantCulture);
	}

	static object GetStats(object unit, BindingFlags flags)
	{
		return unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null).Invoke(unit, null);
	}

	static int GetInt(object o, string getter)
	{
		var m = o.GetType().GetMethod(getter, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
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
