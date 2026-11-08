using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Battle.BattleLog;

namespace OfflineUnlockMod;

/// <summary>
/// Loads battle bundles, prefab templates, array manifests, and HOMM3_* audio indexes for the
/// current fight roster at <see cref="BhBattleLog.Start"/> so first unit spawn / clip change does not pay cold-load cost.
/// </summary>
internal static class Homm3BattleRosterPrewarm
{
	static bool _patched;
	static int _lastPrewarmedBattleId = int.MinValue;
	static ManualLogSource _log;

	internal static void Ensure(Harmony harmony, ManualLogSource log)
	{
		if (_patched || harmony == null)
			return;
		_log = log;
		var start = AccessTools.Method(typeof(BhBattleLog), "Start", Type.EmptyTypes);
		if (start == null)
		{
			log?.LogWarning("Homm3BattleRosterPrewarm: BhBattleLog.Start not found; roster prewarm disabled.");
			return;
		}

		harmony.Patch(start, postfix: new HarmonyMethod(typeof(Homm3BattleRosterPrewarm), nameof(PostfixBattleLogStart)));
		var exit = AccessTools.Method(typeof(BhBattleEnd), nameof(BhBattleEnd.OnBtnExit), Type.EmptyTypes);
		if (exit != null)
			harmony.Patch(exit, prefix: new HarmonyMethod(typeof(Homm3BattleRosterPrewarm), nameof(PrefixBattleEndExit)));
		_patched = true;
		log?.LogInfo("Homm3BattleRosterPrewarm: patched BhBattleLog.Start for roster asset prewarm.");
	}

	static void PrefixBattleEndExit()
	{
		_lastPrewarmedBattleId = int.MinValue;
	}

	static void PostfixBattleLogStart()
	{
		try
		{
			PrewarmCurrentBattleRoster();
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Homm3BattleRosterPrewarm: prewarm failed: " + ex.Message);
		}
	}

	internal static void PrewarmCurrentBattleRoster()
	{
		if (!TryGetCurrentBattleId(out var battleId))
			battleId = 0;
		if (battleId != 0 && battleId == _lastPrewarmedBattleId)
			return;

		var sids = CollectRosterConfigSids();
		if (sids.Count == 0)
			return;

		var sw = Stopwatch.StartNew();
		var bundles = new HashSet<string>(StringComparer.Ordinal);
		var entries = 0;
		var manifests = 0;
		var actionBars = Homm3ImportBhSelectedUnitHudFix.PrewarmReleaseActionBarsForSids(sids, _log);
		foreach (var sid in sids)
		{
			if (!Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(sid, _log, out var entry)
			    || entry == null)
				continue;
			entries++;
			Homm3ImportVisuals.PrewarmBattleEntryAssets(entry, _log);
			if (!string.IsNullOrEmpty(entry.BundleName))
				bundles.Add(entry.BundleName);
			var labSid = Homm3ImportVisuals.TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
			if (!string.IsNullOrEmpty(labSid) && Homm3BattleArrayBillboard.IsArrayPrototypeLabSid(labSid))
				manifests++;
		}

		if (battleId != 0)
			_lastPrewarmedBattleId = battleId;
		sw.Stop();
		if (entries > 0)
		{
			_log?.LogInfo(
				"Homm3BattleRosterPrewarm: prewarmed "
				+ entries
				+ " import entr(y/ies), "
				+ bundles.Count
				+ " bundle(s), "
				+ manifests
				+ " array manifest(s) from "
				+ sids.Count
				+ " roster unit(s), "
				+ actionBars.ActionBars
				+ " action-bar config(s), "
				+ actionBars.Icons
				+ " action-bar icon(s), "
				+ actionBars.IconMisses
				+ " icon miss(es) in "
				+ sw.ElapsedMilliseconds
				+ " ms (battleId="
				+ battleId
				+ ").");
		}
	}

	static bool TryGetCurrentBattleId(out int battleId)
	{
		battleId = 0;
		var controllerType = ResolveBattleControllerType();
		if (controllerType == null)
			return false;
		try
		{
			var field = controllerType.GetField(
				"lastBattleId",
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
			if (field != null && field.FieldType == typeof(int))
			{
				battleId = (int)field.GetValue(null);
				return true;
			}
		}
		catch
		{
		}

		return false;
	}

	static HashSet<string> CollectRosterConfigSids()
	{
		var sids = new HashSet<string>(StringComparer.Ordinal);
		foreach (var transferBattle in EnumerateCurrentTransferBattles())
			CollectSidsFromTransferBattle(transferBattle, sids);
		return sids;
	}

	static IEnumerable<TransferBattle> EnumerateCurrentTransferBattles()
	{
		var controllerType = ResolveBattleControllerType();
		if (controllerType == null)
			yield break;
		var controller = ReadStaticMember(controllerType, GameSymbols.BattleVisual.BattleControllerSingletonMembers);
		if (controller == null)
			yield break;
		var battleLogic = ReadMember(controller, GameSymbols.BattleVisual.BattleLogicOnControllerMembers);
		if (battleLogic == null)
			yield break;
		var seen = new HashSet<object>();
		foreach (var name in GameSymbols.BattleVisual.BattleLogicTransferBattleMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var transfer = ReadMember(battleLogic, name);
			if (transfer == null || !seen.Add(transfer))
				continue;
			if (transfer is TransferBattle tb)
				yield return tb;
		}
	}

	static void CollectSidsFromTransferBattle(TransferBattle transferBattle, HashSet<string> sids)
	{
		if (transferBattle?.sides == null)
			return;
		for (var si = 0; si < transferBattle.sides.Length; si++)
		{
			var side = transferBattle.sides[si];
			if (side?.units == null)
				continue;
			for (var ui = 0; ui < side.units.Length; ui++)
			{
				var unit = side.units[ui];
				if (unit == null)
					continue;
				var sid = unit.configSid;
				if (!string.IsNullOrWhiteSpace(sid))
					sids.Add(sid.Trim());
			}
		}
	}

	static Type ResolveBattleControllerType()
	{
		var asm = typeof(TransferSide).Assembly;
		foreach (var name in GameSymbols.BattleVisual.BattleControllerTypeNames)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null)
				return type;
		}

		return null;
	}

	static object ReadMember(object owner, params string[] names)
	{
		if (owner == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var prop = type.GetProperty(name, flags);
					if (prop != null && prop.GetIndexParameters().Length == 0)
						return prop.GetValue(owner, null);
				}
				catch
				{
				}

				try
				{
					var field = type.GetField(name, flags);
					if (field != null)
						return field.GetValue(owner);
				}
				catch
				{
				}
			}
		}

		return null;
	}

	static object ReadStaticMember(Type type, params string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(null, null);
			}
			catch
			{
			}

			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(null);
			}
			catch
			{
			}
		}

		return null;
	}
}
