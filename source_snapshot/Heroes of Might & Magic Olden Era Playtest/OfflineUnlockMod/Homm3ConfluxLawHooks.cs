using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Conflux faction laws with battle-result levers (law pass 2026-11-25, docs/faction_law_pass_20261125/build_conflux.md).
/// The fusion laws that change a cast (Perfect Conjunction #28) stay in <see cref="Homm3ConfluxFusionRuntime.ApplyFusionLaws"/>.
/// Fail closed: no law, or a read failure, gives level 0 and the current behaviour.
/// </summary>
internal static class Homm3ConfluxLawHooks
{
	internal const string FactionSid = "homm3_conflux";
	/// <summary>Reforming Elements (was Unequal Union): after a won battle, fused elementals restore 15%/30% of the creatures they lost.</summary>
	internal const int ReformingElements = 9;
	/// <summary>law pass 2026-11-25: Reforming Elements (#9). Must match the display carrier in homm3_conflux.json (0.15/0.30).</summary>
	internal static readonly int[] ReformingPercentByLevel = { 0, 15, 30 };
	/// <summary>Stage-1 fusions are h3_fusion_&lt;host&gt;_&lt;guest&gt;, stage-2 h3_fusion_ii_* (custom_factions/conflux_fusion).</summary>
	internal const string FusedSidPrefix = "h3_fusion_";

	private static readonly object Gate = new();
	private static readonly HashSet<int> Resolved = new();
	private static MethodInfo _addSpawnedUnit;
	private static MethodInfo _sortBySlot;
	private static bool _methodsTried;
	private static int _logged;

	internal static bool IsFusedSid(string sid) => sid != null && sid.StartsWith(FusedSidPrefix, StringComparison.Ordinal);

	/// <summary>
	/// law pass 2026-11-25: Reforming Elements (#9). Called before the native battle result applies (dispatched from
	/// the shared battle-result prefix, Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup). For the winning side
	/// only: floor(lost x 15%/30%) of each fused stack's fallen creatures is put back into its stack in the result transfer
	/// side, so the native result carries it home (the Factory Salvage Crews pattern). Once per battle; fail closed.
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
			if (winnerStarted?.units == null || winnerAfter == null)
				return;
			var rank = Rank(ReformingElements, winnerAfter, winnerStarted, winnerAfter.logicHero, winnerStarted.logicHero);
			var percent = rank <= 0 ? 0 : ReformingPercentByLevel[Math.Min(rank, ReformingPercentByLevel.Length - 1)];
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
			foreach (var before in winnerStarted.units)
			{
				if (before == null || before.stacks <= 0)
					continue;
				var sid = before.configSid?.Trim();
				if (!IsFusedSid(sid))
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
				Plugin.LogSource?.LogInfo("[HoMM3 Conflux laws] Reforming Elements L" + rank + " (" + percent + "%) battle " + key + ": " + string.Join(", ", restored));
		}
		catch (Exception ex)
		{
			if (_logged++ < 40)
				Plugin.LogSource?.LogWarning("[HoMM3 Conflux laws] Reforming Elements failed closed: " + ex.GetBaseException().Message);
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
			Plugin.LogSource?.LogWarning("[HoMM3 Conflux laws] TransferSide add/sort not found; Reforming Elements only refills surviving stacks.");
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
