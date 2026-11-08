using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726h
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
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
			var sid = "magic_haste_effect_1";
			var args = new object[] { unit, sid, unit, 1, 99, 1, true, null, null };
			var ok = add.Invoke(null, args);

			object mgr = null;
			foreach (var name in GameSymbolsBuffMgrGetters())
			{
				var mm = unit.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (mm == null) continue;
				try { mgr = mm.Invoke(unit, null); if (mgr != null) break; } catch { }
			}
			if (mgr == null)
			{
				foreach (var m in unit.GetType().GetMethods(flags))
				{
					if (m.GetParameters().Length != 0) continue;
					if ((m.ReturnType?.Name ?? "").IndexOf("Di2StLi1", StringComparison.Ordinal) < 0) continue;
					try { mgr = m.Invoke(unit, null); if (mgr != null) break; } catch { }
				}
			}

			object rawBuff = null;
			object list = null;
			if (mgr != null)
			{
				foreach (var m in mgr.GetType().GetMethods(flags))
				{
					var ps = m.GetParameters();
					if (ps.Length != 1 || ps[0].ParameterType != typeof(string)) continue;
					if ((m.ReturnType?.Name ?? "").IndexOf("List", StringComparison.Ordinal) < 0) continue;
					try
					{
						list = m.Invoke(mgr, new object[] { sid });
						if (list == null) continue;
						var getItem = list.GetType().GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
						if (getItem != null) rawBuff = getItem.Invoke(list, new object[] { 0 });
						break;
					}
					catch { }
				}
			}

			var sb = new StringBuilder();
			sb.Append("{\"ok\":true,\"add\":").Append((ok is bool b && b) ? "true" : "false");
			sb.Append(",\"addFail\":\"").Append((args[8] ?? "").ToString().Replace("\"", "'")).Append('"');
			sb.Append(",\"buffType\":\"").Append(rawBuff?.GetType().Name ?? "null").Append('"');
			sb.Append(",\"configDeep\":\"").Append(DeepDumpConfigs(rawBuff).Replace("\\", "/").Replace("\"", "'")).Append('"');
			sb.Append(",\"buffUnitStats\":\"").Append(DumpAllUnitStats(rawBuff).Replace("\\", "/").Replace("\"", "'")).Append('"');
			sb.Append(",\"unitSpeed\":").Append(SpeedOf(Invoke(unit, "get_stats", flags)));
			sb.Append('}');
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static string[] GameSymbolsBuffMgrGetters()
	{
		return new[]
		{
			"Method_Public_Virtual_Final_New_get_ObjectPublicDi2StLi1ObceInLi1Unique_0",
			"get__cfnh_k__BackingField",
			"cnyb",
			"bbds"
		};
	}

	static string DeepDumpConfigs(object buff)
	{
		if (buff == null) return "null";
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var sb = new StringBuilder();
		foreach (var name in new[] { "config", "dataConfig", "get_config", "get_dataConfig", "prop_BuffConfig_0" })
		{
			object cfg = null;
			var p = buff.GetType().GetProperty(name, flags);
			if (p != null && p.GetIndexParameters().Length == 0)
			{
				try { cfg = p.GetValue(buff); } catch { }
			}
			if (cfg == null)
			{
				var f = buff.GetType().GetField(name, flags);
				if (f != null) try { cfg = f.GetValue(buff); } catch { }
			}
			if (cfg == null)
			{
				var m = buff.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m != null) try { cfg = m.Invoke(buff, null); } catch { }
			}
			if (cfg == null) continue;
			sb.Append(name).Append("=>").Append(DumpBuffConfig(cfg)).Append(" || ");
		}
		// any BuffConfig-typed member
		foreach (var p in buff.GetType().GetProperties(flags))
		{
			if (p.GetIndexParameters().Length != 0) continue;
			if ((p.PropertyType?.Name ?? "") != "BuffConfig") continue;
			try
			{
				var cfg = p.GetValue(buff);
				sb.Append("P:").Append(p.Name).Append("=>").Append(DumpBuffConfig(cfg)).Append(" || ");
			}
			catch { }
		}
		foreach (var f in buff.GetType().GetFields(flags))
		{
			if ((f.FieldType?.Name ?? "") != "BuffConfig") continue;
			try
			{
				var cfg = f.GetValue(buff);
				sb.Append("F:").Append(f.Name).Append("=>").Append(DumpBuffConfig(cfg)).Append(" || ");
			}
			catch { }
		}
		return sb.ToString();
	}

	static string DumpBuffConfig(object cfg)
	{
		if (cfg == null) return "null";
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var sb = new StringBuilder();
		sb.Append(cfg.GetType().Name).Append('{');
		// sid / id / tags
		foreach (var name in new[] { "id", "sid", "get_id", "get_sid", "tags", "get_tags", "icon" })
		{
			TryAppendMember(cfg, name, sb, flags);
		}
		// data / stats nesting
		object data = ReadMember(cfg, "data") ?? ReadMember(cfg, "get_data") ?? ReadMember(cfg, "prop_Object_0");
		if (data != null)
		{
			sb.Append("data=").Append(data.GetType().Name).Append('{');
			object stats = ReadMember(data, "stats") ?? ReadMember(data, "get_stats") ?? ReadMember(data, "prop_UnitStat_0");
			if (stats != null)
			{
				sb.Append("stats.speed=").Append(SpeedOf(stats)).Append(';');
				sb.Append("statsDump=").Append(DumpNumericGets(stats)).Append(';');
			}
			else
			{
				sb.Append("stats=null;");
				sb.Append("dataMembers=").Append(ListMembers(data)).Append(';');
			}
			sb.Append('}');
		}
		else
		{
			sb.Append("data=null;");
			// maybe UnitStat directly on config
			foreach (var m in cfg.GetType().GetMethods(flags))
			{
				if (m.GetParameters().Length != 0) continue;
				if (m.ReturnType?.Name != "UnitStat") continue;
				try
				{
					var st = m.Invoke(cfg, null);
					sb.Append(m.Name).Append(".speed=").Append(SpeedOf(st)).Append(';');
				}
				catch { }
			}
			sb.Append("cfgMembers=").Append(ListMembers(cfg)).Append(';');
		}
		sb.Append('}');
		return sb.ToString();
	}

	static void TryAppendMember(object o, string name, StringBuilder sb, BindingFlags flags)
	{
		var v = ReadMember(o, name);
		if (v == null) return;
		sb.Append(name).Append('=').Append(Describe(v)).Append(';');
	}

	static object ReadMember(object o, string name)
	{
		if (o == null) return null;
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var p = o.GetType().GetProperty(name, flags);
		if (p != null && p.GetIndexParameters().Length == 0)
		{
			try { return p.GetValue(o); } catch { }
		}
		var f = o.GetType().GetField(name, flags);
		if (f != null)
		{
			try { return f.GetValue(o); } catch { }
		}
		var m = o.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
		if (m != null)
		{
			try { return m.Invoke(o, null); } catch { }
		}
		return null;
	}

	static string DumpAllUnitStats(object o)
	{
		if (o == null) return "null";
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var sb = new StringBuilder();
		foreach (var m in o.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (m.ReturnType?.Name != "UnitStat") continue;
			try
			{
				var st = m.Invoke(o, null);
				sb.Append(m.Name).Append('{').Append(DumpNumericGets(st)).Append("};");
			}
			catch { }
		}
		foreach (var f in o.GetType().GetFields(flags))
		{
			if (f.FieldType?.Name != "UnitStat") continue;
			try
			{
				var st = f.GetValue(o);
				sb.Append("F:").Append(f.Name).Append('{').Append(DumpNumericGets(st)).Append("};");
			}
			catch { }
		}
		return sb.ToString();
	}

	static string DumpNumericGets(object o)
	{
		if (o == null) return "null";
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var sb = new StringBuilder();
		foreach (var m in o.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (!m.Name.StartsWith("get_", StringComparison.Ordinal)) continue;
			if (m.ReturnType != typeof(int) && m.ReturnType != typeof(float) && m.ReturnType != typeof(double)) continue;
			if (m.Name.IndexOf("speed", StringComparison.OrdinalIgnoreCase) < 0
			    && m.Name.IndexOf("initiative", StringComparison.OrdinalIgnoreCase) < 0
			    && m.Name.IndexOf("offence", StringComparison.OrdinalIgnoreCase) < 0
			    && m.Name.IndexOf("defence", StringComparison.OrdinalIgnoreCase) < 0
			    && m.Name.IndexOf("Perc", StringComparison.Ordinal) < 0)
				continue;
			try
			{
				sb.Append(m.Name).Append('=').Append(Convert.ToString(m.Invoke(o, null), CultureInfo.InvariantCulture)).Append(';');
			}
			catch { }
		}
		return sb.ToString();
	}

	static string ListMembers(object o)
	{
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var sb = new StringBuilder();
		foreach (var p in o.GetType().GetProperties(flags))
		{
			if (p.GetIndexParameters().Length != 0) continue;
			sb.Append('P').Append(p.Name).Append(':').Append(p.PropertyType?.Name).Append(';');
		}
		foreach (var f in o.GetType().GetFields(flags))
			sb.Append('F').Append(f.Name).Append(':').Append(f.FieldType?.Name).Append(';');
		foreach (var m in o.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (!m.Name.StartsWith("get_", StringComparison.Ordinal) && !m.Name.StartsWith("Method_", StringComparison.Ordinal)) continue;
			sb.Append('M').Append(m.Name).Append(':').Append(m.ReturnType?.Name).Append(';');
		}
		return sb.ToString();
	}

	static string Describe(object v)
	{
		if (v == null) return "null";
		if (v is string || v.GetType().IsPrimitive) return Convert.ToString(v, CultureInfo.InvariantCulture);
		if (v is System.Collections.IEnumerable en && !(v is string))
		{
			var sb = new StringBuilder();
			sb.Append('[');
			var n = 0;
			foreach (var item in en)
			{
				if (n++ > 12) { sb.Append("..."); break; }
				if (n > 1) sb.Append(',');
				sb.Append(item);
			}
			sb.Append(']');
			return sb.ToString();
		}
		return v.GetType().Name;
	}

	static string SpeedOf(object stats)
	{
		if (stats == null) return "null";
		var m = stats.GetType().GetMethod("get_speed", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		if (m == null) return "no";
		try { return Convert.ToString(m.Invoke(stats, null), CultureInfo.InvariantCulture); }
		catch { return "err"; }
	}

	static object Invoke(object o, string name, BindingFlags flags)
	{
		var m = o.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
		return m?.Invoke(o, null);
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
