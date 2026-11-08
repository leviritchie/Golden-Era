using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

public static class SpeedReadProbe20260726i
{
	public static string Run(string requestJson)
	{
		try
		{
			var unit = FindUnit();
			if (unit == null) return "{\"ok\":false,\"error\":\"no unit\"}";
			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var before = SpeedOf(GetStats(unit, flags));
			var notes = new StringBuilder();

			// 1) Direct mutate get_stats.speed via setter if any — proves UI metric.
			var stats = GetStats(unit, flags);
			var setSpeed = stats?.GetType().GetMethod("set_speed", flags, null, new[] { typeof(int) }, null)
				?? stats?.GetType().GetMethod("set_speed", flags, null, new[] { typeof(float) }, null);
			var speedField = FindSpeedField(stats);
			notes.Append("set_speed=").Append(setSpeed != null ? setSpeed.ToString() : "MISS").Append(';');
			notes.Append("speedField=").Append(speedField != null ? speedField.Name + ":" + speedField.FieldType.Name : "MISS").Append(';');

			if (requestJson != null && requestJson.IndexOf("mutate", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				if (setSpeed != null)
				{
					var pt = setSpeed.GetParameters()[0].ParameterType;
					object nv = pt == typeof(float) || pt == typeof(double) ? (object)(before + 4f) : (object)(before + 4);
					setSpeed.Invoke(stats, new[] { nv });
				}
				else if (speedField != null)
				{
					if (speedField.FieldType == typeof(int)) speedField.SetValue(stats, before + 4);
					else if (speedField.FieldType == typeof(float)) speedField.SetValue(stats, before + 4f);
				}
				notes.Append("mutatedDirect;");
			}

			// 2) Try UnitStat merge helpers: methods on UnitStat taking UnitStat
			if (stats != null && requestJson != null && requestJson.IndexOf("merge", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				var delta = BuildDeltaFromHasteConfig(unit, flags, notes);
				if (delta != null)
				{
					foreach (var m in stats.GetType().GetMethods(flags))
					{
						var ps = m.GetParameters();
						if (ps.Length != 1 || ps[0].ParameterType.Name != "UnitStat") continue;
						if (m.ReturnType != typeof(void) && m.ReturnType.Name != "UnitStat") continue;
						try
						{
							var ret = m.Invoke(stats, new object[] { delta });
							notes.Append("merge:").Append(m.Name).Append("=>speed=").Append(SpeedOf(ret ?? stats)).Append(';');
						}
						catch (Exception ex)
						{
							notes.Append("merge:").Append(m.Name).Append("=ERR:").Append(ex.GetType().Name).Append(';');
						}
					}
					// also try unit methods taking UnitStat
					foreach (var m in unit.GetType().GetMethods(flags))
					{
						var ps = m.GetParameters();
						if (ps.Length != 1 || ps[0].ParameterType.Name != "UnitStat") continue;
						if (m.ReturnType != typeof(void) && m.ReturnType.Name != "UnitStat") continue;
						try
						{
							var ret = m.Invoke(unit, new object[] { delta });
							notes.Append("unitMerge:").Append(m.Name).Append("=>").Append(ret == null ? "void" : ret.GetType().Name).Append("/speed=").Append(SpeedOf(GetStats(unit, flags))).Append(';');
						}
						catch (Exception ex)
						{
							notes.Append("unitMerge:").Append(m.Name).Append("=ERR:").Append(ex.GetType().Name).Append(';');
						}
					}
				}
			}

			// 3) Call zero-arg void methods on unit whose name suggests refresh/recalc (bounded)
			if (requestJson != null && requestJson.IndexOf("voidrefresh", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				var n = 0;
				foreach (var m in unit.GetType().GetMethods(flags))
				{
					if (m.GetParameters().Length != 0 || m.ReturnType != typeof(void)) continue;
					var name = m.Name;
					if (!(name.Contains("PDM") || name.Contains("Void_0") || name.Contains("Void_1") || name.Contains("Void_2")))
						continue;
					if (n++ > 40) break;
					var sp0 = SpeedOf(GetStats(unit, flags));
					try
					{
						m.Invoke(unit, null);
						var sp1 = SpeedOf(GetStats(unit, flags));
						if (sp1 != sp0) notes.Append("VOIDHIT:").Append(name).Append(':').Append(sp0).Append("->").Append(sp1).Append(';');
						else notes.Append("void:").Append(name).Append("=same;");
					}
					catch
					{
						notes.Append("void:").Append(name).Append("=ERR;");
					}
				}
			}

			var after = SpeedOf(GetStats(unit, flags));
			return "{"
				+ "\"ok\":true"
				+ ",\"before\":" + before
				+ ",\"after\":" + after
				+ ",\"delta\":" + (after - before)
				+ ",\"notes\":\"" + notes.ToString().Replace("\\", "/").Replace("\"", "'") + "\""
				+ "}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + ex.GetType().Name + ":" + ex.Message.Replace("\\", "/").Replace("\"", "'") + "\"}";
		}
	}

	static object BuildDeltaFromHasteConfig(object unit, BindingFlags flags, StringBuilder notes)
	{
		// Ensure haste present, then read config.data.stats
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
		add.Invoke(null, args);

		object mgr = null;
		foreach (var m in unit.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0) continue;
			if ((m.ReturnType?.Name ?? "").IndexOf("Di2StLi1", StringComparison.Ordinal) < 0) continue;
			try { mgr = m.Invoke(unit, null); if (mgr != null) break; } catch { }
		}
		if (mgr == null) { notes.Append("noMgr;"); return null; }
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
		if (buff == null) { notes.Append("noBuff;"); return null; }
		object cfg = buff.GetType().GetProperty("config", flags)?.GetValue(buff);
		object data = cfg?.GetType().GetProperty("data", flags)?.GetValue(cfg);
		object delta = data?.GetType().GetProperty("stats", flags)?.GetValue(data);
		notes.Append("deltaSpeed=").Append(SpeedOf(delta)).Append(';');
		return delta;
	}

	static FieldInfo FindSpeedField(object stats)
	{
		if (stats == null) return null;
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var f in stats.GetType().GetFields(flags))
		{
			if (f.Name.IndexOf("speed", StringComparison.OrdinalIgnoreCase) >= 0
			    && (f.FieldType == typeof(int) || f.FieldType == typeof(float)))
				return f;
		}
		// backing field heuristics
		foreach (var f in stats.GetType().GetFields(flags))
		{
			if (f.Name.IndexOf("Speed", StringComparison.OrdinalIgnoreCase) >= 0
			    && (f.FieldType == typeof(int) || f.FieldType == typeof(float)))
				return f;
		}
		return null;
	}

	static object GetStats(object unit, BindingFlags flags)
	{
		return unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null)?.Invoke(unit, null);
	}

	static int SpeedOf(object stats)
	{
		if (stats == null) return -999;
		var m = stats.GetType().GetMethod("get_speed", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		if (m == null) return -998;
		try { return Convert.ToInt32(m.Invoke(stats, null)); }
		catch { return -997; }
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
