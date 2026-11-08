using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using Hex.UI.City;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

/// <summary>
/// Volatile live proof for Factory 8-unit recruitment strip option 2:
/// items 0-3, itemsLow3 4-7 (Dreadnought on low row), itemsLow4 hidden.
/// </summary>
public static class FactoryRecruitmentStripOption2Probe20260731
{
	private const BindingFlags All = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
	private static readonly string[] FactorySidsFallback =
	{
		"h3_halfling", "h3_mechanic", "h3_armadillo", "h3_automaton",
		"h3_sandworm", "h3_gunslinger", "h3_couatl", "h3_dreadnought",
	};

	public static string Run()
	{
		var sb = new StringBuilder();
		try
		{
			var sids = GetRecruitmentBaseSids(sb);
			var view = FindCitySpecialView();
			if (view == null)
				return Fail(sb, "BhCitySpecialView not found in CityUI.");

			sb.Append(" scene=").Append(SceneManager.GetActiveScene().name);
			sb.Append(" sids=").Append(sids.Length);

			var applied = 0;
			applied += ApplyList(view, "items", ResolveListSidsOption2("items", sids), sb);
			applied += ApplyList(view, "itemsLow3", ResolveListSidsOption2("itemsLow3", sids), sb);
			applied += ApplyList(view, "itemsLow4", ResolveListSidsOption2("itemsLow4", sids), sb);
			sb.Append(" applied=").Append(applied);

			ApplyPhysicalLayout(view.transform, sids.Length, sb);
			return "{\"ok\":true,\"text\":\"" + Escape(sb.ToString()) + "\"}";
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"" + Escape(ex.GetType().Name + ": " + ex.Message) + "\"}";
		}
	}

	private static string[] GetRecruitmentBaseSids(StringBuilder sb)
	{
		var registry = Type.GetType("OfflineUnlockMod.Homm3CustomFactionRegistry, OfflineUnlockMod");
		if (registry == null)
		{
			sb.Append(" registry=missing");
			return FactorySidsFallback;
		}

		var method = registry.GetMethod("GetRecruitmentBaseSids", All);
		if (method == null)
		{
			sb.Append(" registryMethod=missing");
			return FactorySidsFallback;
		}

		var value = method.Invoke(null, new object[] { "homm3_factory" }) as string[];
		if (value == null || value.Length == 0)
		{
			sb.Append(" registrySids=empty");
			return FactorySidsFallback;
		}

		sb.Append(" registrySids=").Append(value.Length);
		return value;
	}

	private static BhCitySpecialView FindCitySpecialView()
	{
		var views = UnityEngine.Object.FindObjectsOfType<BhCitySpecialView>(true);
		BhCitySpecialView match = null;
		for (var i = 0; i < views.Length; i++)
		{
			var view = views[i];
			if (view == null || view.gameObject == null || !view.gameObject.scene.IsValid())
				continue;
			if (!string.Equals(view.gameObject.scene.name, "CityUI", StringComparison.Ordinal))
				continue;
			if (match != null)
				throw new InvalidOperationException("Multiple BhCitySpecialView instances in CityUI.");
			match = view;
		}
		return match;
	}

	private static string[] ResolveListSidsOption2(string fieldName, string[] baseSids)
	{
		if (baseSids == null || baseSids.Length == 0 || string.IsNullOrWhiteSpace(fieldName))
			return Array.Empty<string>();
		if (string.Equals(fieldName, "items", StringComparison.Ordinal)
		    || string.Equals(fieldName, "bzkd", StringComparison.Ordinal))
			return Slice(baseSids, 0, Math.Min(4, baseSids.Length));
		if (string.Equals(fieldName, "itemsLow3", StringComparison.Ordinal))
		{
			if (baseSids.Length > 7)
				return Slice(baseSids, 4, 4);
			return Slice(baseSids, 4, Math.Min(3, Math.Max(0, baseSids.Length - 4)));
		}
		if (string.Equals(fieldName, "itemsLow4", StringComparison.Ordinal))
			return Array.Empty<string>();
		return Array.Empty<string>();
	}

	private static string[] Slice(string[] sids, int start, int count)
	{
		if (sids == null || start < 0 || count <= 0 || start >= sids.Length)
			return Array.Empty<string>();
		var length = Math.Min(count, sids.Length - start);
		var result = new string[length];
		Array.Copy(sids, start, result, 0, length);
		return result;
	}

	private static int ApplyList(BhCitySpecialView view, string fieldName, string[] explicitSids, StringBuilder sb)
	{
		var list = ReadMember(view, fieldName);
		var listCount = CountList(list);
		sb.Append(' ').Append(fieldName).Append("Count=").Append(listCount);
		sb.Append(' ').Append(fieldName).Append("Sids=").Append(explicitSids.Length);

		var applied = 0;
		var index = 0;
		var items = new List<object>();
		foreach (var item in EnumerateList(list))
			items.Add(item);

		for (var i = 0; i < items.Count; i++)
		{
			var item = items[i];
			var sidIndex = ResolveSidIndexForListSlot(fieldName, i, items.Count, explicitSids.Length);
			if (sidIndex < 0)
			{
				ClearPortrait(item);
				SetItemActive(item, false);
				continue;
			}

			if (sidIndex < explicitSids.Length && !string.IsNullOrWhiteSpace(explicitSids[sidIndex]))
			{
				if (TryApplyPortrait(item, explicitSids[sidIndex]))
				{
					SetItemActive(item, true);
					applied++;
				}
			}
			else
			{
				ClearPortrait(item);
				SetItemActive(item, false);
			}
			index++;
		}
		sb.Append(' ').Append(fieldName).Append("Applied=").Append(applied);
		return applied;
	}

	private static int ResolveSidIndexForListSlot(string fieldName, int slotIndex, int slotCount, int sidCount)
	{
		if (sidCount <= 0)
			return -1;
		if (string.Equals(fieldName, "itemsLow3", StringComparison.Ordinal)
		    && sidCount == 4
		    && slotCount == 3)
		{
			// Three low-row views for tiers 5-6 plus Dreadnought; Couatl stays off the mini strip.
			switch (slotIndex)
			{
				case 0: return 0;
				case 1: return 1;
				case 2: return 3;
				default: return -1;
			}
		}
		return slotIndex < sidCount ? slotIndex : -1;
	}

	private static void ApplyPhysicalLayout(Transform specialRoot, int sidCount, StringBuilder sb)
	{
		var specialView = specialRoot;
		if (specialView == null)
			return;

		var gameObjectRow = FindChildByName(specialView, "GameObject");
		var lowRow = FindChildByName(specialView, "LowRow");
		if (gameObjectRow == null || lowRow == null)
		{
			sb.Append(" layout=missing-row");
			return;
		}

		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL", true);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (1)", true);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (2)", true);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (3)", true);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (4)", false);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (5)", false);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (6)", false);
		SetNamedCardActive(gameObjectRow, "UNIT PREVIEW SMALL (7)", false);

		SetNamedCardActive(lowRow, "UNIT PREVIEW SMALL (4)", sidCount > 4);
		SetNamedCardActive(lowRow, "UNIT PREVIEW SMALL (5)", sidCount > 5);
		SetNamedCardActive(lowRow, "UNIT PREVIEW SMALL (6)", sidCount > 6);

		sb.Append(" layout=4top+3low");
		if (sidCount > 7)
			sb.Append("+dread-low6");
	}

	private static Transform FindChildByName(Transform root, string name)
	{
		if (root == null)
			return null;
		var children = root.GetComponentsInChildren<Transform>();
		for (var i = 0; i < children.Length; i++)
		{
			var child = children[i];
			if (child != null && string.Equals(child.name, name, StringComparison.Ordinal))
				return child;
		}
		return null;
	}

	private static void SetNamedCardActive(Transform row, string cardName, bool active)
	{
		if (row == null)
			return;
		var children = row.GetComponentsInChildren<Transform>();
		for (var i = 0; i < children.Length; i++)
		{
			var child = children[i];
			if (child == null || !string.Equals(child.name, cardName, StringComparison.Ordinal))
				continue;
			if (child.parent != null && child.parent.name.IndexOf("UNIT SELECTION", StringComparison.Ordinal) >= 0)
				continue;
			child.gameObject.SetActive(active);
		}
	}

	private static object ReadMember(object target, string name)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		var prop = type.GetProperty(name, All);
		if (prop != null)
			return prop.GetValue(target);
		var field = type.GetField(name, All);
		return field?.GetValue(target);
	}

	private static int CountList(object list)
	{
		var count = 0;
		foreach (var _ in EnumerateList(list))
			count++;
		return count;
	}

	private static IEnumerable EnumerateList(object list)
	{
		if (list == null)
			yield break;

		if (list is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}

		var type = list.GetType();
		var countProp = type.GetProperty("Count", All) ?? type.GetProperty("count", All);
		var getItem = type.GetMethod("get_Item", All, null, new[] { typeof(int) }, null)
		              ?? type.GetMethod("GetItem", All, null, new[] { typeof(int) }, null);
		if (countProp == null || getItem == null)
			yield break;
		var count = Convert.ToInt32(countProp.GetValue(list));
		for (var i = 0; i < count; i++)
		{
			var item = getItem.Invoke(list, new object[] { i });
			if (item != null)
				yield return item;
		}
	}

	private static bool TryApplyPortrait(object item, string sid)
	{
		if (item == null || string.IsNullOrWhiteSpace(sid))
			return false;
		if (!TryResolveSprite(sid, out var sprite) || sprite == null)
			return false;

		var image = FindPortraitImage(item);
		if (image == null)
			return false;

		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.enabled = true;
		var component = item as Component;
		if (component != null)
			component.gameObject.SetActive(true);
		return true;
	}

	private static void ClearPortrait(object item)
	{
		var image = FindPortraitImage(item);
		if (image != null)
		{
			image.sprite = null;
			image.overrideSprite = null;
			image.enabled = false;
		}
		SetItemActive(item, false);
	}

	private static void SetItemActive(object item, bool active)
	{
		var component = item as Component;
		if (component != null && component.gameObject != null)
			component.gameObject.SetActive(active);
	}

	private static Image FindPortraitImage(object item)
	{
		var component = item as Component;
		if (component == null)
			return null;

		var direct = ReadMember(item, "pic") as Image;
		if (direct != null)
			return direct;

		var images = component.GetComponentsInChildren<Image>();
		Image best = null;
		var bestScore = int.MinValue;
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image == null || image.gameObject == null)
				continue;
			var name = image.gameObject.name ?? string.Empty;
			var score = 0;
			if (name.IndexOf("Icon", StringComparison.OrdinalIgnoreCase) >= 0)
				score += 120;
			if (string.Equals(name, "pic", StringComparison.OrdinalIgnoreCase))
				score += 100;
			if (name.IndexOf("Mask", StringComparison.OrdinalIgnoreCase) >= 0)
				score -= 40;
			if (name.IndexOf("Back", StringComparison.OrdinalIgnoreCase) >= 0)
				score -= 60;
			if (name.IndexOf("Frame", StringComparison.OrdinalIgnoreCase) >= 0)
				score -= 60;
			if (score > bestScore)
			{
				bestScore = score;
				best = image;
			}
		}
		return bestScore >= 60 ? best : null;
	}

	private static bool TryResolveSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		var hook = Type.GetType("OfflineUnlockMod.Homm3CustomUiIconHook, OfflineUnlockMod");
		if (hook == null)
			return false;
		var method = hook.GetMethod("TryResolveSprite", All);
		if (method == null)
			return false;
		var args = new object[] { sid, null };
		var ok = (bool)method.Invoke(null, args);
		sprite = args[1] as Sprite;
		return ok && sprite != null;
	}

	private static string Fail(StringBuilder sb, string message)
	{
		return "{\"ok\":false,\"text\":\"" + Escape(sb + " " + message) + "\"}";
	}

	private static string Escape(string value)
	{
		return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"");
	}
}
