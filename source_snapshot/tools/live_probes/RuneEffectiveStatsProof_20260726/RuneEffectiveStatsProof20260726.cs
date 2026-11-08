using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using Hex.Session.Battle;
using UnityEngine;
using Object = UnityEngine.Object;

/// <summary>
/// Mid-combat proof: TryAddBuffSidFromReceiver for Bulwark Rune threshold SIDs must
/// move Unit.get_stats() via Homm3BuffDebuffNativeAdapter additive fold (no manual
/// set_speed). Modes: apply_offence (level_1), apply_defence (level_2), apply_speed
/// (level_3), apply_ladder (1 then 2 then 3).
/// Assembly: RuneEffectiveStatsProof20260726
/// </summary>
public static class RuneEffectiveStatsProof20260726
{
	public static string Run(string requestJson)
	{
		try
		{
			var findDiag = new StringBuilder();
			var unit = FindUnit(findDiag);
			if (unit == null)
				return Fail("no unit", findDiag.ToString());

			var mode = ReadString(requestJson, "mode") ?? "apply_speed";
			string[] sids;
			switch ((mode ?? "").ToLowerInvariant())
			{
				case "apply_offence":
					sids = new[] { "homm3_bulwark_rune_level_1" };
					break;
				case "apply_defence":
					sids = new[] { "homm3_bulwark_rune_level_2" };
					break;
				case "apply_ladder":
					sids = new[]
					{
						"homm3_bulwark_rune_level_1",
						"homm3_bulwark_rune_level_2",
						"homm3_bulwark_rune_level_3",
					};
					break;
				default:
					mode = "apply_speed";
					sids = new[] { "homm3_bulwark_rune_level_3" };
					break;
			}

			var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			var before = Capture(unit, flags);
			var add = ResolveAddMethod();
			if (add == null)
				return Fail("TryAddBuffSidFromReceiver missing", findDiag.ToString());

			var steps = new StringBuilder();
			steps.Append('[');
			for (var i = 0; i < sids.Length; i++)
			{
				if (i > 0)
					steps.Append(',');
				var sid = sids[i];
				var args = new object[] { unit, sid, unit, Math.Max(1, i + 1), 99, 1, false, null, null };
				var ok = false;
				string fail = null;
				try
				{
					ok = add.Invoke(null, args) is bool b && b;
					fail = args[8]?.ToString();
				}
				catch (Exception ex)
				{
					fail = ex.GetBaseException().GetType().Name + ":" + ex.GetBaseException().Message;
				}
				steps.Append('{')
					.Append("\"sid\":").Append(Json(sid))
					.Append(",\"addOk\":").Append(ok ? "true" : "false")
					.Append(",\"addFail\":").Append(Json(fail))
					.Append('}');
			}
			steps.Append(']');

			var after = Capture(unit, flags);
			var expectedOff = before.offence + ExpectedOffence(mode);
			var expectedDef = before.defence + ExpectedDefence(mode);
			var expectedSpd = before.speed + ExpectedSpeed(mode);
			var proof = after.offence == expectedOff
			            && after.defence == expectedDef
			            && after.speed == expectedSpd;

			return "{"
			       + "\"ok\":true"
			       + ",\"mode\":" + Json(mode)
			       + ",\"find\":" + Json(findDiag.ToString())
			       + ",\"steps\":" + steps
			       + ",\"before\":" + before.Json
			       + ",\"after\":" + after.Json
			       + ",\"expected\":{\"offence\":" + expectedOff
			       + ",\"defence\":" + expectedDef
			       + ",\"speed\":" + expectedSpd + "}"
			       + ",\"proof\":" + (proof ? "true" : "false")
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ":" + ex.Message, null);
		}
	}

	private static int ExpectedOffence(string mode)
	{
		if (mode == "apply_offence" || mode == "apply_ladder")
			return 2;
		return 0;
	}

	private static int ExpectedDefence(string mode)
	{
		if (mode == "apply_defence" || mode == "apply_ladder")
			return 2;
		return 0;
	}

	private static int ExpectedSpeed(string mode)
	{
		if (mode == "apply_speed" || mode == "apply_ladder")
			return 1;
		return 0;
	}

	private static MethodInfo ResolveAddMethod()
	{
		var mod = FindAsm("OfflineUnlockMod");
		var adapter = mod?.GetType("OfflineUnlockMod.Homm3BuffDebuffNativeAdapter", false);
		if (adapter == null)
			return null;
		foreach (var m in adapter.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (m.Name != "TryAddBuffSidFromReceiver")
				continue;
			var ps = m.GetParameters();
			if (ps.Length == 9 && ps[7].ParameterType.IsByRef)
				return m;
		}
		return null;
	}

	private static StatsCapture Capture(object unit, BindingFlags flags)
	{
		var stats = unit.GetType().GetMethod("get_stats", flags, null, Type.EmptyTypes, null).Invoke(unit, null);
		return new StatsCapture(
			GetInt(stats, "get_offence"),
			GetInt(stats, "get_defence"),
			GetInt(stats, "get_speed"));
	}

	private static int GetInt(object o, string getter)
	{
		var m = o.GetType().GetMethod(getter, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		return Convert.ToInt32(m.Invoke(o, null), CultureInfo.InvariantCulture);
	}

	private static Unit FindUnit(StringBuilder diag)
	{
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var mod = FindAsm("OfflineUnlockMod");
			diag.Append("mod=").Append(mod != null).Append(';');
			var reg = mod?.GetType("OfflineUnlockMod.Homm3BattleUnitLawOwnerRegistry");
			var snap = reg?.GetMethod("SnapshotUnits", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
			if (snap != null)
			{
				var list = snap.Invoke(null, new object[] { 64 });
				if (list is System.Collections.IEnumerable en)
				{
					foreach (var item in en)
					{
						if (item == null)
							continue;
						foreach (var f in item.GetType().GetFields(flags))
						{
							if (f.Name != "Unit")
								continue;
							var raw = f.GetValue(item);
							if (raw is Unit u)
								return u;
						}
					}
				}
			}
		}
		catch (Exception ex)
		{
			diag.Append("regERR=").Append(ex.GetType().Name).Append(';');
		}

		var queues = Object.FindObjectsOfType<BhBattleQueueView>(true);
		diag.Append("queues=").Append(queues?.Length ?? -1).Append(';');
		if (queues != null)
		{
			foreach (var q in queues)
			{
				if (q == null)
					continue;
				foreach (var f in q.GetType().GetFields(flags))
					if (f.GetValue(q) is Unit u)
						return u;
			}
		}
		return null;
	}

	private static Assembly FindAsm(string name)
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (string.Equals(asm.GetName().Name, name, StringComparison.Ordinal))
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
		idx = json.IndexOf(':', idx);
		if (idx < 0)
			return null;
		idx++;
		while (idx < json.Length && char.IsWhiteSpace(json[idx]))
			idx++;
		if (idx >= json.Length || json[idx] != '"')
			return null;
		idx++;
		var end = json.IndexOf('"', idx);
		if (end < 0)
			return null;
		return json.Substring(idx, end - idx);
	}

	private static string Json(string value)
	{
		if (value == null)
			return "null";
		return "\"" + value.Replace("\\", "/").Replace("\"", "'") + "\"";
	}

	private static string Fail(string error, string find)
	{
		return "{\"ok\":false,\"error\":" + Json(error) + ",\"find\":" + Json(find) + "}";
	}

	private readonly struct StatsCapture
	{
		internal readonly int offence;
		internal readonly int defence;
		internal readonly int speed;
		internal readonly string Json;

		internal StatsCapture(int offence, int defence, int speed)
		{
			this.offence = offence;
			this.defence = defence;
			this.speed = speed;
			Json = "{\"offence\":" + offence + ",\"defence\":" + defence + ",\"speed\":" + speed + "}";
		}
	}
}
