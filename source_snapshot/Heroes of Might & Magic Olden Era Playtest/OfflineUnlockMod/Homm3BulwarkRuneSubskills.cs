using System;
using System.Collections.Generic;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Bulwark Runes subskills (2026-11-25).
/// Advanced: Rune Ward (-4% Magic Damage per Rune Level, one hidden buff per level), Clan March (+1 Rune Level at
/// round start to a stack that changed hex during the previous round).
/// Expert: Frost Tempo (reaching Rune Level 3/6/9/12 chills the nearest enemy), Elder Mark (one stack per hero gains
/// double Rune Levels), Stone Circle (Defend shields adjacent friendly stacks until the end of the round).
/// Clan March, Frost Tempo, Elder Mark and Stone Circle read the grid through <see cref="Homm3BulwarkLawHooks"/>.
/// Fail closed: anything unreadable does nothing.
/// </summary>
internal static class Homm3BulwarkRuneSubskills
{
	internal const string RuneWard = "sub_skill_faction_homm3_bulwark_rune_ward";
	internal const string ClanMarch = "sub_skill_faction_homm3_bulwark_clan_march";
	internal const string FrostTempo = "sub_skill_faction_homm3_bulwark_frost_tempo";
	internal const string ElderMark = "sub_skill_faction_homm3_bulwark_elder_mark";
	internal const string StoneCircle = "sub_skill_faction_homm3_bulwark_stone_circle";

	internal const string RuneWardBuffPrefix = "homm3_bulwark_rune_ward_";
	internal const string ElderMarkBuff = "homm3_bulwark_elder_mark";
	internal const string FrostChillBuff = "homm3_bulwark_frost_tempo_chill";
	internal const string StoneCircleBuff = "homm3_bulwark_stone_circle";

	internal const int ClanMarchGain = 1;
	internal const int ElderMarkFactor = 2;
	private const int FrostChillRounds = 2;
	private const int StoneCircleRounds = 1;

	internal static bool Has(object logicHero, string sid)
	{
		var dataHero = Homm3BulwarkRunesRuntime.ResolveDataHero(logicHero);
		return dataHero != null
		       && (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, sid)
		           || Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, "arena_" + sid));
	}

	internal static bool IsFrostThreshold(int threshold) => threshold > 0 && threshold % 3 == 0;

	/// <summary>Rune Ward: one stacking hidden buff for each newly reached Rune Level.</summary>
	internal static void ApplyRuneWard(object unit, IReadOnlyList<int> crossed)
	{
		foreach (var level in crossed)
		{
			if (!TryAdd(unit, RuneWardBuffPrefix + level, unit, 99, out var fail))
				Homm3BulwarkRunesRuntime.LogLimited("Rune Ward level " + level + " failed: " + fail);
		}
	}

	/// <summary>Frost Tempo: the nearest enemy loses Initiative and Speed. Several levels at once refresh one chill.</summary>
	internal static void ApplyFrostTempo(object unit)
	{
		var enemy = Homm3BulwarkLawHooks.NearestEnemy(unit);
		if (enemy == null)
			return;
		if (TryAdd(enemy, FrostChillBuff, unit, FrostChillRounds, out var fail))
			Homm3BulwarkRunesRuntime.LogLimited("Frost Tempo chilled " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(enemy) + ".");
		else
			Homm3BulwarkRunesRuntime.LogLimited("Frost Tempo failed: " + fail);
	}

	/// <summary>Stone Circle: a Defending stack shields every adjacent friendly stack until the end of the round.</summary>
	internal static void OnDefend(object unit)
	{
		try
		{
			if (!Homm3BulwarkRunesRuntime.TryResolveSubskillOwner(unit, out var wrapped, out _, out _, out var logicHero)
			    || !Has(logicHero, StoneCircle))
				return;
			var shielded = 0;
			foreach (var ally in Homm3BulwarkLawHooks.AdjacentFriendlyUnits(wrapped))
			{
				if (Homm3BulwarkRunesRuntime.IsWarMachineExcluded(Homm3BulwarkRunesRuntime.TryResolveBattleUnitSid(ally)))
					continue;
				if (TryAdd(ally, StoneCircleBuff, wrapped, StoneCircleRounds, out var fail))
					shielded++;
				else
					Homm3BulwarkRunesRuntime.LogLimited("Stone Circle failed: " + fail);
			}
			if (shielded > 0)
				Homm3BulwarkRunesRuntime.LogLimited("Stone Circle shielded " + shielded + " stack(s).");
		}
		catch (Exception ex)
		{
			Homm3BulwarkRunesRuntime.LogLimited("Stone Circle failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Elder Mark: at the first round, each hero with the subskill marks their highest-tier stack (lowest army slot on a
	/// tie). Runs before the round-one Rune grants so those are doubled too.
	/// </summary>
	internal static void GrantElderMarks(IEnumerable<Unit> units)
	{
		try
		{
			var best = new Dictionary<IntPtr, (Unit Unit, long Key, int Tier, int Slot)>();
			var heroHasMark = new Dictionary<IntPtr, bool>();
			foreach (var unit in units)
			{
				if (!Homm3BulwarkRunesRuntime.TryResolveSubskillOwner(unit, out var wrapped, out var key, out var sid, out var logicHero)
				    || logicHero is not Il2CppObjectBase hero)
					continue;
				if (!heroHasMark.TryGetValue(hero.Pointer, out var has))
					heroHasMark[hero.Pointer] = has = Has(logicHero, ElderMark);
				if (!has)
					continue;
				var tier = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid)?.tier ?? 0;
				var slot = Homm3BulwarkRunesRuntime.TryResolveArmySlot(wrapped);
				if (!best.TryGetValue(hero.Pointer, out var current)
				    || tier > current.Tier
				    || (tier == current.Tier && slot < current.Slot))
					best[hero.Pointer] = (unit, key, tier, slot);
			}
			foreach (var pick in best.Values)
			{
				Homm3BulwarkRunesRuntime.MarkElder(pick.Key);
				if (TryAdd(pick.Unit, ElderMarkBuff, pick.Unit, 99, out var fail))
					Homm3BulwarkRunesRuntime.LogLimited("Elder Mark on " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(pick.Unit)
					                                    + " (tier " + pick.Tier + ", slot " + pick.Slot + ").");
				else
					Homm3BulwarkRunesRuntime.LogLimited("Elder Mark icon failed (the Rune bonus still applies): " + fail);
			}
		}
		catch (Exception ex)
		{
			Homm3BulwarkRunesRuntime.LogLimited("Elder Mark failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static bool TryAdd(object receiver, string sid, object caster, int duration, out string failReason)
		=> Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(receiver, sid, caster, 1, duration, 0, true, out _, out failReason);
}
