using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Session.Data;
using Hex.Session.Hud;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

/// <summary>
/// Volatile live preview: leaf + green x/4, gear + orange-brown x/4 beside army-strip heroFace.
/// </summary>
public static class SplitAssemblySimpleHudLive20260726
{
	private const string OverlayName = "HOMM3_SPLIT_ASSEMBLY_SIMPLE_LIVE";
	private static readonly string[] SessionHeroWrapperHeroFields =
	{
		"_ciez_k__BackingField", "<ciez>k__BackingField", "ciez",
		"<cice>k__BackingField", "_cice_k__BackingField", "cice", "coaa",
		"<cibj>k__BackingField", "_cibj_k__BackingField", "cibj",
		"<ciaj>k__BackingField", "_ciaj_k__BackingField", "ciaj",
		"<chxe>k__BackingField", "_chxe_k__BackingField", "chxe"
	};

	private static readonly string[] SessionLogicHeroDataFields =
	{
		"_ccez_k__BackingField", "<ccez>k__BackingField", "ccez"
	};

	private static readonly string[] SessionHeroDataHeroFields =
	{
		"_ccez_k__BackingField", "<ccez>k__BackingField", "ccez", "dataHero", "hero"
	};

	private const string FactorySkillSid = "skill_faction_homm3_factory";
	private const float IconSize = 22f;
	private const float TextSize = 16f;
	private const float RowGap = 5f;
	private const float IconTextGap = 4f;
	private const float BlockGap = 6f;
	private static readonly Color NatureGreen = new Color(0.20f, 0.76f, 0.28f, 1f);
	private static readonly Color IndustryOrangeBrown = new Color(0.82f, 0.46f, 0.12f, 1f);
	private static readonly Color GearTint = new Color(0.72f, 0.42f, 0.10f, 1f);

	public static string Run(string requestJson)
	{
		try
		{
			ClearOverlays();

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
				return Fail("no active BhHeroHUDPanel with heroView.heroFace");

			var heroView = panel.heroView;
			var portrait = heroView.heroFace;
			object sessionHero = null;
			try { sessionHero = heroView.field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0; }
			catch { sessionHero = null; }
			if (sessionHero == null)
				sessionHero = ReadFirstMember(heroView, new[] { "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0", "byop", "bynf", "bymf", "byjc" });
			if (sessionHero == null)
				return Fail("session hero null");

			if (!TryResolveDataHero(sessionHero, out var dataHero, out var heroFail))
			{
				if (!TryReadTiersFromProductionHud(panel, out var naturalTierDirect, out var industrialTierDirect, out var rankCapDirect, out var productionFail))
					return Fail(heroFail + " | " + productionFail);
				return BuildOverlay(panel, portrait, naturalTierDirect, industrialTierDirect, rankCapDirect);
			}

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
			if (!TryEvaluateViaMod(sids, rank, nOc, iOc, out var naturalTier, out var industrialTier, out var rankCap, out var evalFail))
				return Fail(evalFail);
			if (naturalTier == 0 && industrialTier == 0)
				return Fail("both tiers are 0; nothing to show");

			return BuildOverlay(panel, portrait, naturalTier, industrialTier, rankCap);
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static string BuildOverlay(
		BhHeroHUDPanel panel,
		Image portrait,
		int naturalTier,
		int industrialTier,
		int rankCap)
	{
		try
		{
			ClearOverlays();

			var portraitRt = portrait.rectTransform;
			var faceParentTf = portraitRt.parent;
			RectTransform faceParent = null;
			if (faceParentTf != null)
				faceParent = faceParentTf.GetComponent<RectTransform>();
			if (faceParent == null)
				faceParent = portrait.GetComponentInParent<RectTransform>();
			if (faceParent == null || faceParent == portraitRt)
				return Fail("heroFace parent missing");

			var faceW = portraitRt.rect.width > 1f ? portraitRt.rect.width : Mathf.Abs(portraitRt.sizeDelta.x);
			if (faceW < 1f)
				faceW = 64f;
			var faceH = portraitRt.rect.height > 1f ? portraitRt.rect.height : Mathf.Abs(portraitRt.sizeDelta.y);
			if (faceH < 1f)
				faceH = 72f;

			var blockWidth = IconSize + IconTextGap + 34f;
			var blockHeight = IconSize * 2f + RowGap;
			var rootGo = new GameObject(OverlayName);
			rootGo.layer = panel.gameObject.layer;
			rootGo.transform.SetParent(faceParent, false);
			var root = rootGo.AddComponent<RectTransform>();
			root.anchorMin = portraitRt.anchorMin;
			root.anchorMax = portraitRt.anchorMax;
			root.pivot = new Vector2(1f, 0.5f);
			root.sizeDelta = new Vector2(blockWidth, blockHeight);
			root.anchoredPosition = new Vector2(
				portraitRt.anchoredPosition.x - faceW * 0.5f - BlockGap,
				portraitRt.anchoredPosition.y);
			root.localScale = new Vector3(1f, 1f, 1f);
			root.localRotation = Quaternion.identity;
			root.SetAsLastSibling();

			var leafSprite = CreateLeafSprite();
			var gearSprite = CreateGearSprite();
			var font = BorrowTmpFont(panel.gameObject);

			CreateRow(
				root,
				"natural_row",
				leafSprite,
				NatureGreen,
				naturalTier + "/4",
				new Vector2(0f, RowGap * 0.5f),
				font);
			CreateRow(
				root,
				"industrial_row",
				gearSprite,
				IndustryOrangeBrown,
				industrialTier + "/4",
				new Vector2(0f, -(IconSize + RowGap)),
				font,
				GearTint);

			return "{"
			       + "\"ok\":true"
			       + ",\"overlay\":" + Json(OverlayName)
			       + ",\"path\":" + Json(BuildPath(root))
			       + ",\"natural\":" + Json(naturalTier + "/4")
			       + ",\"industrial\":" + Json(industrialTier + "/4")
			       + ",\"rankCap\":" + rankCap
			       + ",\"note\":\"volatile simple leaf/gear + x/4 live preview; restart restores pip meters\""
			       + "}";
		}
		catch (Exception ex)
		{
			return Fail(ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool TryReadTiersFromProductionHud(
		BhHeroHUDPanel panel,
		out int naturalTier,
		out int industrialTier,
		out int rankCap,
		out string fail)
	{
		naturalTier = 0;
		industrialTier = 0;
		rankCap = 4;
		fail = null;
		try
		{
			var mod = FindAssembly("OfflineUnlockMod");
			var hudType = mod != null ? mod.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyArmyStripHud", false) : null;
			if (hudType == null)
			{
				fail = "production HUD type missing";
				return false;
			}
			var resolveSession = hudType.GetMethod(
				"TryResolveSessionHeroFromPanel",
				BindingFlags.Static | BindingFlags.NonPublic);
			var tryBuild = hudType.GetMethod(
				"TryBuildSnapshot",
				BindingFlags.Static | BindingFlags.NonPublic);
			if (resolveSession == null || tryBuild == null)
			{
				fail = "production HUD resolve/build methods missing";
				return false;
			}
			var session = resolveSession.Invoke(null, new object[] { panel });
			var args = new object[] { session, null, null };
			if (!(bool)tryBuild.Invoke(null, args))
			{
				fail = args[2] as string ?? "production snapshot build failed";
				return false;
			}
			var snap = args[1];
			var t = snap.GetType();
			naturalTier = ReadIntField(snap, t, "NaturalTier");
			industrialTier = ReadIntField(snap, t, "IndustrialTier");
			rankCap = ReadIntField(snap, t, "RankCap");
			if (rankCap <= 0)
				rankCap = 4;
			return true;
		}
		catch (Exception ex)
		{
			fail = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static void ClearOverlays()
	{
		var all = Resources.FindObjectsOfTypeAll<GameObject>();
		for (var i = 0; i < all.Length; i++)
		{
			var go = all[i];
			if (go == null)
				continue;
			if (go.name == OverlayName || go.name == "HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS")
				Object.Destroy(go);
		}
	}

	private static void CreateRow(
		RectTransform parent,
		string rowName,
		Sprite iconSprite,
		Color textColor,
		string label,
		Vector2 anchoredPos,
		TMP_FontAsset font,
		Color? iconTint = null)
	{
		var row = new GameObject(rowName);
		row.transform.SetParent(parent, false);
		var rowRt = row.AddComponent<RectTransform>();
		rowRt.anchorMin = new Vector2(0f, 0.5f);
		rowRt.anchorMax = new Vector2(0f, 0.5f);
		rowRt.pivot = new Vector2(0f, 0.5f);
		rowRt.sizeDelta = new Vector2(IconSize + IconTextGap + 34f, IconSize);
		rowRt.anchoredPosition = anchoredPos;

		var iconGo = new GameObject("icon");
		iconGo.transform.SetParent(row.transform, false);
		var iconRt = iconGo.AddComponent<RectTransform>();
		iconRt.anchorMin = new Vector2(0f, 0.5f);
		iconRt.anchorMax = new Vector2(0f, 0.5f);
		iconRt.pivot = new Vector2(0f, 0.5f);
		iconRt.sizeDelta = new Vector2(IconSize, IconSize);
		iconRt.anchoredPosition = Vector2.zero;
		var icon = iconGo.AddComponent<Image>();
		icon.sprite = iconSprite;
		icon.preserveAspect = true;
		icon.raycastTarget = false;
		icon.color = iconTint ?? Color.white;

		var textGo = new GameObject("count");
		textGo.transform.SetParent(row.transform, false);
		var textRt = textGo.AddComponent<RectTransform>();
		textRt.anchorMin = new Vector2(0f, 0.5f);
		textRt.anchorMax = new Vector2(0f, 0.5f);
		textRt.pivot = new Vector2(0f, 0.5f);
		textRt.sizeDelta = new Vector2(34f, IconSize);
		textRt.anchoredPosition = new Vector2(IconSize + IconTextGap, 0f);
		var text = textGo.AddComponent<TextMeshProUGUI>();
		text.text = label;
		text.fontSize = TextSize;
		text.color = textColor;
		text.alignment = TextAlignmentOptions.MidlineLeft;
		text.raycastTarget = false;
		if (font)
			text.font = font;
	}

	private static TMP_FontAsset BorrowTmpFont(GameObject root)
	{
		try
		{
			var canvas = root.GetComponentInParent<Canvas>();
			var donors = canvas
				? canvas.GetComponentsInChildren<TextMeshProUGUI>(true)
				: root.GetComponentsInChildren<TextMeshProUGUI>(true);
			for (var i = 0; i < donors.Length; i++)
			{
				var donor = donors[i];
				if (donor != null && donor.font)
					return donor.font;
			}
		}
		catch
		{
		}
		return null;
	}

	private static Sprite CreateLeafSprite()
	{
		const int w = 32;
		const int h = 32;
		var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
		var clear = new Color(0f, 0f, 0f, 0f);
		var fill = new Color(0.18f, 0.70f, 0.24f, 1f);
		var stroke = new Color(0.10f, 0.48f, 0.14f, 1f);
		for (var y = 0; y < h; y++)
		{
			for (var x = 0; x < w; x++)
				tex.SetPixel(x, y, clear);
		}
		for (var y = 4; y < h - 4; y++)
		{
			for (var x = 6; x < w - 4; x++)
			{
				var nx = (x - 10f) / 14f;
				var ny = (y - 10f) / 12f;
				var body = nx * nx + ny * ny * 1.35f;
				if (body <= 1f)
					tex.SetPixel(x, y, fill);
				else if (body <= 1.15f)
					tex.SetPixel(x, y, stroke);
			}
		}
		for (var y = 8; y < h - 8; y++)
		{
			var t = (y - 8f) / (h - 16f);
			var x = Mathf.RoundToInt(Mathf.Lerp(15f, 24f, t));
			if (x >= 0 && x < w)
				tex.SetPixel(x, y, stroke);
		}
		tex.Apply();
		tex.filterMode = FilterMode.Bilinear;
		return Sprite.Create(tex, new Rect(0f, 0f, w, h), new Vector2(0.5f, 0.5f), 100f);
	}

	private static Sprite CreateGearSprite()
	{
		const int w = 32;
		const int h = 32;
		var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
		var clear = new Color(0f, 0f, 0f, 0f);
		var fill = new Color(0.78f, 0.44f, 0.10f, 1f);
		var stroke = new Color(0.52f, 0.28f, 0.06f, 1f);
		var cx = 15.5f;
		var cy = 15.5f;
		for (var y = 0; y < h; y++)
		{
			for (var x = 0; x < w; x++)
			{
				var dx = x - cx;
				var dy = y - cy;
				var dist = Mathf.Sqrt(dx * dx + dy * dy);
				var angle = Mathf.Atan2(dy, dx);
				var tooth = Mathf.Cos(angle * 8f);
				var outer = 11.5f + tooth * 2.2f;
				var inner = 5.5f;
				if (dist <= inner)
					tex.SetPixel(x, y, clear);
				else if (dist <= outer - 0.8f)
					tex.SetPixel(x, y, fill);
				else if (dist <= outer)
					tex.SetPixel(x, y, stroke);
				else
					tex.SetPixel(x, y, clear);
			}
		}
		tex.Apply();
		tex.filterMode = FilterMode.Bilinear;
		return Sprite.Create(tex, new Rect(0f, 0f, w, h), new Vector2(0.5f, 0.5f), 100f);
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

	private static bool TryEvaluateViaMod(
		List<string> sids,
		int rank,
		bool nOc,
		bool iOc,
		out int naturalTier,
		out int industrialTier,
		out int rankCap,
		out string fail)
	{
		naturalTier = 0;
		industrialTier = 0;
		rankCap = 4;
		fail = null;
		var mod = FindAssembly("OfflineUnlockMod");
		var evalType = mod != null ? mod.GetType("OfflineUnlockMod.Homm3FactorySplitAssemblyEvaluator", false) : null;
		var tryEvaluate = evalType != null
			? evalType.GetMethod("TryEvaluate", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
			: null;
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
		naturalTier = ReadIntField(snap, t, "NaturalTier");
		industrialTier = ReadIntField(snap, t, "IndustrialTier");
		rankCap = ReadIntField(snap, t, "RankCap");
		if (rankCap <= 0)
			rankCap = 4;
		return true;
	}

	private static int ReadIntField(object snap, Type t, string name)
	{
		var field = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		return field != null && field.GetValue(snap) is int v ? v : 0;
	}

	private static bool TryResolveDataHero(object sessionHero, out Hero dataHero, out string fail)
	{
		dataHero = null;
		fail = null;
		if (sessionHero is Hero direct)
		{
			dataHero = direct;
			return true;
		}

		var nestedData = ReadFirstMember(sessionHero, SessionHeroDataHeroFields) as Hero;
		if (nestedData != null)
		{
			dataHero = nestedData;
			return true;
		}

		var logicHero = ReadFirstMember(sessionHero, SessionHeroWrapperHeroFields);
		if (logicHero != null && !ReferenceEquals(logicHero, sessionHero))
		{
			if (logicHero is Hero logicAsData)
			{
				dataHero = logicAsData;
				return true;
			}
			var fromLogic = ReadFirstMember(logicHero, SessionLogicHeroDataFields) as Hero;
			if (fromLogic != null)
			{
				dataHero = fromLogic;
				return true;
			}
			return TryResolveDataHero(logicHero, out dataHero, out fail);
		}

		fail = "Data.Hero unresolved from session hero type " + (sessionHero.GetType().FullName ?? "?");
		return false;
	}

	private static object ReadFirstMember(object target, string[] names)
	{
		if (target == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = ReadMember(target, names[i]);
			if (value != null)
				return value;
		}
		return null;
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
					return field.GetValue(target);
			}
			catch
			{
			}
		}
		return null;
	}

	private static Assembly FindAssembly(string name)
	{
		var assemblies = AppDomain.CurrentDomain.GetAssemblies();
		for (var i = 0; i < assemblies.Length; i++)
		{
			var asm = assemblies[i];
			if (asm != null && string.Equals(asm.GetName().Name, name, StringComparison.OrdinalIgnoreCase))
				return asm;
		}
		return null;
	}

	private static string BuildPath(Transform t)
	{
		if (!t)
			return "";
		var path = t.name;
		var cur = t.parent;
		while (cur != null)
		{
			path = cur.name + "/" + path;
			cur = cur.parent;
		}
		return path;
	}

	private static string Json(string value)
	{
		if (value == null)
			return "null";
		return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
	}

	private static string Fail(string message)
	{
		return "{\"ok\":false,\"error\":" + Json(message) + "}";
	}
}
