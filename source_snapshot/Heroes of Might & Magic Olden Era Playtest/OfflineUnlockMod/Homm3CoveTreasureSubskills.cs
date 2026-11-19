using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using BattleHex = Hex.Session.Battle.Hex;
using BuffDuration = Hex.Session.Data.BuffDuration;
using DataHero = Hex.Session.Data.Hero;
using LogicHero = Hex.Session.Logic.Hero;
using R = OfflineUnlockMod.Homm3CoveTreasureRuntime;

namespace OfflineUnlockMod;

/// <summary>
/// The picks of the Cove faction skill Treasure Hunting (docs/cove_treasure_hunting_design.md section 7). Their Core
/// rows carry no bonuses; everything happens here.
/// - Archivist: granted in <see cref="R"/> (bonus map piece per region); this class only answers "has the pick".
/// - Lay of the Land: hero buff <see cref="LayOfTheLandHeroBuff"/> (no terrain penalty) while the hero stands in a
///   region its side holds a piece of; with two pieces, +1 Speed (<see cref="LayOfTheLandSpeedBuff"/>) for its units in
///   battles there.
/// - Collector of Secrets: hero buff <see cref="CollectorHeroBuffPrefix"/>N, one level (+2 to all four primary stats)
///   per treasure the hero dug up. The buff is saved with the hero, so it needs no persistence of its own.
/// - Tireless Captain: read by Homm3CoveTreasureDig (no movement needed or spent).
/// - Ancient Curses: in regions where the hero's side dug up the treasure, every enemy unit starts the battle with
///   native Despair.
/// Sids and the Collector cap must match tools/release_port/apply_release_core_overlay.py (HOMM3_COVE_*).
/// </summary>
internal static class Homm3CoveTreasureSubskills
{
	private const string Prefix = "sub_skill_faction_homm3_cove_treasure_hunting_";
	internal const string Archivist = Prefix + "archivist";
	internal const string LayOfTheLand = Prefix + "lay_of_the_land";
	internal const string CollectorOfSecrets = Prefix + "collector_of_secrets";
	internal const string TirelessCaptain = Prefix + "tireless_captain";
	internal const string AncientCurses = Prefix + "ancient_curses";

	internal const string LayOfTheLandHeroBuff = "homm3_cove_lay_of_the_land";
	internal const string LayOfTheLandSpeedBuff = "homm3_cove_lay_of_the_land_speed_buff";
	internal const string CollectorHeroBuffPrefix = "homm3_cove_collector_of_secrets_";
	internal const int CollectorMaxLevel = 30;
	internal const string DespairBuff = "magic_despair_effect";
	// In game a duration of 2 lasted one turn (user test, 2026-11-17): the round it is added in counts. 4 gives three turns.
	internal const int DespairRounds = 4;
	private const int BattleLongDuration = 99;
	private const float PickCacheSeconds = 2f;

	private static ManualLogSource _log;
	private static int _logged;
	private static bool _attempted;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAdd, _buffRemove, _buffGet;
	private static readonly Dictionary<int, LogicHero> LogicHeroes = new();
	private static readonly Dictionary<(int Hero, string Sid), (float At, bool Has)> PickCache = new();

	private static void Info(string message)
	{
		if (_logged++ < 200)
			_log?.LogInfo(R.LogPrefix + "picks: " + message);
	}

	private static void Warn(string message)
	{
		if (_logged++ < 200)
			_log?.LogWarning(R.LogPrefix + "picks: " + message);
	}

	private static string N(int value) => value.ToString(CultureInfo.InvariantCulture);

	// ---------------------------------------------------------------- registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted)
			return;
		_attempted = true;
		_log = log;
		var notes = new List<string>();
		try
		{
			_buffManagerProperty = typeof(LogicHero).GetProperty(GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                       ?? throw new MissingMemberException("logic hero buff manager");
			var managerType = _buffManagerProperty.PropertyType;
			_buffAdd = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd);
			_buffRemove = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerRemove);
			_buffGet = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, null, new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerGet);
			if (_buffAdd == null || _buffRemove == null || _buffGet == null)
				throw new MissingMethodException("hero buff manager add/remove/get");
			notes.Add("hero buffs ok");
		}
		catch (Exception ex)
		{
			_buffManagerProperty = null;
			notes.Add("hero buffs FAILED (Lay of the Land terrain and Collector of Secrets off): " + ex.GetBaseException().Message);
		}
		try
		{
			if (!Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("homm3.cove.treasurePicks", OnDayStartHero, out var failure))
				notes.Add("day-start bus FAILED: " + failure);
			else
				notes.Add("day-start ok");
		}
		catch (Exception ex)
		{
			notes.Add("day-start bus FAILED: " + ex.GetBaseException().Message);
		}
		try
		{
			RegisterBattle(harmony);
			notes.Add("battle ok");
		}
		catch (Exception ex)
		{
			notes.Add("battle FAILED (Lay of the Land speed and Ancient Curses off): " + ex.GetBaseException().Message);
		}
		_log?.LogInfo(R.LogPrefix + "picks registered: " + string.Join("; ", notes) + ".");
	}

	// ---------------------------------------------------------------- pick lookup

	/// <summary>Whether the hero has learned the pick. Cached briefly: the map tick asks every time it runs.</summary>
	internal static bool Has(DataHero hero, string pickSid)
	{
		if (hero == null)
			return false;
		var key = (hero.field_Public_Int32_0, pickSid);
		var now = Time.realtimeSinceStartup;
		if (PickCache.TryGetValue(key, out var cached) && now - cached.At < PickCacheSeconds && now >= cached.At)
			return cached.Has;
		bool has;
		try { has = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, pickSid); }
		catch { has = false; }
		PickCache[key] = (now, has);
		return has;
	}

	// ---------------------------------------------------------------- hero buffs (map)

	private static int OnDayStartHero(object entry)
	{
		try
		{
			if (entry is LogicHero lh && Homm3FactoryLogisticsRuntime.DataHeroOf(lh) is { } dh)
				Remember(lh, dh);
		}
		catch
		{
			// Diagnostic-free: the next day start or Dig remembers the hero.
		}
		return 0;
	}

	internal static void Remember(LogicHero logicHero, DataHero hero)
	{
		if (logicHero != null && hero != null)
			LogicHeroes[hero.field_Public_Int32_0] = logicHero;
	}

	private static object ManagerOf(DataHero hero)
	{
		if (_buffManagerProperty == null || hero == null || !LogicHeroes.TryGetValue(hero.field_Public_Int32_0, out var lh) || lh == null || lh.Pointer == IntPtr.Zero)
			return null;
		// A logic hero from an earlier session must not be written to.
		if (Homm3FactoryLogisticsRuntime.DataHeroOf(lh) is not { } current || current.Pointer != hero.Pointer)
		{
			LogicHeroes.Remove(hero.field_Public_Int32_0);
			return null;
		}
		return _buffManagerProperty.GetValue(lh);
	}

	private static bool HasBuff(object manager, string sid) => _buffGet.Invoke(manager, new object[] { sid }) != null;

	private static bool SetBuff(object manager, string sid, bool wanted)
	{
		if (HasBuff(manager, sid) == wanted)
			return true;
		if (wanted)
		{
			var durations = new Il2CppReferenceArray<BuffDuration>(1);
			durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
			_buffAdd.Invoke(manager, new object[] { sid, durations });
		}
		else
		{
			_buffRemove.Invoke(manager, new object[] { sid });
		}
		return HasBuff(manager, sid) == wanted;
	}

	/// <summary>Map tick, per Cove hero: no terrain penalty while it stands in a region its side has a piece of.</summary>
	internal static void RefreshLayOfTheLand(DataHero hero, int piecesHere)
	{
		try
		{
			var manager = ManagerOf(hero);
			if (manager == null)
				return;
			var wanted = piecesHere >= 1 && Has(hero, LayOfTheLand);
			if (HasBuff(manager, LayOfTheLandHeroBuff) == wanted)
				return;
			if (SetBuff(manager, LayOfTheLandHeroBuff, wanted))
				Info("Lay of the Land " + (wanted ? "on" : "off") + " for hero " + hero.configSid + " (pieces here " + N(piecesHere) + ").");
			else
				Warn("Lay of the Land buff did not " + (wanted ? "stick" : "clear") + " on hero " + hero.configSid + " (missing heroes_buffs row?).");
		}
		catch (Exception ex)
		{
			Warn("Lay of the Land refresh threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>A hero dug up a treasure. Returns the popup line when Collector of Secrets paid out, else null.</summary>
	internal static string OnTreasureDug(LogicHero logicHero, DataHero hero)
	{
		try
		{
			Remember(logicHero, hero);
			if (!Has(hero, CollectorOfSecrets))
				return null;
			var manager = ManagerOf(hero);
			if (manager == null)
			{
				Warn("Collector of Secrets: hero " + hero.configSid + " has no buff manager; no stats granted.");
				return null;
			}
			var level = 0;
			for (var i = CollectorMaxLevel; i >= 1 && level == 0; i--)
				if (HasBuff(manager, CollectorHeroBuffPrefix + N(i)))
					level = i;
			if (level >= CollectorMaxLevel)
				return null;
			var next = level + 1;
			if (!SetBuff(manager, CollectorHeroBuffPrefix + N(next), true))
			{
				Warn("Collector of Secrets level " + N(next) + " did not stick on hero " + hero.configSid + " (missing heroes_buffs row?).");
				return null;
			}
			if (level > 0 && !SetBuff(manager, CollectorHeroBuffPrefix + N(level), false))
				Warn("Collector of Secrets level " + N(level) + " was not cleared on hero " + hero.configSid + ": the hero holds two levels.");
			Info("Collector of Secrets level " + N(next) + " (+" + N(2 * next) + " to all primary stats) for hero " + hero.configSid + ".");
			return "Collector of Secrets: +2 Attack, Defence, Spell Power and Knowledge";
		}
		catch (Exception ex)
		{
			Warn("Collector of Secrets threw " + ex.GetBaseException().Message);
			return null;
		}
	}

	// ---------------------------------------------------------------- battle

	private sealed class BattleSide
	{
		internal IntPtr Wrapper;
		internal bool Speed;
		internal bool Curse;
		internal string Hero;
	}

	private sealed class Battle
	{
		internal object Logic;
		internal IntPtr Hub;
		internal bool Applied;
		internal readonly List<BattleSide> Sides = new();
	}

	private static readonly object Gate = new();
	private static readonly List<Battle> Battles = new();
	private static MethodInfo _logicHeroDataHeroGetter;

	private static string At(string[] names) => names != null && names.Length > 0 ? names[0] : "";

	private static void RegisterBattle(Harmony harmony)
	{
		if (harmony == null)
			throw new ArgumentNullException(nameof(harmony));
		var hexAssembly = typeof(TransferBattle).Assembly;
		var logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName) ?? throw new TypeLoadException("Hex.Session.Logic.Hero");
		foreach (var name in GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var getter = logicHeroType.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
			if (getter != null && getter.ReturnType == typeof(DataHero))
			{
				_logicHeroDataHeroGetter = getter;
				break;
			}
		}
		if (_logicHeroDataHeroGetter == null)
			throw new MissingMethodException("logic hero data getter");
		Type logicType = null;
		foreach (var hint in GameSymbols.InfernoGating.BattleLogicTypeHints)
			if (!string.IsNullOrWhiteSpace(hint) && hexAssembly.GetType(hint) is { } found)
			{
				logicType = found;
				break;
			}
		if (logicType == null)
			throw new TypeLoadException("battle logic type");
		var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
			           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
		           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
		var hubsProperty = logicType.GetProperty(At(GameSymbols.InfernoGating.LogicHubsMembers), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		                   ?? throw new MissingMemberException("battle logic hubs");
		var hubProperty = hubsProperty.PropertyType.GetProperty(At(GameSymbols.InfernoGating.HubsRoundHubMembers), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		                  ?? throw new MissingMemberException("battle round hub");
		var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubProperty.PropertyType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var initPostfix = typeof(Homm3CoveTreasureSubskills).GetMethod(nameof(PostfixBattleLogicInit), flags);
		var roundPostfix = typeof(Homm3CoveTreasureSubskills).GetMethod(nameof(PostfixRoundStarted), flags);
		if (!GameMember.IsHarmonyPatchCompatible(init, initPostfix, out var why) || !GameMember.IsHarmonyPatchCompatible(roundStarted, roundPostfix, out why))
			throw new MissingMethodException("battle postfix incompatible: " + why);
		harmony.Patch(init, postfix: new HarmonyMethod(initPostfix) { priority = Priority.Last });
		harmony.Patch(roundStarted, postfix: new HarmonyMethod(roundPostfix) { priority = Priority.Last });
	}

	private static object Read(object obj, string[] names) => Homm3FortressPredatorInstinctRuntime.ReadProperty(obj, At(names));

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1)
	{
		try
		{
			lock (Gate)
				Battles.RemoveAll(b => ReferenceEquals(b.Logic, __instance));
			if (__1?.sides == null)
				return;
			var clone = Read(__instance, GameSymbols.InfernoGating.LogicBattleCloneMembers) as TransferBattle;
			var hub = Read(Read(__instance, GameSymbols.InfernoGating.LogicHubsMembers), GameSymbols.InfernoGating.HubsRoundHubMembers) as Il2CppObjectBase;
			if (clone?.sides == null || hub == null)
				return;
			Battle battle = null;
			for (var i = 0; i < __1.sides.Length && i < clone.sides.Length; i++)
			{
				var logicHero = __1.sides[i]?.logicHero;
				if (logicHero == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
					continue;
				if (_logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) is not DataHero hero)
					continue;
				var speedPick = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, LayOfTheLand);
				var cursePick = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, AncientCurses);
				if (!speedPick && !cursePick)
					continue;
				var area = R.AreaOf(hero.node);
				var speed = speedPick && area >= 0 && R.PiecesOf(hero.sideId, area) >= 2;
				var curse = cursePick && area >= 0 && R.DugBy(hero.sideId, area);
				Info("battle: hero " + hero.configSid + " side " + N(hero.sideId) + " at node " + N(hero.node) + " area " + N(area)
					+ ": Lay of the Land speed " + (speed ? "on" : speedPick ? "off (needs 2 pieces here)" : "not learned")
					+ ", Ancient Curses " + (curse ? "on" : cursePick ? "off (treasure here not dug by this side)" : "not learned") + ".");
				if (!speed && !curse)
					continue;
				IntPtr wrapper = IntPtr.Zero;
				var wrappers = Read(Read(__instance, GameSymbols.InfernoGating.LogicStateMembers), GameSymbols.InfernoGating.StateSideWrappersMembers);
				if (wrappers is System.Collections.IEnumerable enumerable)
				{
					foreach (var w in enumerable)
					{
						if (Read(w, GameSymbols.InfernoGating.SideWrapperTransferSideMembers) is TransferSide ts && ts.Pointer == clone.sides[i].Pointer && w is Il2CppObjectBase wo)
						{
							wrapper = wo.Pointer;
							break;
						}
					}
				}
				if (wrapper == IntPtr.Zero)
				{
					Warn("battle: side wrapper for hero " + hero.configSid + " not found; picks skipped this battle.");
					continue;
				}
				battle ??= new Battle { Logic = __instance, Hub = hub.Pointer };
				battle.Sides.Add(new BattleSide { Wrapper = wrapper, Speed = speed, Curse = curse, Hero = hero.configSid });
			}
			if (battle == null)
				return;
			lock (Gate)
			{
				Battles.Add(battle);
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			Warn("battle Init postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			if (__instance is not Il2CppObjectBase hub || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args || args.roundNumber < 1)
				return;
			Battle battle = null;
			lock (Gate)
			{
				foreach (var b in Battles)
					if (b.Hub == hub.Pointer && !b.Applied)
					{
						battle = b;
						b.Applied = true;
						break;
					}
			}
			if (battle != null)
				Apply(battle);
		}
		catch (Exception ex)
		{
			Warn("battle RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void Apply(Battle battle)
	{
		var grid = Read(battle.Logic, GameSymbols.InfernoGating.LogicGridMembers);
		if (Read(grid, GameSymbols.InfernoGating.GridHexesMembers) is not Il2CppReferenceArray<BattleHex> hexes)
		{
			Warn("battle: grid unreadable; picks skipped.");
			return;
		}
		var seen = new HashSet<long>();
		var fast = 0;
		var cursed = 0;
		var failed = 0;
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				if (unit == null || !Homm3FortressPredatorInstinctRuntime.IsAlive(unit) || Read(unit, GameSymbols.InfernoGating.FieldObjectSideMembers) is not Il2CppObjectBase wrapper)
					continue;
				var key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
				if (key == 0 || !seen.Add(key))
					continue;
				foreach (var side in battle.Sides)
				{
					var own = wrapper.Pointer == side.Wrapper;
					if (own && side.Speed)
					{
						if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, LayOfTheLandSpeedBuff, unit, 1, BattleLongDuration, 1, true, out _, out _))
							fast++;
						else
							failed++;
					}
					else if (!own && side.Curse)
					{
						// Added straight to the unit, not cast: spell immunities do not see it.
						if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, DespairBuff, unit, 1, DespairRounds, 0, true, out _, out _))
							cursed++;
						else
							failed++;
					}
				}
			}
		}
		Info("battle: Lay of the Land +1 Speed on " + N(fast) + " units, Ancient Curses Despair on " + N(cursed) + " units" + (failed > 0 ? ", " + N(failed) + " FAILED" : "") + ".");
	}
}
