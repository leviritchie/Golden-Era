using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Data;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (REVIEW §1): battle-only stats for the hero defending a siege of a town that has the
/// building. All ten HoMM3 siege-defender buildings live in <see cref="Entries"/>.
///
/// Hook: <c>BattleLogic.Init(int, TransferBattle, bool, bool)</c> (live type <c>ObjectPublicPrcnInPrcnSiBoPrcnInUnique</c>
/// / deob <c>epx</c>, resolved through <c>GameSymbols.DraconicDominion</c>). Native Init stores the passed TransferBattle
/// as <c>startedTransferBattle</c> and builds the battle from <c>transferBattle = started.Clone()</c>
/// (TransferSide.Clone deep-copies the hero and its HeroStat); <c>Side.UpdateStatSum</c> reads the clone's
/// <c>hero.heroStat</c>. So the prefix adds the bonus to the passed object, the clone carries it through the whole
/// battle, and the finalizer restores the passed object. Nothing reaches the world hero: <c>WorldHero.UpdateFromTransferSide</c>
/// copies units only, and battle end copies back current mana only.
///
/// Ordering against the other Init patchers (Harmony runs prefixes and finalizers each in descending priority):
/// - prefix at <see cref="Priority.High"/>: runs before the Normal-priority snapshotters (Conflux Elemental
///   Conjunction, Dungeon Terror Exploitation) so their snapshots include this bonus and their restores keep it;
///   after the Priority.First Factory/Bulwark force-setup pilot, which does not touch HeroStat.
/// - finalizer at <see cref="Priority.Low"/>: runs after every Normal-priority finalizer, so this one restores the
///   originals last.
/// Restores write back only the fields this runtime changed, to the values read just before the change.
/// </summary>
internal static class Homm3TownSiegeDefenseRuntime
{
	internal sealed class Entry
	{
		internal readonly string Name;
		internal readonly string CitySid;
		internal readonly string BuildingSid;
		internal readonly int Level;
		internal readonly int Offence;
		internal readonly int Defence;
		internal readonly int SpellPower;
		internal readonly int Knowledge;
		internal readonly int Morale;
		internal readonly int Luck;

		internal Entry(string name, string citySid, string buildingSid, int offence = 0, int defence = 0, int spellPower = 0, int knowledge = 0, int morale = 0, int luck = 0, int level = 1)
		{
			Name = name;
			CitySid = citySid;
			BuildingSid = buildingSid;
			Level = level;
			Offence = offence;
			Defence = defence;
			SpellPower = spellPower;
			Knowledge = knowledge;
			Morale = morale;
			Luck = luck;
		}
	}

	/// <summary>Final SIDs confirmed by the coordinator 2026-11-22 (grails keep their grail IDs).</summary>
	internal static readonly Entry[] Entries =
	{
		new("Brotherhood of the Sword", "homm3_castle_city", "Build_Mother_Nature", morale: 2),
		new("Fountain of Fortune", "homm3_rampart_city", "Build_Mother_Nature", luck: 2),
		new("Glyphs of Fear", "homm3_fortress_city", "Build_Mother_Nature", defence: 2),
		new("Blood Obelisk", "homm3_fortress_city", "Build_Mycelium_Roots", offence: 2),
		new("Carnivorous Plant", "homm3_fortress_city", "Build_Spring_of_Life", offence: 10, defence: 10),
		new("Brimstone Stormclouds", "homm3_inferno_city", "Build_Resource_Depot_level_2", spellPower: 2),
		new("Warlords' Monument", "homm3_stronghold_city", "Build_Spy_Network", offence: 20),
		new("Guardian of Earth", "homm3_dungeon_city", "Build_Spy_Network", spellPower: 12),
		new("Skyship", "homm3_tower_city", "Build_Golden_Calf", knowledge: 15),
		new("Spirits of the Forebears", "homm3_bulwark_city", "Build_Spring_of_Life", defence: 20),
	};

	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedApplications;
	private static int _loggedSkips;

	internal sealed class StatSnapshot
	{
		internal HeroStat Stat;
		internal int Offence, Defence, SpellPower, Intelligence, Moral, Luck;
	}

	internal sealed class InitState
	{
		internal readonly List<StatSnapshot> Stats = new();
		internal TransferHero Hero;
		internal bool ManaChanged;
		internal int Mana, ManaMax;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var initMethod = ResolveBattleLogicInit("homm3.townSiegeDefense");
			var prefix = typeof(Homm3TownSiegeDefenseRuntime).GetMethod(nameof(PrefixBattleLogicInit), BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			var finalizer = typeof(Homm3TownSiegeDefenseRuntime).GetMethod(nameof(FinalizerBattleLogicInit), BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(initMethod, prefix, out var reason))
				throw new MissingMethodException("prefix incompatible: " + reason);
			if (!GameMember.IsHarmonyPatchCompatible(initMethod, finalizer, out reason))
				throw new MissingMethodException("finalizer incompatible: " + reason);
			harmony.Patch(
				initMethod,
				prefix: new HarmonyMethod(prefix) { priority = Priority.High },
				finalizer: new HarmonyMethod(finalizer) { priority = Priority.Low });
			_registered = true;
			_log?.LogInfo("HoMM3 town siege defense runtime registered on " + initMethod.DeclaringType?.FullName + "." + initMethod.Name + " (" + Entries.Length + " buildings; battle-only, restored after Init).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 town siege defense runtime not registered: " + ex.Message);
		}
	}

	/// <summary>Shared with the Escape Tunnel runtime: the exact BattleLogic.Init(int, TransferBattle, bool, bool).</summary>
	internal static MethodInfo ResolveBattleLogicInit(string symbolId)
	{
		var hexAssembly = typeof(TransferBattle).Assembly;
		Type battleLogicType = null;
		foreach (var hint in GameSymbols.DraconicDominion.BattleLogicTypeHints ?? Array.Empty<string>())
		{
			battleLogicType = string.IsNullOrWhiteSpace(hint) ? null : hexAssembly.GetType(hint);
			if (battleLogicType != null)
				break;
		}
		if (battleLogicType == null)
			throw new MissingMemberException(symbolId + " battle logic type not found from DraconicDominion.BattleLogicTypeHints");
		var transferBattleType = hexAssembly.GetType(GameSymbols.DraconicDominion.TransferBattleTypeName) ?? typeof(TransferBattle);
		var name = GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0];
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in battleLogicType.GetMethods(flags))
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void))
				continue;
			var p = method.GetParameters();
			if (p.Length == 4 && p[0].ParameterType == typeof(int) && p[1].ParameterType == transferBattleType
			    && p[2].ParameterType == typeof(bool) && p[3].ParameterType == typeof(bool))
				return method;
		}
		throw new MissingMethodException(symbolId + " BattleLogic.Init(int, TransferBattle, bool, bool) not found on " + battleLogicType.FullName);
	}

	private static void PrefixBattleLogicInit(object __1, ref InitState __state)
	{
		__state = null;
		try
		{
			// Apply publishes the state before its first write, so a throw part-way is still restored below.
			Apply(__1 as TransferBattle, ref __state);
		}
		catch (Exception ex)
		{
			// Undo anything half-applied, then fail closed.
			Restore(__state);
			__state = null;
			LogSkip("apply failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static Exception FinalizerBattleLogicInit(Exception __exception, InitState __state)
	{
		try
		{
			Restore(__state);
		}
		catch (Exception ex)
		{
			LogSkip("restore failed: " + ex.GetBaseException().Message);
		}
		return __exception;
	}

	private static void Apply(TransferBattle transferBattle, ref InitState published)
	{
		if (transferBattle == null || !Homm3TownBuildingReader.IsSiegeBattle(transferBattle))
			return;
		if (!Homm3TownBuildingReader.TryGetSiegeDefender(transferBattle, out var city, out var defenderIndex, out var defender))
		{
			LogSkip("siege without an exactly identified town/defender; no bonus.");
			return;
		}
		if (defender.typeInWorld != TransferSide.EType.Type_Hero || defender.hero == null)
			return; // garrison-only defence: no hero to receive the bonus (as in HoMM3)

		int off = 0, def = 0, sp = 0, know = 0, mor = 0, luck = 0;
		var applied = new List<string>();
		foreach (var entry in Entries)
		{
			if (!Homm3TownBuildingReader.CityMatchesSid(city, entry.CitySid))
				continue;
			if (!Homm3TownBuildingReader.CityHasBuilding(city, entry.BuildingSid, entry.Level))
				continue;
			off += entry.Offence;
			def += entry.Defence;
			sp += entry.SpellPower;
			know += entry.Knowledge;
			mor += entry.Morale;
			luck += entry.Luck;
			applied.Add(entry.Name);
		}
		if (applied.Count == 0)
			return;

		var hero = defender.hero;
		var state = new InitState { Hero = hero };
		HeroStat primary = null;
		foreach (var stat in DistinctStats(hero))
		{
			primary ??= stat;
			state.Stats.Add(new StatSnapshot
			{
				Stat = stat,
				Offence = stat.offence,
				Defence = stat.defence,
				SpellPower = stat.spellPower,
				Intelligence = stat.intelligence,
				Moral = stat.moral,
				Luck = stat.luck,
			});
		}
		if (primary == null)
		{
			LogSkip("defending hero has no HeroStat; no bonus.");
			return;
		}

		published = state;
		// Max mana before the change (native formula), so Knowledge raises the pool by the native amount.
		var manaMaxBefore = know != 0 ? NativeManaMax(primary, primary.intelligence) : 0;
		foreach (var snap in state.Stats)
		{
			var s = snap.Stat;
			s.offence += off;
			s.defence += def;
			s.spellPower += sp;
			s.intelligence += know;
			s.moral += mor;
			s.luck += luck;
		}
		if (know != 0)
		{
			var delta = NativeManaMax(primary, primary.intelligence) - manaMaxBefore;
			if (delta > 0)
			{
				state.Mana = hero.mana;
				state.ManaMax = hero.manaMax;
				state.ManaChanged = true;
				// state.ManaChanged is set before the writes so a throw between them still restores both.
				hero.manaMax += delta;
				// HoMM3 grants the extra spell points with the Knowledge; leftover points stay after the battle
				// (battle end copies current mana back to the world hero), as a Magic Well overfill does.
				hero.mana += delta;
			}
		}

		if (_loggedApplications++ < 16)
			_log?.LogInfo("HoMM3 town siege defense: " + string.Join(", ", applied) + " -> defender side " + defenderIndex
			              + " in city #" + city.idMapObject + " (" + Homm3TownBuildingReader.CityIdentity(city) + "): atk+" + off + " def+" + def
			              + " sp+" + sp + " know+" + know + " morale+" + mor + " luck+" + luck + (state.ManaChanged ? " manaMax+" + (hero.manaMax - state.ManaMax) : "") + ".");
	}

	private static void Restore(InitState state)
	{
		if (state == null)
			return;
		foreach (var snap in state.Stats)
		{
			var s = snap?.Stat;
			if (s == null)
				continue;
			s.offence = snap.Offence;
			s.defence = snap.Defence;
			s.spellPower = snap.SpellPower;
			s.intelligence = snap.Intelligence;
			s.moral = snap.Moral;
			s.luck = snap.Luck;
		}
		if (state.ManaChanged && state.Hero != null)
		{
			state.Hero.manaMax = state.ManaMax;
			state.Hero.mana = state.Mana;
		}
	}

	/// <summary>heroStat and heroStatUnclamped, deduplicated by native pointer (each property read returns a new wrapper).</summary>
	private static IEnumerable<HeroStat> DistinctStats(TransferHero hero)
	{
		var seen = new HashSet<IntPtr>();
		foreach (var stat in new[] { hero.heroStat, hero.heroStatUnclamped })
		{
			if (stat == null)
				continue;
			var ptr = ((Il2CppObjectBase)stat).Pointer;
			if (ptr == IntPtr.Zero || !seen.Add(ptr))
				continue;
			yield return stat;
		}
	}

	/// <summary>Native max mana: RoundToInt((10 + floor(knowledge * (1 + intelligencePer)) * 10 + manaBonus) * (1 + manaBonusPercent)).</summary>
	private static int NativeManaMax(HeroStat stat, int knowledge)
	{
		var k = Math.Floor(knowledge * (1.0 + stat.intelligencePer));
		var raw = (10.0 + k * 10.0 + stat.manaBonus) * (1.0 + stat.manaBonusPercent);
		return (int)Math.Round(raw, MidpointRounding.ToEven);
	}

	private static void LogSkip(string message)
	{
		if (_loggedSkips++ < 16)
			_log?.LogWarning("HoMM3 town siege defense: " + message);
	}
}
