using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Seeds live dtj/ccns and eta/esd hero entries for AI driver screen_dump when Il2Cpp scans are cold.
/// Populated from Harmony postfixes that already hold live logic-side instances.
/// </summary>
internal static class Homm3AiDriverLogicHeroRegistry
{
	private const string GrepKey = "HOMM3_AI_LOGIC_HERO_REGISTRY";
	private static readonly List<object> Entries = new List<object>(16);
	private static readonly HashSet<long> SeenNativeKeys = new HashSet<long>();
	private static bool _registered;
	private static ManualLogSource _log;
	private static PropertyInfo _sideHeroListProperty;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		_log = log;
		var type = GameMember.FindType(
			GameSymbols.SwashbucklerGold.SideLogicTypeId,
			GameSymbols.SwashbucklerGold.SideLogicTypeHint,
			ResolveSideLogicTypeByShape);
		if (type == null)
		{
			log?.LogWarning(GrepKey + " dtj side logic type not found; logic hero registry skipped.");
			return;
		}

		var startDay = AccessTools.Method(type, GameSymbols.SwashbucklerGold.SideStartDayName, Type.EmptyTypes);
		if (startDay == null)
		{
			log?.LogWarning(GrepKey + " dtj OnStartDay not found; logic hero registry skipped.");
			return;
		}

		_sideHeroListProperty = FindHeroListProperty(type);
		if (_sideHeroListProperty == null)
		{
			log?.LogWarning(GrepKey + " dtj ccns hero list not found; logic hero registry skipped.");
			return;
		}

		harmony.Patch(startDay, postfix: new HarmonyMethod(typeof(Homm3AiDriverLogicHeroRegistry), nameof(PostfixSideStartDay)));
		_registered = true;
		log?.LogWarning(GrepKey + " registered dtj." + startDay.Name + " postfix for logic-world hero seeding.");
	}

	internal static void TryRecordSessionHero(object sessionHero, string source)
	{
		if (sessionHero == null)
			return;
		TryAddEntry(sessionHero, source ?? "sessionHero");
	}

	internal static int CopyEntriesTo(List<object> target)
	{
		if (target == null)
			return 0;
		var before = target.Count;
		lock (Entries)
		{
			for (var i = 0; i < Entries.Count; i++)
			{
				var entry = Entries[i];
				if (entry != null)
					target.Add(entry);
			}
		}
		return target.Count - before;
	}

	internal static string DescribeState()
	{
		lock (Entries)
			return "registry count=" + Entries.Count.ToString(CultureInfo.InvariantCulture);
	}

	private static void PostfixSideStartDay(object __instance)
	{
		try
		{
			RecordLogicSideHeroes(__instance, "dtj.OnStartDay");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " OnStartDay seed failed: " + ex.Message);
		}
	}

	internal static void RecordLogicSideHeroes(object logicSide, string source)
	{
		if (logicSide == null)
			return;

		var heroList = _sideHeroListProperty != null
			? _sideHeroListProperty.GetValue(logicSide)
			: ReadFirstMemberValue(logicSide, GameSymbols.SwashbucklerGold.SideHeroListProperties);
		if (heroList == null)
			return;

		var added = 0;
		foreach (var entry in EnumerateIl2CppList(heroList))
		{
			if (TryAddEntry(entry, source))
				added++;
		}

		if (added > 0)
			_log?.LogWarning(GrepKey + " seeded " + added.ToString(CultureInfo.InvariantCulture) + " hero row(s) from " + (source ?? "?") + ".");
	}

	private static bool TryAddEntry(object entry, string source)
	{
		if (entry == null)
			return false;
		if (!Homm3DirectStateIdentity.TryResolveKey(entry, out var key, out _) || key == 0)
		{
			// Still retain entry when native key is unavailable; dedupe by reference for managed shells.
			lock (Entries)
			{
				if (Entries.Contains(entry))
					return false;
				Entries.Add(entry);
			}
			return true;
		}

		lock (SeenNativeKeys)
		{
			if (!SeenNativeKeys.Add(key))
				return false;
		}

		lock (Entries)
			Entries.Add(entry);
		_ = source;
		return true;
	}

	private static IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;
		if (list is System.Collections.IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}

		for (var i = 0; i < 64; i++)
		{
			object item = null;
			try
			{
				var getter = list.GetType().GetMethod(
					"get_Item",
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					new[] { typeof(int) },
					null);
				if (getter == null)
					break;
				item = getter.Invoke(list, new object[] { i });
			}
			catch
			{
				break;
			}
			if (item == null)
				break;
			yield return item;
		}
	}

	private static object ReadFirstMemberValue(object instance, string[] names)
	{
		if (instance == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			if (string.IsNullOrWhiteSpace(names[i]))
				continue;
			try
			{
				var field = instance.GetType().GetField(names[i], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null)
				{
					var value = field.GetValue(instance);
					if (value != null)
						return value;
				}
				var property = instance.GetType().GetProperty(names[i], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (property?.GetMethod != null)
				{
					var value = property.GetValue(instance);
					if (value != null)
						return value;
				}
			}
			catch { /* Il2Cpp reflection best-effort */ }
		}
		return null;
	}

	private static Type ResolveSideLogicTypeByShape()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null || !string.Equals(asm.GetName().Name, "Hex", StringComparison.OrdinalIgnoreCase))
				continue;
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			catch { continue; }

			foreach (var candidate in types)
			{
				if (candidate == null)
					continue;
				if (AccessTools.Method(candidate, GameSymbols.SwashbucklerGold.SideStartDayName, Type.EmptyTypes) == null)
					continue;
				if (FindHeroListProperty(candidate) == null)
					continue;
				return candidate;
			}
		}
		return null;
	}

	private static PropertyInfo FindHeroListProperty(Type sideLogicType)
	{
		if (sideLogicType == null)
			return null;
		foreach (var name in GameSymbols.SwashbucklerGold.SideHeroListProperties)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = sideLogicType.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (property?.GetMethod != null)
				return property;
		}
		return null;
	}
}
