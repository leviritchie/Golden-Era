using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using Hex.Session.Data;
using Hex.Session.Hud;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

/// <summary>
/// Live proof: adventure party SIDs via field_Public_String_0 (not sid), evaluate Split
/// Assembly through OfflineUnlockMod evaluator, and draw dual meters left of heroIcon.
/// Hot-loaded; does not redeploy OfflineUnlockMod.
/// </summary>
public static class SplitAssemblyHudSidProof20260726
{
	private const string OverlayName = "HOMM3_SPLIT_ASSEMBLY_SID_PROOF";
	private const string FactorySkillSid = "skill_faction_homm3_factory";

	public static string Run(string requestJson)
	{
		try
		{
			var elements = Object.FindObjectsOfType<BhHeroUIElement>(true);
			if (elements == null || elements.Length == 0)
				return Fail("no BhHeroUIElement instances");

			BhHeroUIElement target = null;
			object sessionHero = null;
			for (var i = 0; i < elements.Length; i++)
			{
				var el = elements[i];
				if (el == null || el.gameObject == null || !el.gameObject.activeInHierarchy)
					continue;
				object hero = null;
				try { hero = el.field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0; }
				catch { hero = null; }
				if (hero == null)
					hero = ReadMember(el, "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0");
				if (hero == null)
					continue;
				target = el;
				sessionHero = hero;
				break;
			}
			if (target == null || sessionHero == null)
			{
				for (var i = 0; i < elements.Length; i++)
				{
					var el = elements[i];
					if (el == null)
						continue;
					object hero = null;
					try { hero = el.field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0; }
					catch { hero = null; }
					if (hero == null)
						hero = ReadMember(el, "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0");
					if (hero == null)
						continue;
					target = el;
					sessionHero = hero;
					break;
				}
			}
			if (target == null || sessionHero == null)
				return Fail("no BhHeroUIElement with bound session hero (scanned " + elements.Length + ")");

			object logicHero = null;
			try
			{
				var logicProp = sessionHero.GetType().GetProperty("_ciez_k__BackingField", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (logicProp != null)
					logicHero = logicProp.GetValue(sessionHero, null);
			}
			catch { }
			if (logicHero == null)
				logicHero = ReadMember(sessionHero, "_ciez_k__BackingField");
			if (logicHero == null)
				return Fail("Logic.Hero null on sessionHero type=" + sessionHero.GetType().FullName);

			object dataHeroObj = null;
			try
			{
				var dataProp = logicHero.GetType().GetProperty("_ccez_k__BackingField", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (dataProp != null)
					dataHeroObj = dataProp.GetValue(logicHero, null);
			}
			catch { }
			if (dataHeroObj == null)
				dataHeroObj = ReadMember(logicHero, "_ccez_k__BackingField");
			var dataHero = dataHeroObj as Hero;
			if (dataHero == null)
				return Fail("Data.Hero null type=" + (dataHeroObj == null ? "null" : dataHeroObj.GetType().FullName));

			var heroConfigSid = dataHero.configSid ?? "";
			var party = dataHero.party;
			if (party == null || party.units == null)
				return Fail("party/units null");

			var wrongSidHits = 0;
			var sids = new List<string>();
			var unitRows = new List<string>();
			foreach (var unit in party.units)
			{
				if (unit == null)
				{
					unitRows.Add("{\"null\":true}");
					continue;
				}

				string wrongSid = null;
				try
				{
					// Deliberately probe the broken member name the HUD used.
					wrongSid = TryReadStringMember(unit, "sid");
					if (string.IsNullOrWhiteSpace(wrongSid))
						wrongSidHits++;
				}
				catch
				{
					wrongSidHits++;
				}

				var sid = unit.field_Public_String_0;
				if (string.IsNullOrWhiteSpace(sid))
					return Fail("field_Public_String_0 empty at slotPos=" + unit.slotPos);
				sid = sid.Trim();
				sids.Add(sid);
				unitRows.Add("{"
				             + "\"slotPos\":" + unit.slotPos
				             + ",\"stacks\":" + unit.stacks
				             + ",\"field_Public_String_0\":" + Json(sid)
				             + ",\"sidMember\":" + Json(wrongSid)
				             + "}");
			}

			if (sids.Count == 0)
				return Fail("no unit SIDs from field_Public_String_0");

			if (!TryResolveFactoryRank(dataHero, out var rank, out var rankFail))
				return Fail("Factory skill resolve failed: " + rankFail);

			var naturalOverclock = HasSubSkill(dataHero, "sub_skill_faction_homm3_factory_gantry_reserve");
			var industrialOverclock = HasSubSkill(dataHero, "sub_skill_faction_homm3_factory_industrial_tempo");

			if (!TryEvaluateViaMod(sids, rank, naturalOverclock, industrialOverclock, out var snapshotJson, out var evalFail))
				return Fail("evaluator failed: " + evalFail);

			var portrait = target.heroIcon;
			if (portrait == null)
				return Fail("heroIcon null");

			EnsureOverlay(portrait.rectTransform, snapshotJson, out var overlayNote);

			return "{"
			       + "\"ok\":true"
			       + ",\"proof\":\"adventure_sid_field_Public_String_0_plus_overlay\""
			       + ",\"heroConfigSid\":" + Json(heroConfigSid)
			       + ",\"unitCount\":" + sids.Count
			       + ",\"wrongSidEmptyCount\":" + wrongSidHits
			       + ",\"units\":[" + string.Join(",", unitRows) + "]"
			       + ",\"rank\":" + rank
			       + ",\"naturalOverclock\":" + (naturalOverclock ? "true" : "false")
			       + ",\"industrialOverclock\":" + (industrialOverclock ? "true" : "false")
			       + ",\"snapshot\":" + snapshotJson
			       + ",\"overlay\":" + Json(overlayNote)
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message + " @ " + FirstProbeFrame(ex));
		}
	}

	private static void EnsureOverlay(RectTransform portraitRt, string snapshotJson, out string note)
	{
		note = null;
		var existing = portraitRt.Find(OverlayName);
		if (existing != null)
			Object.Destroy(existing.gameObject);

		ParseTiers(snapshotJson, out var naturalTier, out var industrialTier, out var rankCap);

		var rootGo = new GameObject(OverlayName);
		rootGo.transform.SetParent(portraitRt, false);
		var root = rootGo.AddComponent<RectTransform>();
		root.anchorMin = new Vector2(0f, 0.5f);
		root.anchorMax = new Vector2(0f, 0.5f);
		root.pivot = new Vector2(1f, 0.5f);
		root.sizeDelta = new Vector2(32f, Mathf.Max(48f, portraitRt.rect.height));
		root.anchoredPosition = new Vector2(-4f, 0f);
		root.SetAsLastSibling();

		var bg = rootGo.AddComponent<Image>();
		bg.color = new Color(0.12f, 0.08f, 0.05f, 0.92f);
		bg.raycastTarget = false;

		AddPipColumn(root, 0.28f, new Color(0.91f, 0.66f, 0.19f, 1f), naturalTier, rankCap);
		AddPipColumn(root, 0.72f, new Color(0.55f, 0.70f, 0.82f, 1f), industrialTier, rankCap);

		note = "created under heroIcon left; naturalTiers=" + naturalTier + " industrialTiers=" + industrialTier + " rankCap=" + rankCap;
	}

	private static void AddPipColumn(RectTransform parent, float xAnchor, Color filled, int unlocked, int rankCap)
	{
		for (var i = 0; i < 4; i++)
		{
			var go = new GameObject("pip_" + i);
			go.transform.SetParent(parent, false);
			var rt = go.AddComponent<RectTransform>();
			rt.anchorMin = new Vector2(xAnchor, 1f);
			rt.anchorMax = new Vector2(xAnchor, 1f);
			rt.pivot = new Vector2(0.5f, 0.5f);
			rt.sizeDelta = new Vector2(10f, 10f);
			rt.anchoredPosition = new Vector2(0f, -12f - i * 12f);
			var img = go.AddComponent<Image>();
			img.raycastTarget = false;
			var slot = i + 1;
			if (slot <= unlocked)
				img.color = filled;
			else if (slot <= rankCap)
				img.color = new Color(0.35f, 0.30f, 0.24f, 0.85f);
			else
				img.color = new Color(0.18f, 0.16f, 0.14f, 0.7f);
		}
	}

	private static void ParseTiers(string snapshotJson, out int naturalTiers, out int industrialTiers, out int rankCap)
	{
		naturalTiers = ReadJsonInt(snapshotJson, "NaturalTier");
		industrialTiers = ReadJsonInt(snapshotJson, "IndustrialTier");
		rankCap = ReadJsonInt(snapshotJson, "RankCap");
		if (rankCap <= 0)
			rankCap = 4;
	}

	private static bool TryEvaluateViaMod(
		List<string> sids,
		int rank,
		bool naturalOverclock,
		bool industrialOverclock,
		out string snapshotJson,
		out string fail)
	{
		snapshotJson = null;
		fail = null;
		var mod = FindAssembly("OfflineUnlockMod");
		if (mod == null)
		{
			fail = "OfflineUnlockMod not loaded";
			return false;
		}
		var evalType = mod.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyEvaluator", false);
		if (evalType == null)
		{
			fail = "evaluator type missing";
			return false;
		}
		var tryEvaluate = evalType.GetMethod(
			"TryEvaluate",
			BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
		if (tryEvaluate == null)
		{
			fail = "TryEvaluate missing";
			return false;
		}

		var args = new object[] { sids, rank, naturalOverclock, industrialOverclock, null, null };
		var ok = (bool)tryEvaluate.Invoke(null, args);
		fail = args[5] as string;
		if (!ok)
		{
			fail = fail ?? "TryEvaluate returned false";
			return false;
		}
		var snapshot = args[4];
		if (snapshot == null)
		{
			fail = "snapshot null";
			return false;
		}
		snapshotJson = SnapshotToJson(snapshot);
		return true;
	}

	private static string SnapshotToJson(object snapshot)
	{
		var t = snapshot.GetType();
		string Read(string name)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return f == null ? "null" : Json(f.GetValue(snapshot));
		}
		int ReadInt(string name)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return f != null && f.GetValue(snapshot) is int i ? i : 0;
		}
		bool ReadBool(string name)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return f != null && f.GetValue(snapshot) is bool b && b;
		}
		return "{"
		       + "\"Rank\":" + ReadInt("Rank")
		       + ",\"NaturalEffective\":" + ReadInt("NaturalEffective")
		       + ",\"IndustrialEffective\":" + ReadInt("IndustrialEffective")
		       + ",\"NaturalTier\":" + ReadInt("NaturalTier")
		       + ",\"IndustrialTier\":" + ReadInt("IndustrialTier")
		       + ",\"RankCap\":" + ReadInt("RankCap")
		       + ",\"NaturalOverclock\":" + (ReadBool("NaturalOverclock") ? "true" : "false")
		       + ",\"IndustrialOverclock\":" + (ReadBool("IndustrialOverclock") ? "true" : "false")
		       + ",\"NaturalLines\":" + Read("NaturalLines")
		       + ",\"IndustrialLines\":" + Read("IndustrialLines")
		       + "}";
	}

	private static bool TryResolveFactoryRank(Hero dataHero, out int rank, out string fail)
	{
		rank = 0;
		fail = null;
		var skills = dataHero.skills;
		if (skills == null)
		{
			fail = "skills null";
			return false;
		}
		var list = skills.list;
		if (list == null)
		{
			fail = "HeroSkills.list missing";
			return false;
		}

		foreach (var heroSkill in list)
		{
			if (heroSkill == null)
				continue;
			var sid = heroSkill.field_Public_String_0;
			if (!string.Equals(sid, FactorySkillSid, StringComparison.Ordinal))
				continue;
			rank = heroSkill.level;
			if (rank < 1 || rank > 3)
			{
				fail = "Factory skill level out of range: " + rank;
				return false;
			}
			return true;
		}
		fail = "Factory faction skill not present";
		return false;
	}

	private static bool HasSubSkill(Hero dataHero, string subSkillSid)
	{
		var skills = dataHero?.skills?.list;
		if (skills == null)
			return false;
		foreach (var heroSkill in skills)
		{
			if (heroSkill?.subSkills == null)
				continue;
			foreach (var sub in heroSkill.subSkills)
			{
				if (sub == null)
					continue;
				var sid = sub.field_Public_String_0;
				if (string.Equals(sid, subSkillSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	private static object ReadMember(object target, string name)
	{
		if (target == null || string.IsNullOrEmpty(name))
			return null;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			FieldInfo field = null;
			try { field = cur.GetField(name, flags); }
			catch { field = null; }
			if (field != null)
			{
				try
				{
					var value = field.GetValue(target);
					if (value != null)
						return value;
				}
				catch
				{
				}
			}

			PropertyInfo prop = null;
			try { prop = cur.GetProperty(name, flags); }
			catch { prop = null; }
			if (prop != null && prop.CanRead && prop.GetIndexParameters().Length == 0)
			{
				try
				{
					var value = prop.GetValue(target, null);
					if (value != null)
						return value;
				}
				catch
				{
				}
			}

			MethodInfo getter = null;
			try { getter = cur.GetMethod("get_" + name, flags, null, Type.EmptyTypes, null); }
			catch { getter = null; }
			if (getter != null && getter.ReturnType != typeof(void))
			{
				try
				{
					var value = getter.Invoke(target, null);
					if (value != null)
						return value;
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static object ReadNativeField(object target, string name)
	{
		return ReadMember(target, name);
	}

	private static object TryGetProperty(object target, string name)
	{
		return ReadMember(target, name);
	}

	private static string TryReadStringMember(object target, string name)
	{
		var value = ReadNativeField(target, name) ?? TryGetProperty(target, name);
		return value as string;
	}

	private static bool TryReadIntMember(object target, out int value, params string[] names)
	{
		value = 0;
		foreach (var name in names)
		{
			var raw = ReadNativeField(target, name) ?? TryGetProperty(target, name);
			if (raw is int i)
			{
				value = i;
				return true;
			}
		}
		return false;
	}

	private static Assembly FindAssembly(string name)
	{
		var asms = AppDomain.CurrentDomain.GetAssemblies();
		for (var i = 0; i < asms.Length; i++)
		{
			var asm = asms[i];
			if (asm != null && string.Equals(asm.GetName().Name, name, StringComparison.OrdinalIgnoreCase))
				return asm;
		}
		return null;
	}

	private static int ReadJsonInt(string json, string key)
	{
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return 0;
		var token = "\"" + key + "\":";
		var idx = json.IndexOf(token, StringComparison.Ordinal);
		if (idx < 0)
			return 0;
		idx += token.Length;
		var end = idx;
		while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '-'))
			end++;
		return int.TryParse(json.Substring(idx, end - idx), out var value) ? value : 0;
	}

	private static string FirstProbeFrame(Exception ex)
	{
		if (ex?.StackTrace == null)
			return "";
		foreach (var line in ex.StackTrace.Split('\n'))
		{
			if (line != null && line.IndexOf("SplitAssemblyHudSidProof", StringComparison.Ordinal) >= 0)
				return line.Trim();
		}
		return "";
	}

	private static string Json(object value)
	{
		if (value == null)
			return "null";
		if (value is bool b)
			return b ? "true" : "false";
		if (value is int || value is long || value is float || value is double)
			return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
		var s = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
		return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}

	private static string Fail(string message)
	{
		return "{\"ok\":false,\"error\":" + Json(message) + "}";
	}
}
