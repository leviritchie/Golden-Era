using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Session.Data;
using Hex.Session.Hud;
using Hex.UI;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

/// <summary>
/// Live-positive art proof: authored Split Assembly HUD sprites left of
/// <c>BhHeroHUDPanel.heroView.heroFace</c> on <c>CanvasHeroHUDPanel</c>,
/// strip-local sizing (same as the accepted neon size proof).
/// </summary>
public static class SplitAssemblyArmyStripHudProof20260726
{
	private const string OverlayName = "HOMM3_SPLIT_ASSEMBLY_ARMY_STRIP_PROOF";
	private const string FactorySkillSid = "skill_faction_homm3_factory";
	private const float MeterWidth = 28f;
	private const float MeterGap = 4f;
	private const float PipSize = 10f;
	private const float HeaderSize = 12f;

	public static string Run(string requestJson)
	{
		try
		{
			// Clear prior wrong-surface / orphan proofs.
			foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
			{
				if (go == null)
					continue;
				var n = go.name;
				if (n == OverlayName
				    || n == "HOMM3_SPLIT_ASSEMBLY_VISIBLE_PROOF"
				    || n == "HOMM3_SPLIT_ASSEMBLY_SID_PROOF"
				    || n == "HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS")
					Object.Destroy(go);
			}

			var panels = Object.FindObjectsOfType<BhHeroHUDPanel>(true);
			BhHeroHUDPanel panel = null;
			for (var i = 0; i < panels.Length; i++)
			{
				var p = panels[i];
				if (p == null || p.gameObject == null || !p.gameObject.activeInHierarchy)
					continue;
				if (p.heroView == null || p.heroView.heroFace == null)
					continue;
				panel = p;
				break;
			}
			if (panel == null)
				return Fail("no active BhHeroHUDPanel with heroView.heroFace (scanned " + panels.Length + ")");

			var heroView = panel.heroView;
			var portrait = heroView.heroFace;
			var sessionHero = heroView.field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0;
			if (sessionHero == null)
				return Fail("heroView session hero null");

			var logicHero = ReadMember(sessionHero, "_ciez_k__BackingField");
			if (logicHero == null)
				return Fail("Logic.Hero missing");
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

			var parent = panel.GetComponent<RectTransform>();
			if (parent == null)
				parent = panel.transform as RectTransform;
			if (parent == null)
				return Fail("BhHeroHUDPanel has no RectTransform");

			var path = BuildPath(panel.transform);
			if (path.IndexOf("CanvasSideHeroHUDPanel", StringComparison.Ordinal) >= 0)
				return Fail("refused: resolved panel under CanvasSideHeroHUDPanel (wrong surface)");
			if (path.IndexOf("CanvasHeroHUDPanel", StringComparison.Ordinal) < 0)
				return Fail("refused: panel path missing CanvasHeroHUDPanel: " + path);

			var portraitRt = portrait.rectTransform;
			var faceParentTf = portraitRt.parent;
			RectTransform faceParent = null;
			if (faceParentTf != null)
				faceParent = faceParentTf.GetComponent<RectTransform>();
			if (faceParent == null)
				faceParent = portrait.GetComponentInParent<RectTransform>();
			if (faceParent == null || faceParent == portraitRt)
				return Fail("heroFace parent RectTransform missing");
			var faceParentPath = BuildPath(faceParent);
			if (faceParentPath.IndexOf("CanvasSideHeroHUDPanel", StringComparison.Ordinal) >= 0)
				return Fail("refused: heroFace under side list: " + faceParentPath);
			if (faceParentPath.IndexOf("CanvasHeroHUDPanel", StringComparison.Ordinal) < 0)
				return Fail("refused: heroFace parent not under CanvasHeroHUDPanel: " + faceParentPath);

			if (!TryRequireHudArt(out var artFail))
				return Fail(artFail);

			var rootGo = new GameObject(OverlayName);
			rootGo.layer = panel.gameObject.layer;
			rootGo.transform.SetParent(faceParent, false);
			if (rootGo.transform.parent != faceParent)
				return Fail("SetParent failed under heroFace parent=" + faceParent.name);

			var root = rootGo.GetComponent<RectTransform>() ?? rootGo.AddComponent<RectTransform>();
			root.anchorMin = portraitRt.anchorMin;
			root.anchorMax = portraitRt.anchorMax;
			root.pivot = new Vector2(1f, 0.5f);
			var faceW = portraitRt.rect.width > 1f ? portraitRt.rect.width : Mathf.Abs(portraitRt.sizeDelta.x);
			if (faceW < 1f)
				faceW = 64f;
			var faceH = portraitRt.rect.height > 1f ? portraitRt.rect.height : Mathf.Abs(portraitRt.sizeDelta.y);
			if (faceH < 1f)
				faceH = 72f;
			root.sizeDelta = new Vector2(MeterWidth, faceH);
			root.anchoredPosition = new Vector2(
				portraitRt.anchoredPosition.x - faceW * 0.5f - MeterGap,
				portraitRt.anchoredPosition.y);
			root.localRotation = Quaternion.identity;
			root.localScale = new Vector3(1f, 1f, 1f);
			root.SetAsLastSibling();

			// Transparent hit plate (product meters use authored rail, not neon fill).
			var hit = rootGo.AddComponent<Image>();
			hit.color = new Color(1f, 1f, 1f, 0.01f);
			hit.raycastTarget = false;

			CreateChildImage(root, "rail", RequireSprite("rail_frame"), new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(MeterWidth, faceH));
			CreateChildImage(root, "header_natural", RequireSprite("header_natural"), new Vector2(0.25f, 1f), new Vector2(0f, -2f), new Vector2(HeaderSize, HeaderSize));
			CreateChildImage(root, "header_industrial", RequireSprite("header_industrial"), new Vector2(0.75f, 1f), new Vector2(0f, -2f), new Vector2(HeaderSize, HeaderSize));
			var nOcMark = CreateChildImage(root, "overclock_natural", RequireSprite("overclock_mark"), new Vector2(0.25f, 1f), new Vector2(6f, 6f), new Vector2(8f, 8f));
			var iOcMark = CreateChildImage(root, "overclock_industrial", RequireSprite("overclock_mark"), new Vector2(0.75f, 1f), new Vector2(6f, 6f), new Vector2(8f, 8f));
			nOcMark.enabled = nOc;
			iOcMark.enabled = iOc;

			for (var i = 0; i < 4; i++)
			{
				var y = -14f - i * (PipSize + 2f);
				CreateChildImage(
					root,
					"pip_natural_" + i,
					RequirePipSprite("natural", i + 1, naturalTiers, rankCap),
					new Vector2(0.25f, 1f),
					new Vector2(0f, y),
					new Vector2(PipSize, PipSize));
				CreateChildImage(
					root,
					"pip_industrial_" + i,
					RequirePipSprite("industrial", i + 1, industrialTiers, rankCap),
					new Vector2(0.75f, 1f),
					new Vector2(0f, y),
					new Vector2(PipSize, PipSize));
			}

			var lossy = root.lossyScale;
			var faceLossy = portraitRt.lossyScale;
			return "{"
			       + "\"ok\":true"
			       + ",\"parent\":" + Json(faceParentPath)
			       + ",\"panelPath\":" + Json(path)
			       + ",\"portrait\":\"heroView.heroFace\""
			       + ",\"faceParent\":" + Json(faceParent.name)
			       + ",\"heroConfigSid\":" + Json(dataHero.configSid)
			       + ",\"unitSids\":" + Json(string.Join(",", sids.ToArray()))
			       + ",\"snapshot\":" + snapshotJson
			       + ",\"art\":\"homm3_factory_split_assembly_hud\""
			       + ",\"overlayLossyScale\":" + Json(lossy.x + "," + lossy.y)
			       + ",\"heroFaceLossyScale\":" + Json(faceLossy.x + "," + faceLossy.y)
			       + ",\"anchoredPosition\":" + Json(root.anchoredPosition.x + "," + root.anchoredPosition.y)
			       + ",\"sizeDelta\":" + Json(root.sizeDelta.x + "x" + root.sizeDelta.y)
			       + ",\"note\":\"authored PNG meters at accepted strip-local size left of army-strip heroFace\""
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static string BuildPath(Transform t)
	{
		var parts = new List<string>();
		for (var cur = t; cur != null; cur = cur.parent)
			parts.Add(cur.name);
		parts.Reverse();
		return string.Join("/", parts.ToArray());
	}

	private static Image CreateChildImage(
		RectTransform parent,
		string name,
		Sprite sprite,
		Vector2 anchor,
		Vector2 anchoredPos,
		Vector2 size)
	{
		var go = new GameObject(name);
		go.transform.SetParent(parent, false);
		var rt = go.AddComponent<RectTransform>();
		rt.anchorMin = anchor;
		rt.anchorMax = anchor;
		rt.pivot = new Vector2(0.5f, 0.5f);
		rt.sizeDelta = size;
		rt.anchoredPosition = anchoredPos;
		var img = go.AddComponent<Image>();
		img.sprite = sprite;
		img.preserveAspect = true;
		img.raycastTarget = false;
		img.color = Color.white;
		return img;
	}

	private static bool TryRequireHudArt(out string fail)
	{
		fail = null;
		var mod = FindAssembly("OfflineUnlockMod");
		var cacheType = mod?.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyHudSpriteCache", false);
		var tryRequire = cacheType?.GetMethod("TryRequireAll", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
		if (tryRequire == null)
		{
			fail = "Homm3FactorySplitAssemblyHudSpriteCache.TryRequireAll missing";
			return false;
		}
		var args = new object[] { null };
		if (!(bool)tryRequire.Invoke(null, args))
		{
			fail = args[0] as string ?? "HUD art missing";
			return false;
		}
		return true;
	}

	private static Sprite RequireSprite(string name)
	{
		if (!TryGetHudSprite(name, out var sprite) || !sprite)
			throw new InvalidOperationException("HUD sprite missing: " + name);
		return sprite;
	}

	private static Sprite RequirePipSprite(string branch, int slot, int unlocked, int rankCap)
	{
		string state;
		if (slot <= unlocked)
			state = "filled";
		else if (slot <= rankCap)
			state = "empty";
		else
			state = "locked";
		return RequireSprite("pip_" + branch + "_" + state);
	}

	private static bool TryGetHudSprite(string name, out Sprite sprite)
	{
		sprite = null;
		var mod = FindAssembly("OfflineUnlockMod");
		var cacheType = mod?.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyHudSpriteCache", false);
		var tryGet = cacheType?.GetMethod("TryGetOrCreateSprite", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
		if (tryGet == null)
			return false;
		var args = new object[] { name, null };
		if (!(bool)tryGet.Invoke(null, args))
			return false;
		sprite = args[1] as Sprite;
		return sprite != null;
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
