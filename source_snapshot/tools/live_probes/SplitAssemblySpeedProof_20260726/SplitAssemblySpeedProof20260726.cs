using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

/// <summary>
/// Live proof mid-combat: enumerate Units via BhBattleQueueView + law-owner registry,
/// read get_speed, query Split Assembly / haste buffs, apply haste or custom speed SID,
/// re-read speed. Hot-loaded via volatile_load_probe_assembly (no OfflineUnlockMod deploy).
/// </summary>
public static class SplitAssemblySpeedProof20260726
{
	private const string CustomSpeedSid = "homm3_factory_split_assembly_speed_1";
	private const string CustomInitiativeSid = "homm3_factory_split_assembly_initiative_1";
	private const string HasteBaseSid = "magic_haste_effect";
	private const string HasteExactSid = "magic_haste_effect_1";

	public static string Run(string requestJson)
	{
		try
		{
			var mod = FindAssembly("OfflineUnlockMod");
			if (mod == null)
				return Fail("OfflineUnlockMod assembly not loaded");

			var adapterType = mod.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter", false);
			if (adapterType == null)
				return Fail("Homm3BuffDebuffNativeAdapter not found");

			var queryOne = adapterType.GetMethod(
				"TryRequireBuffSidFromReceiver",
				BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			var addMethod = ResolveAddMethod(adapterType);
			if (queryOne == null || addMethod == null)
				return Fail("buff adapter query/add methods missing");

			var mode = ReadString(requestJson, "mode") ?? "diagnose";
			var units = CollectUnits(out var collectNote);
			if (units.Count == 0)
				return Fail("no Units found (" + collectNote + ")");

			var rows = new List<string>(units.Count);
			Unit target = null;
			var targetScore = int.MinValue;
			for (var i = 0; i < units.Count; i++)
			{
				var unit = units[i];
				if (unit == null)
					continue;
				var sid = TryReadSid(unit);
				var speed = TryReadSpeed(unit);
				var customSpeed = QuerySid(queryOne, unit, CustomSpeedSid);
				var customInit = QuerySid(queryOne, unit, CustomInitiativeSid);
				var hasteExact = QuerySid(queryOne, unit, HasteExactSid);
				var score = 0;
				if (customSpeed.HasSid)
					score += 20;
				if (!string.IsNullOrEmpty(sid) && sid.StartsWith("h3_", StringComparison.Ordinal))
					score += 5;
				if (speed.Known)
					score += 1;
				if (score > targetScore)
				{
					targetScore = score;
					target = unit;
				}
				rows.Add("{"
				         + "\"index\":" + i
				         + ",\"sid\":" + Json(sid)
				         + ",\"speedKnown\":" + (speed.Known ? "true" : "false")
				         + ",\"speed\":" + (speed.Known ? Fmt(speed.Value) : "null")
				         + ",\"speedMember\":" + Json(speed.Member)
				         + ",\"customSpeed\":" + customSpeed.ToJson()
				         + ",\"customInitiative\":" + customInit.ToJson()
				         + ",\"hasteExact\":" + hasteExact.ToJson()
				         + "}");
			}

			if (string.Equals(mode, "diagnose", StringComparison.OrdinalIgnoreCase))
			{
				return "{"
				       + "\"ok\":true"
				       + ",\"mode\":\"diagnose\""
				       + ",\"collectNote\":" + Json(collectNote)
				       + ",\"unitCount\":" + units.Count
				       + ",\"rows\":[" + string.Join(",", rows) + "]"
				       + "}";
			}

			if (target == null)
				return Fail("no suitable Unit target");

			string applySid;
			int level;
			if (string.Equals(mode, "apply_haste", StringComparison.OrdinalIgnoreCase))
			{
				applySid = HasteBaseSid;
				level = 1;
			}
			else if (string.Equals(mode, "apply_haste_exact", StringComparison.OrdinalIgnoreCase))
			{
				applySid = HasteExactSid;
				level = 1;
			}
			else if (string.Equals(mode, "apply_custom_speed", StringComparison.OrdinalIgnoreCase))
			{
				applySid = CustomSpeedSid;
				level = 1;
			}
			else
				return Fail("mode must be diagnose|apply_haste|apply_haste_exact|apply_custom_speed");

			var beforeSpeed = TryReadSpeed(target);
			var beforeCustom = QuerySid(queryOne, target, CustomSpeedSid);
			var beforeHaste = QuerySid(queryOne, target, HasteExactSid);

			var addArgs = new object[] { target, applySid, target, level, 99, 1, true, null, null };
			var addOk = false;
			string addEx = null;
			try
			{
				var raw = addMethod.Invoke(null, addArgs);
				addOk = raw is bool b && b;
			}
			catch (Exception ex)
			{
				var root = ex is TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : ex;
				addEx = root.GetType().Name + ": " + root.Message;
			}

			var afterSpeed = TryReadSpeed(target);
			var afterCustom = QuerySid(queryOne, target, CustomSpeedSid);
			var afterApplied = QuerySid(queryOne, target, applySid);
			var afterHasteExact = QuerySid(queryOne, target, HasteExactSid);
			int? delta = null;
			if (beforeSpeed.Known && afterSpeed.Known)
				delta = afterSpeed.Value - beforeSpeed.Value;

			return "{"
			       + "\"ok\":true"
			       + ",\"mode\":" + Json(mode)
			       + ",\"collectNote\":" + Json(collectNote)
			       + ",\"applySid\":" + Json(applySid)
			       + ",\"targetSid\":" + Json(TryReadSid(target))
			       + ",\"beforeSpeed\":" + SpeedJson(beforeSpeed)
			       + ",\"afterSpeed\":" + SpeedJson(afterSpeed)
			       + ",\"speedDelta\":" + (delta.HasValue ? Fmt(delta.Value) : "null")
			       + ",\"speedChanged\":" + (delta.HasValue && delta.Value != 0 ? "true" : "false")
			       + ",\"beforeCustomSpeed\":" + beforeCustom.ToJson()
			       + ",\"afterCustomSpeed\":" + afterCustom.ToJson()
			       + ",\"beforeHasteExact\":" + beforeHaste.ToJson()
			       + ",\"afterHasteExact\":" + afterHasteExact.ToJson()
			       + ",\"afterAppliedSid\":" + afterApplied.ToJson()
			       + ",\"addOk\":" + (addOk ? "true" : "false")
			       + ",\"addInfo\":" + Json(addArgs[7]?.ToString())
			       + ",\"addFailure\":" + Json(addArgs[8]?.ToString())
			       + ",\"addException\":" + Json(addEx)
			       + ",\"diagnoseRows\":[" + string.Join(",", rows) + "]"
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message + " @ " + ex.StackTrace);
		}
	}

	private static List<Unit> CollectUnits(out string note)
	{
		var list = new List<Unit>();
		var seen = new HashSet<int>();
		var notes = new List<string>();

		try
		{
			var queues = Object.FindObjectsOfType<BhBattleQueueView>(true);
			notes.Add("BhBattleQueueView.count=" + (queues == null ? 0 : queues.Length));
			if (queues != null)
			{
				foreach (var queue in queues)
				{
					if (queue == null)
						continue;
					ScanQueueInstance(list, seen, notes, queue);
				}
			}
			// Live interop may rename DiffableCs static `me`; also probe static fields.
			const BindingFlags staticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
			foreach (var field in typeof(BhBattleQueueView).GetFields(staticFlags))
			{
				if (!typeof(BhBattleQueueView).IsAssignableFrom(field.FieldType))
					continue;
				try
				{
					var queue = field.GetValue(null) as BhBattleQueueView;
					if (queue != null)
					{
						notes.Add("static." + field.Name + "=ok");
						ScanQueueInstance(list, seen, notes, queue);
					}
				}
				catch
				{
				}
			}
		}
		catch (Exception ex)
		{
			notes.Add("queueScan=" + ex.GetType().Name + ":" + ex.Message);
		}

		try
		{
			var mod = FindAssembly("OfflineUnlockMod");
			var registry = mod?.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry", false);
			var snap = registry?.GetMethod("SnapshotUnits", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (snap != null)
			{
				var snapshots = snap.Invoke(null, new object[] { 64 }) as IEnumerable;
				var n = 0;
				if (snapshots != null)
				{
					foreach (var row in snapshots)
					{
						var unitObj = row.GetType().GetField("Unit", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(row)
						              ?? row.GetType().GetProperty("Unit", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(row, null);
						if (unitObj is Unit u)
						{
							TryAddUnit(list, seen, u, "registry");
							n++;
						}
					}
				}
				notes.Add("registrySnap=" + n);
			}
			else
				notes.Add("registrySnap=missing");
		}
		catch (Exception ex)
		{
			notes.Add("registrySnap=" + ex.GetType().Name);
		}

		note = string.Join(";", notes);
		return list;
	}

	private static void ScanQueueInstance(List<Unit> list, HashSet<int> seen, List<string> notes, BhBattleQueueView queue)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in typeof(BhBattleQueueView).GetMethods(flags))
		{
			if (method.GetParameters().Length != 0 || method.IsSpecialName)
				continue;
			if (method.ReturnType == typeof(Unit))
			{
				try
				{
					TryAddUnit(list, seen, method.Invoke(queue, null) as Unit, "queue." + method.Name);
				}
				catch
				{
				}
			}
			if (typeof(IEnumerable).IsAssignableFrom(method.ReturnType) || method.ReturnType.Name.StartsWith("List", StringComparison.Ordinal))
			{
				try
				{
					var raw = method.Invoke(queue, null);
					var n = AddEnumerableUnits(list, seen, raw, "queue." + method.Name);
					if (n > 0)
						notes.Add("queue." + method.Name + "=" + n);
				}
				catch
				{
				}
			}
		}
		foreach (var prop in typeof(BhBattleQueueView).GetProperties(flags))
		{
			if (prop.GetIndexParameters().Length != 0)
				continue;
			try
			{
				if (typeof(Unit).IsAssignableFrom(prop.PropertyType))
					TryAddUnit(list, seen, prop.GetValue(queue, null) as Unit, "queueProp." + prop.Name);
				else if (typeof(IEnumerable).IsAssignableFrom(prop.PropertyType))
				{
					var n = AddEnumerableUnits(list, seen, prop.GetValue(queue, null), "queueProp." + prop.Name);
					if (n > 0)
						notes.Add("queueProp." + prop.Name + "=" + n);
				}
			}
			catch
			{
			}
		}
		foreach (var field in typeof(BhBattleQueueView).GetFields(flags))
		{
			try
			{
				var raw = field.GetValue(queue);
				if (raw is Unit u)
					TryAddUnit(list, seen, u, "queueField." + field.Name);
				else
				{
					var n = AddEnumerableUnits(list, seen, raw, "queueField." + field.Name);
					if (n > 0)
						notes.Add("queueField." + field.Name + "=" + n);
				}
			}
			catch
			{
			}
		}
	}

	private static int AddEnumerableUnits(List<Unit> list, HashSet<int> seen, object raw, string tag)
	{
		if (raw == null)
			return 0;
		var n = 0;
		if (raw is IEnumerable en && !(raw is string))
		{
			foreach (var item in en)
			{
				if (item is Unit u)
				{
					if (TryAddUnit(list, seen, u, tag))
						n++;
				}
				else if (item != null)
				{
					// Turn view wrappers often expose a Unit member.
					var unit = ReadUnitMember(item);
					if (TryAddUnit(list, seen, unit, tag))
						n++;
				}
			}
		}
		return n;
	}

	private static Unit ReadUnitMember(object obj)
	{
		if (obj == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[] { "unit", "Unit", "cgwu", "coai", "field_Public_Unit_0", "get_unit", "get_Unit" })
		{
			try
			{
				var t = obj.GetType();
				var f = t.GetField(name, flags);
				if (f != null && typeof(Unit).IsAssignableFrom(f.FieldType))
					return f.GetValue(obj) as Unit;
				var p = t.GetProperty(name, flags);
				if (p != null && typeof(Unit).IsAssignableFrom(p.PropertyType))
					return p.GetValue(obj, null) as Unit;
				var m = t.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m != null && typeof(Unit).IsAssignableFrom(m.ReturnType))
					return m.Invoke(obj, null) as Unit;
			}
			catch
			{
			}
		}
		foreach (var f in obj.GetType().GetFields(flags))
		{
			if (typeof(Unit).IsAssignableFrom(f.FieldType))
			{
				try
				{
					return f.GetValue(obj) as Unit;
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static bool TryAddUnit(List<Unit> list, HashSet<int> seen, Unit unit, string tag)
	{
		if (unit == null)
			return false;
		var key = unit.GetHashCode();
		if (!seen.Add(key))
			return false;
		list.Add(unit);
		return true;
	}

	private static MethodInfo ResolveAddMethod(Type adapterType)
	{
		foreach (var method in adapterType.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!string.Equals(method.Name, "TryAddBuffSidFromReceiver", StringComparison.Ordinal))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 9
			    && ps[0].ParameterType == typeof(object)
			    && ps[1].ParameterType == typeof(string)
			    && ps[3].ParameterType == typeof(int)
			    && ps[4].ParameterType == typeof(int)
			    && ps[5].ParameterType == typeof(int)
			    && ps[6].ParameterType == typeof(bool)
			    && ps[7].ParameterType.IsByRef
			    && ps[8].ParameterType.IsByRef)
				return method;
		}
		return null;
	}

	private static SidQuery QuerySid(MethodInfo queryOne, object unit, string sid)
	{
		var args = new object[] { unit, sid, null, null };
		try
		{
			var ok = queryOne.Invoke(null, args) is bool b && b;
			var info = args[2]?.ToString();
			var fail = args[3]?.ToString();
			var has = false;
			if (args[2] != null)
			{
				var t = args[2].GetType();
				var fi = t.GetField("HasSid", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (fi != null && fi.FieldType == typeof(bool))
					has = (bool)fi.GetValue(args[2]);
				else if (!string.IsNullOrEmpty(info) && info.IndexOf("hasSid=True", StringComparison.OrdinalIgnoreCase) >= 0)
					has = true;
			}
			return new SidQuery { QueryOk = ok || has, HasSid = has, Info = info, Fail = fail };
		}
		catch (Exception ex)
		{
			var root = ex is TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : ex;
			return new SidQuery { QueryOk = false, HasSid = false, Fail = root.GetType().Name + ": " + root.Message };
		}
	}

	private static SpeedRead TryReadSpeed(object unit)
	{
		if (unit == null)
			return default;
		var type = unit.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[] { "get_speed", "speed", "Speed", "get_Speed" })
		{
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && IsNumeric(method.ReturnType))
				{
					var raw = method.Invoke(unit, null);
					return new SpeedRead { Known = true, Value = Convert.ToInt32(raw), Member = method.Name };
				}
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0 && IsNumeric(prop.PropertyType))
				{
					var raw = prop.GetValue(unit, null);
					return new SpeedRead { Known = true, Value = Convert.ToInt32(raw), Member = "prop:" + prop.Name };
				}
				var field = type.GetField(name, flags);
				if (field != null && IsNumeric(field.FieldType))
				{
					var raw = field.GetValue(unit);
					return new SpeedRead { Known = true, Value = Convert.ToInt32(raw), Member = "field:" + field.Name };
				}
			}
			catch
			{
			}
		}

		// Also probe nested stats object.
		foreach (var statsName in new[] { "stats", "get_stats", "chju", "chjv" })
		{
			try
			{
				object stats = null;
				var m = type.GetMethod(statsName, flags, null, Type.EmptyTypes, null);
				if (m != null)
					stats = m.Invoke(unit, null);
				else
				{
					var p = type.GetProperty(statsName, flags);
					if (p != null)
						stats = p.GetValue(unit, null);
					else
					{
						var f = type.GetField(statsName, flags);
						if (f != null)
							stats = f.GetValue(unit);
					}
				}
				if (stats == null)
					continue;
				var nested = TryReadSpeed(stats);
				if (nested.Known)
				{
					nested.Member = statsName + "." + nested.Member;
					return nested;
				}
			}
			catch
			{
			}
		}
		return default;
	}

	private static bool IsNumeric(Type t)
	{
		return t == typeof(int) || t == typeof(float) || t == typeof(double) || t == typeof(short) || t == typeof(byte);
	}

	private static string TryReadSid(object unit)
	{
		if (unit == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in new[] { "configSid", "sid", "get_configSid", "get_sid", "id" })
		{
			try
			{
				var t = unit.GetType();
				var p = t.GetProperty(name, flags);
				if (p != null && p.PropertyType == typeof(string) && p.GetIndexParameters().Length == 0)
				{
					var s = p.GetValue(unit, null) as string;
					if (!string.IsNullOrWhiteSpace(s))
						return s;
				}
				var m = t.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (m != null && m.ReturnType == typeof(string))
				{
					var s = m.Invoke(unit, null) as string;
					if (!string.IsNullOrWhiteSpace(s))
						return s;
				}
				var f = t.GetField(name, flags);
				if (f != null && f.FieldType == typeof(string))
				{
					var s = f.GetValue(unit) as string;
					if (!string.IsNullOrWhiteSpace(s))
						return s;
				}
			}
			catch
			{
			}
		}
		return null;
	}

	private static Assembly FindAssembly(string name)
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (string.Equals(asm.GetName().Name, name, StringComparison.OrdinalIgnoreCase))
				return asm;
		}
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

	private static string SpeedJson(SpeedRead s)
	{
		return "{"
		       + "\"known\":" + (s.Known ? "true" : "false")
		       + ",\"value\":" + (s.Known ? Fmt(s.Value) : "null")
		       + ",\"member\":" + Json(s.Member)
		       + "}";
	}

	private static string Fmt(int v)
	{
		return v.ToString(System.Globalization.CultureInfo.InvariantCulture);
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

	private struct SpeedRead
	{
		public bool Known;
		public int Value;
		public string Member;
	}

	private struct SidQuery
	{
		public bool QueryOk;
		public bool HasSid;
		public string Info;
		public string Fail;

		public string ToJson()
		{
			return "{"
			       + "\"queryOk\":" + (QueryOk ? "true" : "false")
			       + ",\"hasSid\":" + (HasSid ? "true" : "false")
			       + ",\"info\":" + Json(Info)
			       + ",\"fail\":" + Json(Fail)
			       + "}";
		}
	}
}
