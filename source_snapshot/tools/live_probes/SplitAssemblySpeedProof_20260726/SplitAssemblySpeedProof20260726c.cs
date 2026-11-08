using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

/// <summary>
/// Mid-combat: apply haste, dump numeric members before/after, try UnitStat refresh paths.
/// Assembly: SplitAssemblySpeedProof20260726c
/// </summary>
public static class SplitAssemblySpeedProof20260726c
{
	private const string HasteExactSid = "magic_haste_effect_1";
	private const string CustomSpeedSid = "homm3_factory_split_assembly_speed_1";

	public static string Run(string requestJson)
	{
		try
		{
			var mod = FindAssembly("OfflineUnlockMod");
			var adapterType = mod?.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter", false);
			var addMethod = ResolveAddMethod(adapterType);
			var queryOne = adapterType?.GetMethod("TryRequireBuffSidFromReceiver", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (addMethod == null || queryOne == null)
				return Fail("adapter missing");

			var units = CollectUnits(out var note);
			if (units.Count == 0)
				return Fail("no units: " + note);
			var unit = units[0];
			var mode = ReadString(requestJson, "mode") ?? "snapshot_apply_haste";

			var before = CaptureNumericMap(unit, "before");
			string applySid = null;
			var addOk = false;
			string addFail = null;
			if (!string.Equals(mode, "snapshot_only", StringComparison.OrdinalIgnoreCase))
			{
				applySid = string.Equals(mode, "apply_custom", StringComparison.OrdinalIgnoreCase) ? CustomSpeedSid : HasteExactSid;
				var args = new object[] { unit, applySid, unit, 1, 99, 1, true, null, null };
				try
				{
					addOk = addMethod.Invoke(null, args) is bool b && b;
					addFail = args[8]?.ToString();
				}
				catch (Exception ex)
				{
					addFail = ex.GetBaseException().GetType().Name + ": " + ex.GetBaseException().Message;
				}
			}

			var afterAdd = CaptureNumericMap(unit, "afterAdd");
			var refreshLog = TryRefreshUnitStats(unit);
			var afterRefresh = CaptureNumericMap(unit, "afterRefresh");
			var changed = DiffMaps(before, afterRefresh);

			var q = QuerySid(queryOne, unit, applySid ?? HasteExactSid);

			return "{"
			       + "\"ok\":true"
			       + ",\"mode\":" + Json(mode)
			       + ",\"collectNote\":" + Json(note)
			       + ",\"applySid\":" + Json(applySid)
			       + ",\"addOk\":" + (addOk ? "true" : "false")
			       + ",\"addFail\":" + Json(addFail)
			       + ",\"buffQuery\":" + q
			       + ",\"refreshLog\":" + Json(refreshLog)
			       + ",\"before\":" + before
			       + ",\"afterAdd\":" + afterAdd
			       + ",\"afterRefresh\":" + afterRefresh
			       + ",\"changed\":" + changed
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static string TryRefreshUnitStats(Unit unit)
	{
		var log = new StringBuilder();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		// Prefer methods that take no args and return UnitStat or void with Stat in name.
		foreach (var method in unit.GetType().GetMethods(flags))
		{
			var name = method.Name ?? "";
			var ps = method.GetParameters();
			var interesting = name.IndexOf("Stat", StringComparison.OrdinalIgnoreCase) >= 0
			                  || name.IndexOf("Refresh", StringComparison.OrdinalIgnoreCase) >= 0
			                  || name.IndexOf("Recalc", StringComparison.OrdinalIgnoreCase) >= 0
			                  || name.IndexOf("bbfa", StringComparison.OrdinalIgnoreCase) >= 0
			                  || name.IndexOf("bbfb", StringComparison.OrdinalIgnoreCase) >= 0;
			if (!interesting)
				continue;
			if (ps.Length > 2)
				continue;
			try
			{
				object[] args = null;
				if (ps.Length == 0)
					args = Array.Empty<object>();
				else if (ps.Length == 1 && ps[0].ParameterType == typeof(bool))
					args = new object[] { true };
				else if (ps.Length == 2 && ps[0].ParameterType == typeof(bool) && ps[1].ParameterType == typeof(bool))
					args = new object[] { true, true };
				else
					continue;
				method.Invoke(unit, args);
				log.Append(name).Append("(ok);");
			}
			catch (Exception ex)
			{
				log.Append(name).Append("(ERR:").Append(ex.GetBaseException().GetType().Name).Append(");");
			}
		}

		// Buff manager Unit hooks: dzv.bbfa(Unit)/bbfb(Unit)
		try
		{
			var mgr = ReadBuffManager(unit);
			if (mgr != null)
			{
				foreach (var method in mgr.GetType().GetMethods(flags))
				{
					var ps = method.GetParameters();
					if (ps.Length != 1 || !ps[0].ParameterType.IsInstanceOfType(unit))
						continue;
					if (method.ReturnType != typeof(void))
						continue;
					var name = method.Name ?? "";
					if (!(name.Contains("Unit") || name.StartsWith("Method_Public_Void_Unit", StringComparison.Ordinal)))
						continue;
					try
					{
						method.Invoke(mgr, new object[] { unit });
						log.Append("mgr.").Append(name).Append("(ok);");
					}
					catch (Exception ex)
					{
						log.Append("mgr.").Append(name).Append("(ERR:").Append(ex.GetBaseException().GetType().Name).Append(");");
					}
				}
			}
			else
				log.Append("mgr=null;");
		}
		catch (Exception ex)
		{
			log.Append("mgrScan=").Append(ex.GetType().Name).Append(';');
		}
		return log.ToString();
	}

	private static object ReadBuffManager(object unit)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[]
		         {
			         "cnyb", "bbds", "get__cfnh_k__BackingField",
			         "Method_Public_Virtual_Final_New_get_ObjectPublicDi2StLi1ObceInLi1Unique_0",
			         "get_field_Private_ObjectPublicDi2StLi1ObceInLi1Unique_0"
		         })
		{
			try
			{
				var t = unit.GetType();
				var m = t.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m != null)
				{
					var v = m.Invoke(unit, null);
					if (v != null)
						return v;
				}
				var p = t.GetProperty(name, flags);
				if (p != null)
				{
					var v = p.GetValue(unit, null);
					if (v != null)
						return v;
				}
				var f = t.GetField(name, flags);
				if (f != null)
				{
					var v = f.GetValue(unit);
					if (v != null)
						return v;
				}
			}
			catch
			{
			}
		}
		foreach (var m in unit.GetType().GetMethods(flags))
		{
			if (m.GetParameters().Length != 0)
				continue;
			var rt = m.ReturnType?.Name ?? "";
			if (rt.Contains("Di2StLi1") || rt.Contains("Buff"))
			{
				try
				{
					var v = m.Invoke(unit, null);
					if (v != null)
						return v;
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static string CaptureNumericMap(object root, string label)
	{
		var map = new SortedDictionary<string, string>(StringComparer.Ordinal);
		WalkNumeric(root, "unit", map, 0, 3);
		var sb = new StringBuilder();
		sb.Append('{');
		var first = true;
		foreach (var kv in map)
		{
			if (!first)
				sb.Append(',');
			first = false;
			sb.Append(Json(kv.Key)).Append(':').Append(kv.Value);
		}
		sb.Append('}');
		return sb.ToString();
	}

	private static void WalkNumeric(object obj, string path, SortedDictionary<string, string> map, int depth, int maxDepth)
	{
		if (obj == null || depth > maxDepth || map.Count > 120)
			return;
		var type = obj.GetType();
		if (type == typeof(string) || type.IsPrimitive || type.IsEnum)
			return;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in type.GetMethods(flags))
		{
			if (method.IsSpecialName || method.GetParameters().Length != 0)
				continue;
			if (!IsNumeric(method.ReturnType))
				continue;
			var name = method.Name ?? "";
			if (!(name.StartsWith("get_", StringComparison.Ordinal)
			      || name.IndexOf("speed", StringComparison.OrdinalIgnoreCase) >= 0
			      || name.IndexOf("Speed", StringComparison.Ordinal) >= 0
			      || name.IndexOf("initiative", StringComparison.OrdinalIgnoreCase) >= 0
			      || name.IndexOf("Initiative", StringComparison.Ordinal) >= 0
			      || name.IndexOf("attack", StringComparison.OrdinalIgnoreCase) >= 0
			      || name.IndexOf("defense", StringComparison.OrdinalIgnoreCase) >= 0
			      || name.IndexOf("Stat", StringComparison.OrdinalIgnoreCase) >= 0))
				continue;
			try
			{
				var raw = method.Invoke(obj, null);
				map[path + "." + name] = Convert.ToDouble(raw, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture);
			}
			catch
			{
			}
		}

		if (depth >= maxDepth)
			return;
		foreach (var name in new[] { "stats", "get_stats", "get_field_Private_UnitStat_0", "Method_Public_get_UnitStat_0", "Method_Public_get_UnitStat_1", "Method_Public_Virtual_UnitStat_0" })
		{
			try
			{
				object child = null;
				var m = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m != null)
					child = m.Invoke(obj, null);
				else
				{
					var p = type.GetProperty(name, flags);
					if (p != null)
						child = p.GetValue(obj, null);
					else
					{
						var f = type.GetField(name, flags);
						if (f != null)
							child = f.GetValue(obj);
					}
				}
				if (child != null && !ReferenceEquals(child, obj))
					WalkNumeric(child, path + "." + name, map, depth + 1, maxDepth);
			}
			catch
			{
			}
		}
	}

	private static string DiffMaps(string beforeJson, string afterJson)
	{
		// Lightweight: report keys that appear in both dumps via probe-side compare already done in maps — parse simply.
		try
		{
			var before = ParseFlat(beforeJson);
			var after = ParseFlat(afterJson);
			var sb = new StringBuilder();
			sb.Append('{');
			var first = true;
			foreach (var key in after.Keys)
			{
				if (!before.TryGetValue(key, out var b))
					continue;
				if (before[key] == after[key])
					continue;
				if (!first)
					sb.Append(',');
				first = false;
				sb.Append(Json(key)).Append(":{\"from\":").Append(b).Append(",\"to\":").Append(after[key]).Append('}');
			}
			sb.Append('}');
			return sb.ToString();
		}
		catch
		{
			return "{}";
		}
	}

	private static Dictionary<string, string> ParseFlat(string json)
	{
		var map = new Dictionary<string, string>(StringComparer.Ordinal);
		if (string.IsNullOrEmpty(json) || json.Length < 2)
			return map;
		var i = 1;
		while (i < json.Length)
		{
			while (i < json.Length && (json[i] == ',' || char.IsWhiteSpace(json[i]) || json[i] == '{'))
				i++;
			if (i >= json.Length || json[i] == '}')
				break;
			if (json[i] != '"')
				break;
			i++;
			var key = new StringBuilder();
			while (i < json.Length && json[i] != '"')
				key.Append(json[i++]);
			i++; // "
			while (i < json.Length && json[i] != ':')
				i++;
			i++;
			while (i < json.Length && char.IsWhiteSpace(json[i]))
				i++;
			var val = new StringBuilder();
			while (i < json.Length && json[i] != ',' && json[i] != '}')
				val.Append(json[i++]);
			map[key.ToString()] = val.ToString().Trim();
		}
		return map;
	}

	private static List<Unit> CollectUnits(out string note)
	{
		var list = new List<Unit>();
		var seen = new HashSet<int>();
		var notes = new List<string>();
		var queues = Object.FindObjectsOfType<BhBattleQueueView>(true);
		notes.Add("queueCount=" + (queues == null ? 0 : queues.Length));
		if (queues != null)
		{
			foreach (var q in queues)
			{
				if (q == null)
					continue;
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
				foreach (var m in typeof(BhBattleQueueView).GetMethods(flags))
				{
					if (m.GetParameters().Length != 0)
						continue;
					try
					{
						if (m.ReturnType == typeof(Unit))
							TryAdd(list, seen, m.Invoke(q, null) as Unit);
						else if (typeof(IEnumerable).IsAssignableFrom(m.ReturnType))
						{
							var raw = m.Invoke(q, null) as IEnumerable;
							if (raw == null)
								continue;
							foreach (var item in raw)
							{
								if (item is Unit u)
									TryAdd(list, seen, u);
							}
						}
					}
					catch
					{
					}
				}
				foreach (var f in typeof(BhBattleQueueView).GetFields(flags))
				{
					try
					{
						if (f.GetValue(q) is Unit u)
							TryAdd(list, seen, u);
					}
					catch
					{
					}
				}
			}
		}
		note = string.Join(";", notes) + ";n=" + list.Count;
		return list;
	}

	private static void TryAdd(List<Unit> list, HashSet<int> seen, Unit unit)
	{
		if (unit == null)
			return;
		var key = unit.GetHashCode();
		if (!seen.Add(key))
			return;
		list.Add(unit);
	}

	private static MethodInfo ResolveAddMethod(Type adapterType)
	{
		if (adapterType == null)
			return null;
		foreach (var method in adapterType.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (method.Name != "TryAddBuffSidFromReceiver")
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 9 && ps[7].ParameterType.IsByRef && ps[8].ParameterType.IsByRef)
				return method;
		}
		return null;
	}

	private static string QuerySid(MethodInfo queryOne, object unit, string sid)
	{
		var args = new object[] { unit, sid, null, null };
		try
		{
			var ok = queryOne.Invoke(null, args) is bool b && b;
			return "{\"ok\":" + (ok ? "true" : "false") + ",\"info\":" + Json(args[2]?.ToString()) + ",\"fail\":" + Json(args[3]?.ToString()) + "}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"fail\":" + Json(ex.GetBaseException().Message) + "}";
		}
	}

	private static bool IsNumeric(Type t)
	{
		return t == typeof(int) || t == typeof(float) || t == typeof(double) || t == typeof(short) || t == typeof(byte) || t == typeof(long);
	}

	private static Assembly FindAssembly(string name)
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
			if (string.Equals(asm.GetName().Name, name, StringComparison.OrdinalIgnoreCase))
				return asm;
		return null;
	}

	private static string ReadString(string json, string key)
	{
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return null;
		var needle = "\"" + key + "\"";
		var idx = json.IndexOf(needle, StringComparison.Ordinal);
		if (idx < 0)
			return null;
		var colon = json.IndexOf(':', idx + needle.Length);
		if (colon < 0)
			return null;
		var i = colon + 1;
		while (i < json.Length && char.IsWhiteSpace(json[i]))
			i++;
		if (i >= json.Length || json[i] != '"')
			return null;
		i++;
		var sb = new StringBuilder();
		while (i < json.Length)
		{
			var c = json[i++];
			if (c == '\\' && i < json.Length)
			{
				sb.Append(json[i++]);
				continue;
			}
			if (c == '"')
				break;
			sb.Append(c);
		}
		return sb.ToString();
	}

	private static string Fail(string message)
	{
		return "{\"ok\":false,\"error\":" + Json(message) + "}";
	}

	private static string Json(string value)
	{
		if (value == null)
			return "null";
		return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r") + "\"";
	}
}
