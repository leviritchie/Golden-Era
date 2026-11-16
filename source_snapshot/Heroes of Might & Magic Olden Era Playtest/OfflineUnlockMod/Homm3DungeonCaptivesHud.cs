using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// War Captives UI text: the live tooltip of the visible enslaved buff (homm3_dungeon_captives_enslaved).
/// The post-battle choice window is Homm3DungeonWarCaptivesWindow.
/// </summary>
internal static class Homm3DungeonCaptivesUi
{
	internal sealed class Snapshot
	{
		internal int Enslaved;
		internal int DailyGold;
		internal double GoldPerCaptive;
		internal int Rank;
		internal bool SlaveMarkets;
	}

	internal static class Layout
	{
		internal const string TooltipHeadingColor = "#D6BC7C";
		internal const string TooltipNoteColor = "#B4ADA3";
	}

	internal static string FormatNumber(long value)
	{
		return value.ToString("N0", CultureInfo.InvariantCulture);
	}

	/// <summary>Live block that replaces the duration text of the enslaved buff tooltip.</summary>
	internal static string BuildTooltipLiveText(Snapshot s)
	{
		var sb = new StringBuilder();
		sb.Append("<color=").Append(Layout.TooltipHeadingColor).Append(">Enslaved captives</color>\n");
		sb.Append(FormatNumber(s.Enslaved)).Append(s.Enslaved == 1 ? " captive" : " captives").Append(" working for this hero\n");
		sb.Append("+").Append(FormatNumber(s.DailyGold)).Append(" gold each day (")
			.Append(s.GoldPerCaptive.ToString("0.##", CultureInfo.InvariantCulture)).Append(" per captive)");
		if (s.SlaveMarkets)
			sb.Append(" <color=").Append(Layout.TooltipNoteColor).Append(">(Slave Markets +25%)</color>");
		sb.Append("\n<color=").Append(Layout.TooltipNoteColor).Append(">Lost if the hero is dismissed.</color>");
		return sb.ToString();
	}
}

/// <summary>Shared reflection reader (also used by Homm3HeroSkillMeterHud).</summary>
internal static class Homm3DungeonCaptivesHud
{
	internal static object ReadMember(object obj, IEnumerable<string> names)
	{
		if (obj == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cur = obj.GetType(); cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				var property = cur.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					var value = property.GetValue(obj);
					if (value != null)
						return value;
					break;
				}
				var field = cur.GetField(name, flags);
				if (field != null)
				{
					var value = field.GetValue(obj);
					if (value != null)
						return value;
					break;
				}
			}
		}
		return null;
	}
}

/// <summary>
/// Live hero-profile tooltip for the War Captives enslaved buff. The native buff descriptions are static
/// lang SIDs, so instead of rewriting lang text the mod replaces the tooltip's third (duration) text:
/// BhHeroBuffView.OnHover calls its private duration-text builder (its only caller) and passes the
/// result to BhTooltips.Show(name, description, text, ...). A postfix on that builder swaps the
/// "infinite duration" text of the homm3_dungeon_captives_enslaved buff for the live enslaved block,
/// computed on every hover from the profile hero's buffs, level-rank and subskills (so it is always
/// current; nothing to update when captives change). The profile hero comes from a postfix on
/// BhHeroDataView.Init(Logic.Hero, ...); the buff view must be a child of that data view.
/// </summary>
internal static class Homm3DungeonCaptivesBuffTooltip
{
	private static bool _registered;

	internal static bool IsRegistered => _registered;
	private static ManualLogSource _log;
	private static IntPtr _profileViewPointer;
	private static Transform _profileViewTransform;
	private static object _profileLogicHero;
	private static int _loggedApplies;
	private static int _loggedSkips;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var dataViewType = hexAssembly.GetType(GameSymbols.DungeonCaptives.HeroDataViewTypeName)
			                   ?? throw new TypeLoadException("Missing " + GameSymbols.DungeonCaptives.HeroDataViewTypeName);
			var buffViewType = hexAssembly.GetType(GameSymbols.DungeonCaptives.HeroBuffViewTypeName)
			                   ?? throw new TypeLoadException("Missing " + GameSymbols.DungeonCaptives.HeroBuffViewTypeName);
			var logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                    ?? throw new TypeLoadException("Missing Hex.Session.Logic.Hero");
			var init = FindExact(dataViewType, GameSymbols.DungeonCaptives.HeroDataViewInit, typeof(void), new[] { logicHeroType, typeof(bool), typeof(bool) });
			var durationText = FindExact(buffViewType, GameSymbols.DungeonCaptives.HeroBuffViewDurationText, typeof(string), Type.EmptyTypes);
			Patch(harmony, init, nameof(PostfixDataViewInit));
			Patch(harmony, durationText, nameof(PostfixDurationText));
			_registered = true;
			_log?.LogInfo("HoMM3 Dungeon War Captives buff tooltip registered: " + dataViewType.Name + "." + init.Name + " (profile hero) + "
				+ buffViewType.Name + "." + durationText.Name + " (live text replaces the enslaved buff's duration line). Proof tier: build; runtime unproven.");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Dungeon War Captives buff tooltip NOT registered (fail closed, native static tooltip): " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixDataViewInit(object __instance, [HarmonyArgument(0)] object _hero)
	{
		try
		{
			var view = __instance as Component;
			_profileViewPointer = (__instance as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
			_profileViewTransform = view ? view.transform : null;
			_profileLogicHero = _hero;
		}
		catch (Exception ex)
		{
			_profileViewPointer = IntPtr.Zero;
			_profileViewTransform = null;
			_profileLogicHero = null;
			Skip("profile hero capture failed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixDurationText(object __instance, ref string __result)
	{
		try
		{
			var logicBuff = Homm3DungeonCaptivesHud.ReadMember(__instance, GameSymbols.DungeonCaptives.HeroBuffViewBuffMembers);
			var dataBuff = Homm3DungeonCaptivesHud.ReadMember(logicBuff, GameSymbols.DungeonCaptives.LogicBuffDataMembers);
			var sid = Homm3DungeonCaptivesHud.ReadMember(dataBuff, GameSymbols.DungeonCaptives.DataBuffSidMembers) as string;
			if (sid == null || !string.Equals(sid, Homm3DungeonCaptivesRuntime.EnslavedBuffSid, StringComparison.Ordinal))
				return;
			var view = __instance as Component;
			if (!view || _profileViewPointer == IntPtr.Zero || !_profileViewTransform || !view.transform.IsChildOf(_profileViewTransform))
			{
				Skip("tooltip for " + sid + " kept native: buff view is not under the last BhHeroDataView.Init hero.");
				return;
			}
			string failReason = "not a logic hero";
			Homm3DungeonCaptivesUi.Snapshot snapshot = default;
			if (!Homm3DungeonCaptivesRuntime.IsLogicHero(_profileLogicHero)
			    || !Homm3DungeonCaptivesRuntime.TryBuildUiSnapshot(_profileLogicHero, out snapshot, out failReason))
			{
				Skip("tooltip for " + sid + " kept native: enslaved state unreadable (" + failReason + ").");
				return;
			}
			__result = Homm3DungeonCaptivesUi.BuildTooltipLiveText(snapshot);
			if (_loggedApplies++ < 12)
				_log?.LogInfo("HoMM3 Dungeon War Captives buff tooltip: live text for " + sid + " (enslaved=" + snapshot.Enslaved + " daily=" + snapshot.DailyGold + ").");
		}
		catch (Exception ex)
		{
			Skip("tooltip kept native after error: " + ex.GetBaseException().Message);
		}
	}

	private static MethodInfo FindExact(Type type, GameSymbols.MethodSymbol symbol, Type returnType, Type[] parameterTypes)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			var method = string.IsNullOrWhiteSpace(name) ? null : type.GetMethod(name, flags, null, parameterTypes, null);
			if (method != null && method.ReturnType == returnType)
				return method;
		}
		throw new MissingMethodException(symbol.Id + " exact method not found on " + type.FullName);
	}

	private static void Patch(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = typeof(Homm3DungeonCaptivesBuffTooltip).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}

	private static void Skip(string message)
	{
		if (_loggedSkips++ < 24)
			_log?.LogWarning("HoMM3 Dungeon War Captives buff tooltip: " + message);
	}
}
