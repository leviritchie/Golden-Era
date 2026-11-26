using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Factory faction laws that change the Logistics Network or battle results (law pass 2026-11-21,
/// docs/faction_law_pass_20261121/factory.md and build_factory.md; reworded in the 2026-11-25 pass,
/// docs/faction_law_pass_20261125/build_factory.md). Network laws are read from the owning player's
/// data side by side index, cached briefly because the network solver and the facade ask often. Salvage Crews is read
/// from the winning battle side (transfer side or its logic hero). Fail closed: no law, or a read failure, gives level 0
/// and the current behaviour.
/// </summary>
internal static class Homm3FactoryLawHooks
{
	internal const string FactionSid = "homm3_factory";
	/// <summary>Telegraph Lines: every mine and dwelling you own can be managed remotely up to enhancement level 1/2,
	/// even one no Factory hero has visited.</summary>
	internal const int TelegraphLines = 5;
	/// <summary>Surveyors' Charter: the base range of the Logistics Network +50%.</summary>
	internal const int SurveyorsCharter = 7;
	/// <summary>Standard Parts: enhancing network buildings costs 15%/30% less.</summary>
	internal const int StandardParts = 12;
	/// <summary>Overclocked Plants: enhanced buildings work 1 level higher (at most Expert).</summary>
	internal const int OverclockedPlants = 21;
	/// <summary>Salvage Crews: after a won battle 20%/40% of fallen Automaton/Dreadnought-line creatures return.</summary>
	internal const int SalvageCrews = 25;
	/// <summary>Insured Plants: enhancements survive capture, dormant until the town is retaken.</summary>
	internal const int InsuredPlants = 32;

	internal static readonly int[] StandardPartsPercentByLevel = { 0, 15, 30 };
	// law pass 2026-11-25: Surveyors' Charter (#7). Must match the law's display carrier (0.50).
	internal static readonly int[] SurveyorsCharterPercentByLevel = { 0, 50 };
	internal static readonly int[] SalvagePercentByLevel = { 0, 20, 40 };

	internal static readonly HashSet<string> ConstructSids = new(StringComparer.Ordinal)
	{
		"h3_automaton", "h3_sentinel_automaton", "h3_automaton_upg_alt",
		"h3_dreadnought", "h3_juggernaut", "h3_dreadnought_upg_alt",
	};

	private const int CacheMs = 1500;
	private static readonly Dictionary<long, (int Tick, int Level)> _cache = new();

	/// <summary>Law level (0 = not taken) for the player at <paramref name="sideIndex"/>.</summary>
	internal static int Level(int sideIndex, int lawIndex)
	{
		if (sideIndex < 0 || sideIndex > 31 || lawIndex <= 0)
			return 0;
		var key = ((long)sideIndex << 32) | (uint)lawIndex;
		var now = Environment.TickCount;
		if (_cache.TryGetValue(key, out var hit) && unchecked(now - hit.Tick) < CacheMs)
			return hit.Level;
		var level = 0;
		try
		{
			if (Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out _) && side != null)
				level = Math.Max(0, Homm3CustomFactionLawRuntime.CustomLawRank(side, lawIndex, FactionSid));
		}
		catch
		{
			level = 0;
		}
		_cache[key] = (now, level);
		return level;
	}

	internal static int Table(int[] table, int level) => table == null || level <= 0 ? 0 : table[Math.Min(level, table.Length - 1)];

	internal static void ClearCache() => _cache.Clear();

	// law pass 2026-11-25: Surveyors' Charter (#7). Range is LogisticsLevel x RangeMpPerLevel, so +50% of the base range
	// is +ceil(base x 50%) levels (base 2 -> +1 level, +0.5 day). Rails and hubs add on top and are not scaled.
	internal static int BaseLogisticsLevel(Homm3FactoryLogisticsConfig config, int sideIndex)
	{
		var baseLevel = config?.BaseLogisticsLevel ?? 0;
		var pct = Table(SurveyorsCharterPercentByLevel, Level(sideIndex, SurveyorsCharter));
		if (pct <= 0 || baseLevel <= 0)
			return baseLevel;
		return baseLevel + Math.Max(1, (baseLevel * pct + 99) / 100);
	}

	// law pass 2026-11-25: Telegraph Lines (#5). Remote management works on unvisited buildings too (the facade builds a
	// fresh object state); only the text changed in this pass.
	internal static int TelegraphLevel(int sideIndex) => Math.Min(2, Level(sideIndex, TelegraphLines));

	// law pass 2026-11-21: Standard Parts (#12)
	internal static int StandardPartsPercent(int sideIndex) => Table(StandardPartsPercentByLevel, Level(sideIndex, StandardParts));

	// law pass 2026-11-21: Overclocked Plants (#21)
	internal static int OverclockLevels(int sideIndex) => Math.Min(1, Level(sideIndex, OverclockedPlants));

	// law pass 2026-11-21: Insured Plants (#32)
	internal static bool InsuredPlantsActive(int sideIndex) => Level(sideIndex, InsuredPlants) > 0;

	// ---------------------------------------------------------------- Salvage Crews (#25)

	private static readonly object Gate = new();
	private static readonly HashSet<int> Resolved = new();
	private static MethodInfo _addSpawnedUnit;
	private static MethodInfo _sortBySlot;
	private static bool _methodsTried;
	private static int _logged;

	/// <summary>
	/// law pass 2026-11-21: Salvage Crews (#25). Called from the shared battle-result prefix before the native result
	/// applies (needs a dispatch line in Homm3RuntimeMechanicHooks; see build_factory.md). For the winning side only:
	/// floor(lost x 20%/40%) of each fallen Automaton/Dreadnought-line stack is put back into its stack in the result
	/// transfer side, so the native result carries it home. Once per battle; fail closed.
	/// </summary>
	internal static void ObserveBeforeBattleResult(object battleLogic)
	{
		if (battleLogic == null)
			return;
		try
		{
			var transfer = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
			var started = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle;
			var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
			if (transfer?.sides == null || started?.sides == null || result == null)
				return;
			var winnerIndex = result.winnerIndex;
			if (winnerIndex < 0 || winnerIndex >= started.sides.Length || winnerIndex >= transfer.sides.Length)
				return;
			var winnerStarted = started.sides[winnerIndex];
			var winnerAfter = transfer.sides[winnerIndex];
			if (winnerStarted == null || winnerAfter == null)
				return;
			var rank = Rank(SalvageCrews, winnerAfter, winnerStarted, winnerAfter.logicHero, winnerStarted.logicHero);
			var percent = Table(SalvagePercentByLevel, rank);
			if (percent <= 0)
				return;
			var key = BattleKey(battleLogic);
			lock (Gate)
			{
				if (!Resolved.Add(key))
					return;
				if (Resolved.Count > 256)
				{
					Resolved.Clear();
					Resolved.Add(key);
				}
			}

			var restored = new List<string>();
			var addedNew = false;
			if (winnerStarted.units == null)
				return;
			foreach (var before in winnerStarted.units)
			{
				if (before == null || before.stacks <= 0)
					continue;
				var sid = before.configSid?.Trim();
				if (sid == null || !ConstructSids.Contains(sid))
					continue;
				TransferUnit after = null;
				if (winnerAfter.units != null)
				{
					foreach (var candidate in winnerAfter.units)
					{
						if (candidate != null && candidate.slotPos == before.slotPos && string.Equals(candidate.configSid?.Trim(), sid, StringComparison.Ordinal))
						{
							after = candidate;
							break;
						}
					}
				}
				var remaining = after == null ? 0 : Math.Max(0, after.stacks);
				var lost = Math.Max(0, before.stacks - remaining);
				var back = lost * percent / 100;
				if (back <= 0)
					continue;
				if (after != null)
				{
					after.stacks = remaining + back;
				}
				else
				{
					if (!EnsureMethods())
						continue;
					_addSpawnedUnit.Invoke(winnerAfter, new object[] { new TransferUnit(sid, back, 0), true });
					addedNew = true;
				}
				restored.Add(sid + " +" + back + "/" + lost);
			}
			if (addedNew && EnsureMethods())
				_sortBySlot.Invoke(winnerAfter, Array.Empty<object>());
			if (restored.Count > 0 && _logged++ < 40)
				Plugin.LogSource?.LogInfo("[HoMM3 Factory laws] Salvage Crews L" + rank + " (" + percent + "%) battle " + key + ": " + string.Join(", ", restored));
		}
		catch (Exception ex)
		{
			if (_logged++ < 40)
				Plugin.LogSource?.LogWarning("[HoMM3 Factory laws] Salvage Crews failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static int Rank(int lawIndex, params object[] owners)
	{
		foreach (var owner in owners)
		{
			if (owner == null)
				continue;
			try
			{
				var rank = Homm3CustomFactionLawRuntime.CustomLawRank(owner, lawIndex, FactionSid);
				if (rank > 0)
					return rank;
			}
			catch
			{
				// fail closed: try the next owner
			}
		}
		return 0;
	}

	private static bool EnsureMethods()
	{
		if (_addSpawnedUnit != null && _sortBySlot != null)
			return true;
		if (_methodsTried)
			return false;
		_methodsTried = true;
		_addSpawnedUnit = FindMethod(GameSymbols.SkeletalNecromancy.TransferSideAddSpawnedUnit, new[] { typeof(TransferUnit), typeof(bool) });
		_sortBySlot = FindMethod(GameSymbols.SkeletalNecromancy.TransferSideSortBySlot, Type.EmptyTypes);
		if (_addSpawnedUnit == null || _sortBySlot == null)
			Plugin.LogSource?.LogWarning("[HoMM3 Factory laws] TransferSide add/sort not found; Salvage Crews only refills surviving stacks.");
		return _addSpawnedUnit != null && _sortBySlot != null;
	}

	private static MethodInfo FindMethod(GameSymbols.MethodSymbol symbol, Type[] parameterTypes)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in typeof(TransferSide).GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameters.Length && exact; i++)
					exact = parameters[i].ParameterType == parameterTypes[i];
				if (exact)
					return method;
			}
		}
		return null;
	}

	private static int BattleKey(object battleLogic)
	{
		if (ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicIdFields) is int id && id != 0)
			return id;
		if (battleLogic is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
		{
			var ptr = il2Cpp.Pointer.ToInt64();
			return unchecked((int)(ptr ^ (ptr >> 32)));
		}
		return battleLogic.GetHashCode();
	}

	private static object ReadMember(object obj, params string[] names)
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
					return property.GetValue(obj);
				var field = cur.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
		}
		return null;
	}
}
