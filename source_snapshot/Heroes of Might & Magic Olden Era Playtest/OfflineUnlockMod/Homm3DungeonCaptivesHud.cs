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
/// Dungeon Captives UI values and text: the hero-portrait skill meter (shared Homm3HeroSkillMeterHud,
/// geometry in Homm3HeroSkillMeterLayout) and the hero-profile buff tooltip. Meter fill = effective
/// strength / next tier threshold (cumulative, the same two numbers the hover text shows).
/// tools/homm3_hero_skill_meter_mockup.py parses <see cref="Layout"/>; revise values here only.
/// </summary>
internal static class Homm3DungeonCaptivesUi
{
	internal sealed class Snapshot
	{
		internal int Squads;
		internal long Strength;
		internal long EffectiveStrength;
		internal int Tier;
		internal int NextThreshold;
		internal float Progress;
		internal int ExecuteXp;
		internal int InterrogationMana;
		internal int RansomGold;
		internal int Rank;
		internal bool DungeonCells;
		internal bool Interrogation;
		internal bool SlaveMarkets;
	}

	internal static class Layout
	{
		internal const string MeterKey = "dungeon_captives";
		internal const int MeterOrder = 10;
		/// <summary>One Captives icon for the meter socket and the tier buffs (overlay buff rows use the same key).</summary>
		internal const string IconKey = "skill_faction_homm3_dungeon";
		internal static readonly Color FillColor = new(0.80f, 0.32f, 0.30f, 1f);

		// Hover / buff tooltip text (TMP rich text).
		internal const string TooltipHeadingColor = "#D6BC7C";
		internal const string TooltipBarFillColor = "#CC5248";
		internal const string TooltipBarEmptyColor = "#5A5048";
		internal const string TooltipNoteColor = "#B4ADA3";
		internal const int TooltipBarSegments = 20;
		internal const char TooltipBarGlyph = '|';
	}

	internal static string FormatNumber(long value)
	{
		return value.ToString("N0", CultureInfo.InvariantCulture);
	}

	internal static string BuildTextBar(float progress)
	{
		var filled = Mathf.Clamp(Mathf.RoundToInt(Mathf.Clamp01(progress) * Layout.TooltipBarSegments), 0, Layout.TooltipBarSegments);
		return "<color=" + Layout.TooltipBarFillColor + ">" + new string(Layout.TooltipBarGlyph, filled) + "</color>"
			+ "<color=" + Layout.TooltipBarEmptyColor + ">" + new string(Layout.TooltipBarGlyph, Layout.TooltipBarSegments - filled) + "</color>";
	}

	private static void AppendHeld(StringBuilder sb, Snapshot s)
	{
		if (s.Strength <= 0)
		{
			sb.Append("No captives held. Let fleeing enemy squads go to capture them.");
			return;
		}
		sb.Append(s.Squads).Append(s.Squads == 1 ? " squad, " : " squads, ").Append(FormatNumber(s.Strength)).Append(" strength");
		if (s.DungeonCells)
			sb.Append(" (").Append(FormatNumber(s.EffectiveStrength)).Append(" with Dungeon Cells)");
	}

	private static void AppendTier(StringBuilder sb, Snapshot s)
	{
		sb.Append(s.Tier > 0 ? "Tier " + s.Tier + ": +" + s.Tier + " Attack, +" + s.Tier + " Defense" : "No tier bonus yet").Append('\n');
		sb.Append(s.NextThreshold > 0
			? "Next: Tier " + (s.Tier + 1) + " at " + FormatNumber(s.NextThreshold) + " (" + FormatNumber(s.EffectiveStrength) + " / " + FormatNumber(s.NextThreshold) + ")"
			: "Maximum tier");
	}

	private static void AppendYields(StringBuilder sb, Snapshot s, string heading)
	{
		if (s.Rank <= 0 || s.Strength <= 0)
			return;
		sb.Append("\n<color=").Append(Layout.TooltipHeadingColor).Append(">").Append(heading).Append("</color>\n");
		sb.Append("Execute: +").Append(FormatNumber(s.ExecuteXp)).Append(" XP");
		if (s.InterrogationMana > 0)
			sb.Append(", +").Append(FormatNumber(s.InterrogationMana)).Append(" mana <color=").Append(Layout.TooltipNoteColor).Append(">(Interrogation)</color>");
		sb.Append("\nRansom: +").Append(FormatNumber(s.RansomGold)).Append(" gold");
		if (s.SlaveMarkets)
			sb.Append(" <color=").Append(Layout.TooltipNoteColor).Append(">(Slave Markets +25%)</color>");
	}

	/// <summary>Native hover tooltip of the Captives meter (the fill is the bar, so no text bar here).</summary>
	internal static string BuildMeterTooltip(Snapshot s)
	{
		var sb = new StringBuilder();
		sb.Append("<color=").Append(Layout.TooltipHeadingColor).Append(">Captives</color>\n");
		AppendHeld(sb, s);
		sb.Append('\n');
		AppendTier(sb, s);
		AppendYields(sb, s, "Cast now");
		return sb.ToString();
	}

	/// <summary>Live block that replaces the duration text of the Captives tier buff tooltip.</summary>
	internal static string BuildTooltipLiveText(Snapshot s)
	{
		var sb = new StringBuilder();
		sb.Append("<color=").Append(Layout.TooltipHeadingColor).Append(">Captives held</color>\n");
		AppendHeld(sb, s);
		sb.Append('\n').Append(BuildTextBar(s.Progress)).Append('\n');
		AppendTier(sb, s);
		AppendYields(sb, s, "If cast now");
		return sb.ToString();
	}

	internal static Homm3HeroSkillMeterState BuildMeterState(Snapshot s)
	{
		return new Homm3HeroSkillMeterState
		{
			Fill = s.Progress,
			Tooltip = BuildMeterTooltip(s),
			LogSummary = "squads=" + s.Squads + " strength=" + s.Strength + " effective=" + s.EffectiveStrength + " tier=" + s.Tier + " next=" + s.NextThreshold
				+ " fill=" + s.Progress.ToString("0.000", CultureInfo.InvariantCulture) + " execute=+" + s.ExecuteXp + "xp ransom=+" + s.RansomGold + "g rank=" + s.Rank,
		};
	}
}

/// <summary>
/// Registers the Captives meter with the shared hero-skill meter (shown while the selected hero has
/// skill_faction_homm3_dungeon) and forwards the runtime's state-change notifications to it.
/// </summary>
internal static class Homm3DungeonCaptivesHud
{
	private static bool _registered;

	internal static bool IsRegistered => _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		_registered = Homm3HeroSkillMeterHud.Register(new Homm3HeroSkillMeterSpec
		{
			Key = Homm3DungeonCaptivesUi.Layout.MeterKey,
			Order = Homm3DungeonCaptivesUi.Layout.MeterOrder,
			IconKey = Homm3DungeonCaptivesUi.Layout.IconKey,
			FillColor = Homm3DungeonCaptivesUi.Layout.FillColor,
			SpentFillColor = Homm3DungeonCaptivesUi.Layout.FillColor,
			Read = ReadMeter,
		}, harmony, log);
		if (_registered)
			log?.LogInfo("HoMM3 Dungeon Captives [meter] registered: key " + Homm3DungeonCaptivesUi.Layout.MeterKey + " on the shared hero skill meter (shown for heroes with " + Homm3DungeonCaptivesRuntime.FactionSkillSid + ").");
		else
			log?.LogError("HoMM3 Dungeon Captives [meter] NOT registered (fail closed, no meter; captives and spells unaffected).");
	}

	private static bool ReadMeter(object logicHero, out Homm3HeroSkillMeterState state, out string failReason)
	{
		state = null;
		failReason = null;
		if (!Homm3DungeonCaptivesRuntime.IsLogicHero(logicHero))
		{
			failReason = "selected hero has no Logic.Hero";
			return false;
		}
		if (!Homm3DungeonCaptivesRuntime.TryBuildUiSnapshot(logicHero, out _, out var snapshot, out failReason))
			return false;
		if (snapshot.Rank > 0)
			state = Homm3DungeonCaptivesUi.BuildMeterState(snapshot);
		return true;
	}

	internal static void NotifyStateChanged(string reason)
	{
		Homm3HeroSkillMeterHud.NotifyStateChanged("captives " + reason);
	}

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
/// Live hero-profile tooltip for the Captives tier buffs. The native buff descriptions are static
/// lang SIDs, so instead of rewriting lang text the mod replaces the tooltip's third (duration) text:
/// BhHeroBuffView.OnHover calls its private duration-text builder (its only caller) and passes the
/// result to BhTooltips.Show(name, description, text, ...). A postfix on that builder swaps the
/// "infinite duration" text of a homm3_dungeon_captives_tier_N buff for the live Captives block,
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
			_log?.LogInfo("HoMM3 Dungeon Captives buff tooltip registered: " + dataViewType.Name + "." + init.Name + " (profile hero) + "
				+ buffViewType.Name + "." + durationText.Name + " (live text replaces the tier buff's duration line). Proof tier: build; runtime unproven.");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Dungeon Captives buff tooltip NOT registered (fail closed, native static tooltip): " + ex.GetBaseException().Message);
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
			if (sid == null || !sid.StartsWith(Homm3DungeonCaptivesRuntime.TierBuffPrefix, StringComparison.Ordinal))
				return;
			var view = __instance as Component;
			if (!view || _profileViewPointer == IntPtr.Zero || !_profileViewTransform || !view.transform.IsChildOf(_profileViewTransform))
			{
				Skip("tooltip for " + sid + " kept native: buff view is not under the last BhHeroDataView.Init hero.");
				return;
			}
			if (!Homm3DungeonCaptivesRuntime.IsLogicHero(_profileLogicHero)
			    || !Homm3DungeonCaptivesRuntime.TryBuildUiSnapshot(_profileLogicHero, out _, out var snapshot, out var failReason))
			{
				Skip("tooltip for " + sid + " kept native: captives state unreadable.");
				return;
			}
			__result = Homm3DungeonCaptivesUi.BuildTooltipLiveText(snapshot);
			if (_loggedApplies++ < 12)
				_log?.LogInfo("HoMM3 Dungeon Captives buff tooltip: live text for " + sid + " (squads=" + snapshot.Squads + " strength=" + snapshot.Strength + " tier=" + snapshot.Tier + ").");
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
			_log?.LogWarning("HoMM3 Dungeon Captives buff tooltip: " + message);
	}
}
