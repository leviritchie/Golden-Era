using System;
using System.Collections.Generic;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (docs/building_pass_20261122/bulwark.md §1, REVIEW §2): Altar of the Runes, with the
/// Sieidi of the Runes folded in, on the <c>Build_Mycelium_Roots</c> row of <c>homm3_bulwark_city</c> (no native effect).
///
/// At round 1 of every battle, each stack the Runes skill already covers (its owner hero has the Bulwark faction
/// skill; see <see cref="Homm3BulwarkRunesRuntime"/>) gains one Rune Level per owned Bulwark town with the Altar.
/// Rides the round-1 hook in <see cref="Homm3BulwarkLawHooks"/> after Runes Carved in Advance, so it needs no
/// registration of its own and is live exactly when that hook is. Once per stack per battle (the Runes stack state is
/// cleared per battle). Fail closed: an unreadable owner or town list grants nothing.
/// </summary>
internal static class Homm3BulwarkAltarRunesRuntime
{
	internal const string BuildingSid = "Build_Mycelium_Roots";
	internal const string CitySid = "homm3_bulwark_city";

	/// <summary>Called once per battle at round 1 with the battle's deduplicated stacks. Returns the stacks granted.</summary>
	internal static int GrantRoundOne(List<Unit> units)
	{
		if (units == null || units.Count == 0)
			return 0;
		var altarsByHero = new Dictionary<IntPtr, int>();
		int AltarLevels(object logicHero)
		{
			if (logicHero is not Il2CppObjectBase hero || hero.Pointer == IntPtr.Zero)
				return 0;
			if (!altarsByHero.TryGetValue(hero.Pointer, out var count))
				altarsByHero[hero.Pointer] = count = Math.Max(0, Homm3TownBuildingReader.SideBuildingCount(logicHero, BuildingSid, CitySid));
			return count;
		}
		var granted = 0;
		foreach (var unit in units)
		{
			if (Homm3BulwarkRunesRuntime.ApplyAltarOfRunes(unit, AltarLevels))
				granted++;
		}
		return granted;
	}
}
