using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726m
{
	// Live-prove: add Split Assembly speed buff + apply config.data.stats.speed additively via set_speed.
	public static string Run(string requestJson)
	{
		try
		{
			var findDiag = new StringBuilder();
			var unit = FindUnit(findDiag);
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\",\"find\":\"" + findDiag.ToString().Replace("\"", "'") + "\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var sid = "homm3_factory_split_assembly_speed_1";
			var stats = GetStats(unit, flags);
			var before = GetInt(stats, "get_speed");
			var beforeOff = GetInt(stats, "get_offence");

			var mod = FindAsm("OfflineUnlockMod");
			var adapter = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter");
			MethodInfo add = null;
			foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
			{
				if (m.Name != "TryAddBuffSidFromReceiver") continue;
				var ps = m.GetParameters();
				if (ps.Length == 9 && ps[7].ParameterType.IsByRef) { add = m; break; }
			}
			var args = new object[] { unit, sid, unit, 1, 99, 1, true, null, null };
			var ok = add.Invoke(null, args);

			var delta = ReadConfigSpeed(unit, sid, flags, out var tags);
			var set = stats.GetType().GetMethod("set_speed", flags, null, new[] { typeof(int) }, null);
			set.Invoke(stats, new object[] { before + delta });
			var after = GetInt(GetStats(unit, flags), "get_speed");
			var afterOff = GetInt(GetStats(unit, flags), "get_offence");

			return "{"
				+ "\"ok\":true"
				+ ",\"sid\":\"" + sid + "\""
				+ ",\"add\":" + ((ok is bool b && b) ? "true" : "false")
				+ ",\"addFail\":\"" + (args[8] ?? "").ToString().Replace("\"", "'") + "\""
				+ ",\"tags\":\"" + tags.Replace("\"", "'") + "\""
				+ ",\"configSpeed\":" + delta
				+ ",\"before\":" + before
				+ ",\"after\":" + after
				+ ",\"expected\":" + (before + delta)
				+ ",\"proof\":" + (after == before + delta && afterOff == beforeOff ? "true" : "false")
				+ ",\"offenceUnchanged\":" + (afterOff == beforeOff ? "true" : "false")
				+ "}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static int ReadConfigSpeed(object unit, string sid, BindingFlags flags, out string tags)
	{
		tags = "";
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
				var list = m.Invoke(mgr, new object[] { sid });
				var getItem = list?.GetType().GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
				buff = getItem?.Invoke(list, new object[] { 0 });
				if (buff != null) break;
			}
			catch { }
		}
		var cfg = buff.GetType().GetProperty("config", flags).GetValue(buff);
		var tagObj = cfg.GetType().GetProperty("tags", flags)?.GetValue(cfg);
		if (tagObj is System.Collections.IEnumerable en)
		{
			var sb = new StringBuilder();
			foreach (var t in en) { if (sb.Length > 0) sb.Append(','); sb.Append(t); if (sb.Length > 120) break; }
			tags = sb.ToString();
		}
		var data = cfg.GetType().GetProperty("data", flags).GetValue(cfg);
		var delta = data.GetType().GetProperty("stats", flags).GetValue(data);
		return GetInt(delta, "get_speed");
	}

	static object GetStats(object unit, BindingFlags flags)
	{
		return unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null).Invoke(unit, null);
	}

	static int GetInt(object o, string getter)
	{
		var m = o.GetType().GetMethod(getter, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		return Convert.ToInt32(m.Invoke(o, null), CultureInfo.InvariantCulture);
	}

	static Unit FindUnit(StringBuilder diag)
	{
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var mod = FindAsm("OfflineUnlockMod");
			diag.Append("mod=").Append(mod != null).Append(';');
			var reg = mod?.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry");
			diag.Append("reg=").Append(reg != null).Append(';');
			var snap = reg?.GetMethod("SnapshotUnits", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
			diag.Append("snap=").Append(snap != null).Append(';');
			if (snap != null)
			{
				var list = snap.Invoke(null, new object[] { 64 });
				diag.Append("listType=").Append(list?.GetType().FullName ?? "null").Append(';');
				var n = 0;
				if (list is System.Collections.IEnumerable en)
				{
					foreach (var item in en)
					{
						n++;
						if (item == null) continue;
						var t = item.GetType();
						diag.Append("item=").Append(t.FullName).Append(';');
						object raw = null;
						foreach (var f in t.GetFields(flags))
						{
							if (f.Name != "Unit") continue;
							raw = f.GetValue(item);
							diag.Append("fieldUnitType=").Append(raw?.GetType().FullName ?? "null").Append(';');
						}
						if (raw is Unit u) return u;
						if (raw != null)
						{
							try { return (Unit)raw; }
							catch (Exception ex) { diag.Append("castERR=").Append(ex.GetType().Name).Append(';'); }
						}
					}
				}
				diag.Append("n=").Append(n).Append(';');
			}
		}
		catch (Exception ex)
		{
			diag.Append("regERR=").Append(ex.GetType().Name).Append(':').Append(ex.Message).Append(';');
		}

		var queues = Object.FindObjectsOfType<BhBattleQueueView>(true);
		diag.Append("queues=").Append(queues?.Length ?? -1).Append(';');
		if (queues != null)
		{
			foreach (var q in queues)
			{
				if (q == null) continue;
				foreach (var f in q.GetType().GetFields(flags))
					if (f.GetValue(q) is Unit u) return u;
				foreach (var m in q.GetType().GetMethods(flags))
				{
					if (m.GetParameters().Length != 0 || m.ReturnType != typeof(Unit)) continue;
					try { var u = m.Invoke(q, null) as Unit; if (u != null) return u; } catch { }
				}
			}
		}
		var units = Object.FindObjectsOfType<Unit>(true);
		diag.Append("findUnits=").Append(units?.Length ?? -1).Append(';');
		if (units != null)
		{
			foreach (var u in units)
				if (u != null) return u;
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
