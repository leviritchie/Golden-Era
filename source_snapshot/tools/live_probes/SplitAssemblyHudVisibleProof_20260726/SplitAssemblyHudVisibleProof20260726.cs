using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Session.Data;
using Hex.Session.Hud;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

/// <summary>
/// Visible live proof: parent meters to BhHeroUIElement root (NOT under scaled HERO ICON).
/// Prior inject was invisible because HERO ICON lossyScale ~0.19 crushed the overlay.
/// </summary>
public static class SplitAssemblyHudVisibleProof20260726
{
	private const string OverlayName = "HOMM3_SPLIT_ASSEMBLY_VISIBLE_PROOF";
	private const string FactorySkillSid = "skill_faction_homm3_factory";

	public static string Run(string requestJson)
	{
		try
		{
			var elements = Object.FindObjectsOfType<BhHeroUIElement>(true);
			BhHeroUIElement target = null;
			for (var i = 0; i < elements.Length; i++)
			{
				var el = elements[i];
				if (el == null || el.gameObject == null || !el.gameObject.activeInHierarchy)
					continue;
				if (el.field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0 == null)
					continue;
				target = el;
				break;
			}
			if (target == null)
				return Fail("no active BhHeroUIElement with hero");

			var sessionHero = target.field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0;
			var logicHero = ReadMember(sessionHero, "_ciez_k__BackingField");
			var dataHero = ReadMember(logicHero, "_ccez_k__BackingField") as Hero;
			if (dataHero == null)
				return Fail("Data.Hero missing");

			var sids = new List<string>();
			foreach (var unit in dataHero.party.units)
			{
				if (unit == null)
					continue;
				var sid = unit.field_Public_String_0;
				if (!string.IsNullOrWhiteSpace(sid))
					sids.Add(sid.Trim());
			}
			if (!TryResolveFactoryRank(dataHero, out var rank, out var rankFail))
				return Fail(rankFail);
			var nOc = HasSubSkill(dataHero, "sub_skill_faction_homm3_factory_gantry_reserve");
			var iOc = HasSubSkill(dataHero, "sub_skill_faction_homm3_factory_industrial_tempo");
			if (!TryEvaluateViaMod(sids, rank, nOc, iOc, out var snapshotJson, out var evalFail))
				return Fail(evalFail);

			ParseTiers(snapshotJson, out var naturalTiers, out var industrialTiers, out var rankCap);

			var portrait = target.heroIcon;
			if (portrait == null)
				return Fail("heroIcon missing");

			// Destroy prior proofs (including clipped-under-icon / orphaned scene-root ones).
			DestroyNamed(portrait.rectTransform, "HOMM3_SPLIT_ASSEMBLY_SID_PROOF");
			DestroyNamed(target.transform, OverlayName);
			DestroyNamed(portrait.rectTransform, OverlayName);
			foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
			{
				if (go == null) continue;
				if (go.name == OverlayName || go.name == "HOMM3_SPLIT_ASSEMBLY_SID_PROOF")
					Object.Destroy(go);
			}

			var parent = target.GetComponent<RectTransform>();
			if (parent == null)
				parent = target.transform as RectTransform;
			if (parent == null)
				return Fail("BhHeroUIElement has no RectTransform");

			var rootGo = new GameObject(OverlayName);
			rootGo.layer = target.gameObject.layer;
			rootGo.transform.SetParent(parent, false);
			if (rootGo.transform.parent != parent)
				return Fail("SetParent failed; parent=" + (parent == null ? "null" : parent.name) + " actual=" + (rootGo.transform.parent == null ? "null" : rootGo.transform.parent.name));

			var root = rootGo.GetComponent<RectTransform>() ?? rootGo.AddComponent<RectTransform>();
			// Left of portrait: match portrait anchors in element space.
			var portraitRt = portrait.rectTransform;
			root.anchorMin = portraitRt.anchorMin;
			root.anchorMax = portraitRt.anchorMax;
			root.pivot = new Vector2(1f, 0.5f);
			var h = Mathf.Max(72f, portraitRt.rect.height > 1f ? portraitRt.rect.height : 72f);
			root.sizeDelta = new Vector2(64f, h);
			root.anchoredPosition = new Vector2(
				portraitRt.anchoredPosition.x - (portraitRt.rect.width > 1f ? portraitRt.rect.width * 0.5f : portraitRt.sizeDelta.x * 0.5f) - 6f,
				portraitRt.anchoredPosition.y);
			root.SetAsLastSibling();
			// Strip list root is heavily scaled (~0.19). Compensate so meters are screen-visible.
			var pls = parent.lossyScale;
			var sx = Math.Abs(pls.x) > 0.0001f ? 1f / pls.x : 1f;
			var sy = Math.Abs(pls.y) > 0.0001f ? 1f / pls.y : 1f;
			root.localScale = new Vector3(sx, sy, 1f);
			root.sizeDelta = new Vector2(48f, 96f);

			var bg = rootGo.AddComponent<Image>();
			bg.color = new Color(1f, 0f, 1f, 0.95f); // neon magenta — impossible to miss
			bg.raycastTarget = false;

			AddPipColumn(root, 0.30f, new Color(1f, 0.85f, 0.1f, 1f), naturalTiers, rankCap);
			AddPipColumn(root, 0.70f, new Color(0.2f, 0.95f, 1f, 1f), industrialTiers, rankCap);

			var lossy = root.lossyScale;
			var iconLossy = portraitRt.lossyScale;
			return "{"
			       + "\"ok\":true"
			       + ",\"parent\":\"BhHeroUIElement.root\""
			       + ",\"heroConfigSid\":" + Json(dataHero.configSid)
			       + ",\"snapshot\":" + snapshotJson
			       + ",\"overlayLossyScale\":" + Json(lossy.x + "," + lossy.y)
			       + ",\"iconLossyScale\":" + Json(iconLossy.x + "," + iconLossy.y)
			       + ",\"sizeDelta\":" + Json(root.sizeDelta.x + "x" + root.sizeDelta.y)
			       + ",\"anchoredPosition\":" + Json(root.anchoredPosition.x + "," + root.anchoredPosition.y)
			       + ",\"note\":\"magenta rail left of portrait on strip cell root; prior icon-child inject was scale-crushed\""
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void DestroyNamed(Transform parent, string name)
	{
		if (parent == null)
			return;
		var existing = parent.Find(name);
		if (existing)
			Object.Destroy(existing.gameObject);
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
			rt.sizeDelta = new Vector2(18f, 18f);
			rt.anchoredPosition = new Vector2(0f, -16f - i * 20f);
			var img = go.AddComponent<Image>();
			img.raycastTarget = false;
			var slot = i + 1;
			if (slot <= unlocked)
				img.color = filled;
			else if (slot <= rankCap)
				img.color = new Color(0.2f, 0.2f, 0.2f, 0.9f);
			else
				img.color = new Color(0.05f, 0.05f, 0.05f, 0.7f);
		}
	}

	private static bool TryResolveFactoryRank(Hero dataHero, out int rank, out string fail)
	{
		rank = 0;
		fail = null;
		foreach (var heroSkill in dataHero.skills.list)
		{
			if (heroSkill == null)
				continue;
			if (!string.Equals(heroSkill.field_Public_String_0, FactorySkillSid, StringComparison.Ordinal))
				continue;
			rank = heroSkill.level;
			if (rank < 1 || rank > 3)
			{
				fail = "bad rank " + rank;
				return false;
			}
			return true;
		}
		fail = "Factory skill missing";
		return false;
	}

	private static bool HasSubSkill(Hero dataHero, string subSkillSid)
	{
		foreach (var heroSkill in dataHero.skills.list)
		{
			if (heroSkill?.subSkills == null)
				continue;
			foreach (var sub in heroSkill.subSkills)
			{
				if (sub != null && string.Equals(sub.field_Public_String_0, subSkillSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	private static bool TryEvaluateViaMod(List<string> sids, int rank, bool nOc, bool iOc, out string snapshotJson, out string fail)
	{
		snapshotJson = null;
		fail = null;
		var mod = FindAssembly("OfflineUnlockMod");
		var evalType = mod?.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyEvaluator", false);
		var tryEvaluate = evalType?.GetMethod("TryEvaluate", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
		if (tryEvaluate == null)
		{
			fail = "evaluator missing";
			return false;
		}
		var args = new object[] { sids, rank, nOc, iOc, null, null };
		if (!(bool)tryEvaluate.Invoke(null, args))
		{
			fail = args[5] as string ?? "evaluate false";
			return false;
		}
		var snap = args[4];
		var t = snap.GetType();
		int I(string n) => t.GetField(n, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(snap) is int v ? v : 0;
		bool B(string n) => t.GetField(n, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(snap) is bool b && b;
		string S(string n) => Json(t.GetField(n, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(snap));
		snapshotJson = "{\"Rank\":" + I("Rank")
		               + ",\"NaturalTiers\":" + I("NaturalTier")
		               + ",\"IndustrialTiers\":" + I("IndustrialTier")
		               + ",\"RankCap\":" + I("RankCap")
		               + ",\"NaturalEffective\":" + I("NaturalEffective")
		               + ",\"IndustrialEffective\":" + I("IndustrialEffective")
		               + ",\"NaturalOverclock\":" + (B("NaturalOverclock") ? "true" : "false")
		               + ",\"IndustrialOverclock\":" + (B("IndustrialOverclock") ? "true" : "false")
		               + ",\"NaturalLines\":" + S("NaturalLines")
		               + ",\"IndustrialLines\":" + S("IndustrialLines") + "}";
		return true;
	}

	private static void ParseTiers(string snapshotJson, out int naturalTiers, out int industrialTiers, out int rankCap)
	{
		naturalTiers = ReadJsonInt(snapshotJson, "NaturalTiers");
		industrialTiers = ReadJsonInt(snapshotJson, "IndustrialTiers");
		rankCap = ReadJsonInt(snapshotJson, "RankCap");
		if (rankCap <= 0)
			rankCap = 4;
	}

	private static object ReadMember(object target, string name)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			try
			{
				var field = cur.GetField(name, flags);
				if (field != null)
				{
					var v = field.GetValue(target);
					if (v != null)
						return v;
				}
			}
			catch { }
			try
			{
				var prop = cur.GetProperty(name, flags);
				if (prop != null && prop.CanRead && prop.GetIndexParameters().Length == 0)
				{
					var v = prop.GetValue(target, null);
					if (v != null)
						return v;
				}
			}
			catch { }
			try
			{
				var getter = cur.GetMethod("get_" + name, flags, null, Type.EmptyTypes, null);
				if (getter != null)
				{
					var v = getter.Invoke(target, null);
					if (v != null)
						return v;
				}
			}
			catch { }
		}
		return null;
	}

	private static Assembly FindAssembly(string name)
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm != null && string.Equals(asm.GetName().Name, name, StringComparison.OrdinalIgnoreCase))
				return asm;
		}
		return null;
	}

	private static int ReadJsonInt(string json, string key)
	{
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

	private static string Json(object value)
	{
		if (value == null)
			return "null";
		var s = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
		return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}

	private static string Fail(string message)
	{
		return "{\"ok\":false,\"error\":" + Json(message) + "}";
	}
}
