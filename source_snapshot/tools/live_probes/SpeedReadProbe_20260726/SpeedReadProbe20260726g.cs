using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726g
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var sb = new StringBuilder();
			sb.Append("{\"ok\":true");

			var beforeStats = SpeedOf(InvokeNamed(unit, "get_stats", flags));
			sb.Append(",\"beforeSpeed\":").Append(beforeStats);

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
			sb.Append(",\"add\":").Append((ok is bool b && b) ? "true" : "false");
			sb.Append(",\"addFail\":\"").Append((args[8] ?? "").ToString().Replace("\"", "'")).Append('"');

			// Resolve buff manager + list for SID.
			object mgr = null;
			foreach (var m in unit.GetType().GetMethods(flags))
			{
				if (m.GetParameters().Length != 0) continue;
				if (m.ReturnType == null) continue;
				if (!m.Name.Contains("ObjectPublicDi2StLi1ObceInLi1Unique") && !m.Name.Contains("get_") ) continue;
				if (m.ReturnType.Name.IndexOf("Di2StLi1", StringComparison.Ordinal) < 0 && m.Name.IndexOf("Di2StLi1", StringComparison.Ordinal) < 0)
					continue;
				try { mgr = m.Invoke(unit, null); if (mgr != null) break; } catch { }
			}
			if (mgr == null)
			{
				// fallback: scan zero-arg getters whose type name looks like buff manager
				foreach (var m in unit.GetType().GetMethods(flags))
				{
					if (m.GetParameters().Length != 0) continue;
					var rn = m.ReturnType?.Name ?? "";
					if (rn.IndexOf("Di2", StringComparison.Ordinal) < 0) continue;
					try { var v = m.Invoke(unit, null); if (v != null) { mgr = v; sb.Append(",\"mgrVia\":\"").Append(m.Name).Append('"'); break; } } catch { }
				}
			}
			sb.Append(",\"mgr\":").Append(mgr == null ? "null" : ("\"" + mgr.GetType().Name + "\""));

			object buffList = null;
			object rawBuff = null;
			if (mgr != null)
			{
				foreach (var m in mgr.GetType().GetMethods(flags))
				{
					var ps = m.GetParameters();
					if (ps.Length != 1 || ps[0].ParameterType != typeof(string)) continue;
					if (m.ReturnType == null || m.ReturnType.Name.IndexOf("List", StringComparison.Ordinal) < 0) continue;
					try
					{
						var list = m.Invoke(mgr, new object[] { sid });
						if (list == null) continue;
						buffList = list;
						sb.Append(",\"listMethod\":\"").Append(m.Name).Append('"');
						var countProp = list.GetType().GetProperty("Count") ?? list.GetType().GetProperty("get_Count");
						int count = -1;
						try
						{
							if (countProp != null) count = Convert.ToInt32(countProp.GetValue(list));
							else
							{
								var cm = list.GetType().GetMethod("get_Count", flags, null, Type.EmptyTypes, null);
								if (cm != null) count = Convert.ToInt32(cm.Invoke(list, null));
							}
						}
						catch { }
						sb.Append(",\"listCount\":").Append(count);
						// indexer
						var item = list.GetType().GetProperty("Item");
						if (item != null && count > 0)
						{
							rawBuff = item.GetValue(list, new object[] { 0 });
						}
						else
						{
							foreach (var im in list.GetType().GetMethods(flags))
							{
								if (im.Name != "get_Item" || im.GetParameters().Length != 1) continue;
								try { rawBuff = im.Invoke(list, new object[] { 0 }); break; } catch { }
							}
						}
						break;
					}
					catch { }
				}
			}

			sb.Append(",\"buffDump\":\"").Append(DumpObjectShallow(rawBuff).Replace("\\", "/").Replace("\"", "'")).Append('"');

			// Call private UnitStat(List, bool, bool) rebuild candidates.
			var rebuildNotes = new StringBuilder();
			foreach (var m in unit.GetType().GetMethods(flags))
			{
				if (m.ReturnType == null || m.ReturnType.Name != "UnitStat") continue;
				var ps = m.GetParameters();
				if (ps.Length < 1 || ps.Length > 3) continue;
				if (ps[0].ParameterType.Name.IndexOf("List", StringComparison.Ordinal) < 0 &&
				    ps[0].ParameterType.Name.IndexOf("IList", StringComparison.Ordinal) < 0 &&
				    ps[0].ParameterType.Name.IndexOf("IEnumerable", StringComparison.Ordinal) < 0)
					continue;

				var callArgs = new object[ps.Length];
				callArgs[0] = buffList;
				for (var i = 1; i < ps.Length; i++)
				{
					if (ps[i].ParameterType == typeof(bool)) callArgs[i] = true;
					else if (ps[i].ParameterType == typeof(int)) callArgs[i] = 0;
					else callArgs[i] = null;
				}
				// try several bool combos
				var combos = ps.Length == 3 && ps[1].ParameterType == typeof(bool) && ps[2].ParameterType == typeof(bool)
					? new[] { new object[] { buffList, false, false }, new object[] { buffList, true, false }, new object[] { buffList, false, true }, new object[] { buffList, true, true } }
					: new[] { callArgs };
				foreach (var ca in combos)
				{
					try
					{
						var ret = m.Invoke(unit, ca);
						var sp = SpeedOf(ret);
						rebuildNotes.Append(m.Name).Append('(');
						for (var i = 0; i < ca.Length; i++)
						{
							if (i > 0) rebuildNotes.Append(',');
							rebuildNotes.Append(ca[i] is bool bb ? (bb ? "T" : "F") : (ca[i] == null ? "null" : ca[i].GetType().Name));
						}
						rebuildNotes.Append(")=>speed=").Append(sp).Append(';');
					}
					catch (Exception ex)
					{
						rebuildNotes.Append(m.Name).Append("=ERR:").Append(ex.GetType().Name).Append(':').Append(ex.InnerException?.GetType().Name ?? "").Append(';');
					}
				}
			}
			sb.Append(",\"rebuild\":\"").Append(rebuildNotes.ToString().Replace("\\", "/").Replace("\"", "'")).Append('"');

			// Also try invoking Final_New_UnitStat_1 after rebuild attempts.
			var afterSlots = new StringBuilder();
			foreach (var name in new[] {
				"get_stats",
				"Method_Public_Virtual_Final_New_UnitStat_0",
				"Method_Public_Virtual_Final_New_UnitStat_1",
				"get__chju_k__BackingField",
				"get__chjv_k__BackingField",
				"Method_Public_Virtual_UnitStat_0"
			})
			{
				var m = unit.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m == null) { afterSlots.Append(name).Append("=MISS;"); continue; }
				try
				{
					var st = m.Invoke(unit, null);
					afterSlots.Append(name).Append(".speed=").Append(SpeedOf(st)).Append(';');
				}
				catch (Exception ex)
				{
					afterSlots.Append(name).Append("=ERR:").Append(ex.GetType().Name).Append(';');
				}
			}
			sb.Append(",\"afterSlots\":\"").Append(afterSlots.ToString().Replace("\"", "'")).Append('"');
			sb.Append('}');
			return sb.ToString();
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static string SpeedOf(object stats)
	{
		if (stats == null) return "null";
		var m = stats.GetType().GetMethod("get_speed", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		if (m == null) return "no-get_speed";
		try { return Convert.ToString(m.Invoke(stats, null), CultureInfo.InvariantCulture); }
		catch { return "err"; }
	}

	static object InvokeNamed(object o, string name, BindingFlags flags)
	{
		var m = o.GetType().GetMethod(name, flags, null, Type.EmptyTypes, null);
		return m?.Invoke(o, null);
	}

	static string DumpObjectShallow(object o)
	{
		if (o == null) return "null";
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var sb = new StringBuilder();
		sb.Append(o.GetType().Name).Append('{');
		foreach (var p in o.GetType().GetProperties(flags))
		{
			if (p.GetIndexParameters().Length != 0) continue;
			if (p.Name.IndexOf("speed", StringComparison.OrdinalIgnoreCase) < 0
			    && p.Name.IndexOf("stat", StringComparison.OrdinalIgnoreCase) < 0
			    && p.Name.IndexOf("sid", StringComparison.OrdinalIgnoreCase) < 0
			    && p.Name.IndexOf("data", StringComparison.OrdinalIgnoreCase) < 0
			    && p.Name.IndexOf("config", StringComparison.OrdinalIgnoreCase) < 0
			    && p.Name.IndexOf("value", StringComparison.OrdinalIgnoreCase) < 0
			    && p.Name.IndexOf("level", StringComparison.OrdinalIgnoreCase) < 0
			    && !p.Name.StartsWith("get_", StringComparison.Ordinal)
			    && p.Name.Length > 12)
				continue;
			try
			{
				var v = p.GetValue(o);
				sb.Append(p.Name).Append('=').Append(Describe(v)).Append(';');
			}
			catch { }
		}
		foreach (var f in o.GetType().GetFields(flags))
		{
			if (f.Name.IndexOf("speed", StringComparison.OrdinalIgnoreCase) < 0
			    && f.Name.IndexOf("stat", StringComparison.OrdinalIgnoreCase) < 0
			    && f.Name.IndexOf("sid", StringComparison.OrdinalIgnoreCase) < 0
			    && f.Name.IndexOf("data", StringComparison.OrdinalIgnoreCase) < 0
			    && f.Name.IndexOf("config", StringComparison.OrdinalIgnoreCase) < 0
			    && f.Name.Length > 20)
				continue;
			try
			{
				var v = f.GetValue(o);
				sb.Append("F:").Append(f.Name).Append('=').Append(Describe(v)).Append(';');
			}
			catch { }
		}
		// nested UnitStat on buff
		foreach (var m in o.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (m.ReturnType == null || m.ReturnType.Name != "UnitStat") continue;
			try
			{
				var st = m.Invoke(o, null);
				sb.Append(m.Name).Append(".speed=").Append(SpeedOf(st)).Append(';');
			}
			catch { }
		}
		sb.Append('}');
		return sb.ToString();
	}

	static string Describe(object v)
	{
		if (v == null) return "null";
		var t = v.GetType();
		if (t.IsPrimitive || v is string) return Convert.ToString(v, CultureInfo.InvariantCulture);
		if (t.Name == "UnitStat") return "UnitStat(speed=" + SpeedOf(v) + ")";
		return t.Name;
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
