using System;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class BuffDurationProbe20260726
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var dur = 99;
			if (requestJson != null)
			{
				if (requestJson.IndexOf("neg1", StringComparison.OrdinalIgnoreCase) >= 0) dur = -1;
				else if (requestJson.IndexOf("9999", StringComparison.OrdinalIgnoreCase) >= 0) dur = 9999;
				else if (requestJson.IndexOf("dur1", StringComparison.OrdinalIgnoreCase) >= 0) dur = 1;
			}
			var sid = "homm3_factory_split_assembly_speed_1";
			var mod = FindAsm("OfflineUnlockMod");
			var adapter = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter");
			MethodInfo add = null;
			foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
			{
				if (m.Name != "TryAddBuffSidFromReceiver") continue;
				var ps = m.GetParameters();
				if (ps.Length == 9 && ps[7].ParameterType.IsByRef) { add = m; break; }
			}
			var args = new object[] { unit, sid, unit, 1, dur, 1, true, null, null };
			var ok = add.Invoke(null, args);
			var dump = DumpBuff(unit, sid, flags);
			return "{\"ok\":true,\"requestedDuration\":" + dur
				+ ",\"add\":" + ((ok is bool b && b) ? "true" : "false")
				+ ",\"addFail\":\"" + (args[8] ?? "").ToString().Replace("\"", "'") + "\""
				+ ",\"buff\":\"" + dump.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static string DumpBuff(object unit, string sid, BindingFlags flags)
	{
		object mgr = null;
		foreach (var m in unit.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if ((m.ReturnType?.Name ?? "").IndexOf("Di2StLi1", StringComparison.Ordinal) < 0) continue;
			try { mgr = m.Invoke(unit, null); if (mgr != null) break; } catch { }
		}
		if (mgr == null) return "no-mgr";
		object buff = null;
		var count = -1;
		foreach (var m in mgr.GetType().GetMethods(flags))
		{
			var ps = m.GetParameters();
			if (ps.Length != 1 || ps[0].ParameterType != typeof(string)) continue;
			if ((m.ReturnType?.Name ?? "").IndexOf("List", StringComparison.Ordinal) < 0) continue;
			try
			{
				var list = m.Invoke(mgr, new object[] { sid });
				var cm = list?.GetType().GetMethod("get_Count", flags, null, Type.EmptyTypes, null);
				if (cm != null) count = Convert.ToInt32(cm.Invoke(list, null));
				var getItem = list?.GetType().GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
				if (count > 0 && getItem != null) buff = getItem.Invoke(list, new object[] { 0 });
				break;
			}
			catch { }
		}
		if (buff == null) return "count=" + count + ";null";
		var sb = new StringBuilder();
		sb.Append("count=").Append(count).Append(';');
		foreach (var m in buff.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if (m.ReturnType != typeof(int) && m.ReturnType != typeof(bool) && m.ReturnType != typeof(float)) continue;
			if (!m.Name.StartsWith("get_", StringComparison.Ordinal) && !m.Name.StartsWith("prop_", StringComparison.Ordinal)) continue;
			try { sb.Append(m.Name).Append('=').Append(m.Invoke(buff, null)).Append(';'); } catch { }
		}
		foreach (var p in buff.GetType().GetProperties(flags))
		{
			if (p.GetIndexParameters().Length != 0) continue;
			if (p.PropertyType != typeof(int) && p.PropertyType != typeof(bool) && p.PropertyType != typeof(float)) continue;
			try { sb.Append("P:").Append(p.Name).Append('=').Append(p.GetValue(buff)).Append(';'); } catch { }
		}
		return sb.ToString();
	}

	static Unit FindUnit()
	{
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var mod = FindAsm("OfflineUnlockMod");
			var reg = mod?.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry");
			var snap = reg?.GetMethod("SnapshotUnits", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
			var list = snap?.Invoke(null, new object[] { 64 });
			if (list is System.Collections.IEnumerable en)
			{
				foreach (var item in en)
				{
					var f = item.GetType().GetField("Unit", flags);
					var raw = f?.GetValue(item);
					if (raw is Unit u) return u;
					if (raw != null) try { return (Unit)raw; } catch { }
				}
			}
		}
		catch { }
		var queues = Object.FindObjectsOfType<BhBattleQueueView>(true);
		if (queues != null)
		{
			foreach (var q in queues)
			{
				if (q == null) continue;
				foreach (var f in q.GetType().GetFields(flags))
					if (f.GetValue(q) is Unit u) return u;
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
