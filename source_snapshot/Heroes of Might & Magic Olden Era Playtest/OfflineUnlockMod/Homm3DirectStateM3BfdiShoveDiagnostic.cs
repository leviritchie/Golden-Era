using System;
using System.Globalization;
using System.Text;

namespace OfflineUnlockMod;

/// <summary>
/// M3 focused live-positive shove diagnostic. Explicit flag-only path that reaches
/// <see cref="Homm3DirectStateAdapters.TryMove"/> → journaled <c>UnitData.bfdi</c>
/// with CapLog dual-readback (helper hex + <c>Hex.fieldObjects</c>).
/// Teleport stays gated. Production MovementPush ungates only after a proof ledger
/// record cites CapLog agree (see validate_banned_surfaces).
/// </summary>
internal static class Homm3DirectStateM3BfdiShoveDiagnostic
{
	internal const string DiagnosticFlag = "homm3_direct_state_m3_bfdi_shove.flag";
	internal const string CapLogPrefix = "HoMM3 M3_BFDI_DUAL_READBACK";

	/// <summary>
	/// Set true only after focused live-positive CapLog dual-readback agree is recorded.
	/// Keeps validators and gameplay gate synchronized.
	/// Proven 2026-07-20: neighbour_relocate via journaled UnitData.bfdi /
	/// Method_Public_set_Void_Hex_0 with helper hex + fieldObjects CapLog agree
	/// (proof_ledger/entries/ds_m3_movement_push_live_positive.json).
	/// </summary>
	internal const bool MovementPushLivePositiveProven = true;

	internal static bool IsDiagnosticPilotEnabled =>
		Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag);

	internal static bool IsMovementPushAllowed()
	{
		return MovementPushLivePositiveProven || IsDiagnosticPilotEnabled;
	}

	internal static string DescribeGateState()
	{
		if (MovementPushLivePositiveProven)
			return "ungated_live_positive_proven";
		if (IsDiagnosticPilotEnabled)
			return "diagnostic_pilot_flag";
		return "gated";
	}

	/// <summary>
	/// Find two adjacent registered battle units and shove the second away from the first
	/// through the production MovementPush adapter path. If no adjacent pair exists (common
	/// on adventure-map pools), fall back to relocating one live hexed unit onto an empty
	/// neighbour via journaled <see cref="NativeCombatWriteGateway.TryCommitUnitHexMove"/>.
	/// </summary>
	internal static bool TryRunAdjacentUnitShove(
		out string resultJson,
		out string failReason)
	{
		resultJson = null;
		failReason = null;
		if (!IsMovementPushAllowed())
		{
			failReason =
				"MovementPush still gated; enable "
				+ DiagnosticFlag
				+ " for M3 diagnostic or set MovementPushLivePositiveProven after CapLog agree";
			return false;
		}

		if (!NativeCombatWriteGateway.TryPrepareAdapter(
			    Homm3DirectStateAdapterId.Movement,
			    out failReason))
			return false;

		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(128);
		if (units == null || units.Count < 1)
		{
			failReason =
				"need registered battle units for shove (count="
				+ (units?.Count ?? 0)
				+ "); enter combat first";
			return false;
		}

		if (units.Count >= 2
		    && TryRunAdjacentPairShove(units, out resultJson, out failReason))
			return true;

		var pairFailure = failReason;
		if (TryRunSingleUnitNeighbourRelocate(units, out resultJson, out failReason))
			return true;

		failReason =
			"adjacent pair failed ("
			+ (pairFailure ?? "none")
			+ "); neighbour relocate failed ("
			+ (failReason ?? "none")
			+ ")";
		return false;
	}

	private static bool TryRunAdjacentPairShove(
		System.Collections.Generic.List<Homm3BattleUnitLawOwnerRegistry.BattleUnitSnapshot> units,
		out string resultJson,
		out string failReason)
	{
		resultJson = null;
		failReason = null;
		for (var i = 0; i < units.Count; i++)
		{
			var source = units[i].Unit;
			if (source == null)
				continue;
			if (!TryReadUnitHex(source, out var sourceHex)
			    || sourceHex == null
			    || !TryReadHexCoords(sourceHex, out var sx, out var sz))
				continue;

			for (var j = 0; j < units.Count; j++)
			{
				if (i == j)
					continue;
				var target = units[j].Unit;
				if (target == null)
					continue;
				if (!TryReadUnitHex(target, out var targetHex)
				    || targetHex == null
				    || !TryReadHexCoords(targetHex, out var tx, out var tz))
					continue;
				if (HexDistance(sx, sz, tx, tz) != 1)
					continue;

				var beforeSourceMembership = TryFieldObjectsContains(targetHex, target);
				var beforeDestMembership = false;
				var destX = tx + (tx - sx);
				var destZ = tz + (tz - sz);
				if (Homm3DirectStateHexNeighbourNative.TryReadNeighbourSlots(
					    targetHex,
					    out var neighbours,
					    out _)
				    && neighbours != null)
				{
					for (var n = 0; n < neighbours.Length; n++)
					{
						var candidate = neighbours[n];
						if (candidate == null)
							continue;
						if (!TryReadHexCoords(candidate, out var nx, out var nz)
						    || nx != destX
						    || nz != destZ)
							continue;
						beforeDestMembership = TryFieldObjectsContains(candidate, target);
						break;
					}
				}

				var beforeHelperIndex = TryHexIndex(targetHex);
				var beforeHelperCoords = "(" + tx + "," + tz + ")";
				var scope = TryReadBattleLogic(target) ?? TryReadBattleLogic(source) ?? target;

				Plugin.LogSource?.LogInfo(
					CapLogPrefix
					+ " attempt scenario=adjacent_unit_shove"
					+ " sourceKey=" + units[i].UnitKey
					+ " targetKey=" + units[j].UnitKey
					+ " beforeHelper=" + beforeHelperCoords
					+ " beforeHelperIndex=" + beforeHelperIndex
					+ " beforeSourceFieldObjects=" + beforeSourceMembership
					+ " beforeDestFieldObjects=" + beforeDestMembership
					+ " expectedDestCoords=(" + destX + "," + destZ + ")"
					+ ".");

				if (!Homm3DirectStateAdapters.TryMove(
					    scope,
					    source,
					    target,
					    Homm3DirectStateOperation.MovementPush,
					    null,
					    out var destination,
					    out failReason))
				{
					Plugin.LogSource?.LogWarning(
						CapLogPrefix
						+ " reject scenario=adjacent_unit_shove reason="
						+ (failReason ?? "null"));
					return false;
				}

				return FinishDualReadback(
					"adjacent_unit_shove",
					units[i].UnitKey,
					units[j].UnitKey,
					target,
					targetHex,
					destination,
					beforeHelperCoords,
					beforeHelperIndex,
					beforeSourceMembership,
					beforeDestMembership,
					out resultJson,
					out failReason);
			}
		}

		failReason = "no adjacent registered battle unit pair found for shove";
		return false;
	}

	private static bool TryRunSingleUnitNeighbourRelocate(
		System.Collections.Generic.List<Homm3BattleUnitLawOwnerRegistry.BattleUnitSnapshot> units,
		out string resultJson,
		out string failReason)
	{
		resultJson = null;
		failReason = null;
		var inspected = 0;
		var withHex = 0;
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i].Unit;
			if (unit == null)
				continue;
			inspected++;
			if (!TryReadUnitHex(unit, out var sourceHex)
			    || sourceHex == null
			    || !TryReadHexCoords(sourceHex, out var sx, out var sz))
				continue;
			withHex++;
			if (!Homm3DirectStateHexNeighbourNative.TryReadNeighbourSlots(
				    sourceHex,
				    out var neighbours,
				    out var neighbourFailure)
			    || neighbours == null)
			{
				failReason = neighbourFailure ?? "neighbour slots unavailable";
				continue;
			}

			object destHex = null;
			for (var n = 0; n < neighbours.Length; n++)
			{
				var candidate = neighbours[n];
				if (candidate == null)
					continue;
				if (!TryReadHexCoords(candidate, out var nx, out var nz))
					continue;
				if (nx == sx && nz == sz)
					continue;
				// Prefer hexes that do not already list this unit.
				if (TryFieldObjectsContains(candidate, unit))
					continue;
				destHex = candidate;
				break;
			}
			if (destHex == null)
				continue;

			var beforeSourceMembership = TryFieldObjectsContains(sourceHex, unit);
			var beforeDestMembership = TryFieldObjectsContains(destHex, unit);
			var beforeHelperIndex = TryHexIndex(sourceHex);
			var beforeHelperCoords = "(" + sx + "," + sz + ")";
			var scope = TryReadBattleLogic(unit) ?? unit;

			Plugin.LogSource?.LogInfo(
				CapLogPrefix
				+ " attempt scenario=neighbour_relocate"
				+ " unitKey=" + units[i].UnitKey
				+ " beforeHelper=" + beforeHelperCoords
				+ " beforeHelperIndex=" + beforeHelperIndex
				+ " beforeSourceFieldObjects=" + beforeSourceMembership
				+ " beforeDestFieldObjects=" + beforeDestMembership
				+ ".");

			if (!BattleCombatTransactionManager.TryBegin(
				    scope,
				    Homm3DirectStateAdapterId.Movement,
				    Homm3DirectStateOperation.MovementPush,
				    reserveJournal: 2,
				    reserveRootWork: 1,
				    out var transaction,
				    out failReason))
				return false;
			using (transaction)
			{
				if (!NativeCombatWriteGateway.TryCommitUnitHexMove(
					    unit,
					    destHex,
					    transaction,
					    out _,
					    out failReason))
				{
					Plugin.LogSource?.LogWarning(
						CapLogPrefix
						+ " reject scenario=neighbour_relocate reason="
						+ (failReason ?? "null"));
					return false;
				}
				if (!transaction.Commit(out failReason))
					return false;
			}

			return FinishDualReadback(
				"neighbour_relocate",
				units[i].UnitKey,
				units[i].UnitKey,
				unit,
				sourceHex,
				destHex,
				beforeHelperCoords,
				beforeHelperIndex,
				beforeSourceMembership,
				beforeDestMembership,
				out resultJson,
				out failReason);
		}

		failReason =
			"no relocatable unit with hex+neighbour (inspected="
			+ inspected
			+ " withHex="
			+ withHex
			+ ")";
		return false;
	}

	private static bool FinishDualReadback(
		string scenario,
		long sourceKey,
		long targetKey,
		object target,
		object oldHex,
		object destination,
		string beforeHelperCoords,
		string beforeHelperIndex,
		bool beforeSourceMembership,
		bool beforeDestMembership,
		out string resultJson,
		out string failReason)
	{
		resultJson = null;
		if (!TryReadUnitHex(target, out var afterHex) || afterHex == null)
		{
			failReason = "post-shove helper hex unavailable";
			Plugin.LogSource?.LogWarning(CapLogPrefix + " reject " + failReason);
			return false;
		}

		var afterHelperIndex = TryHexIndex(afterHex);
		TryReadHexCoords(afterHex, out var ax, out var az);
		var afterDestMembership = TryFieldObjectsContains(afterHex, target);
		var afterSourceMembership = TryFieldObjectsContains(oldHex, target);
		var helperAgree = NativeCombatWriteGateway.NativeHexIdentityEqualsPublic(afterHex, destination)
		                  || (destination != null
		                      && TryReadHexCoords(destination, out var dx, out var dz)
		                      && ax == dx
		                      && az == dz);
		var dualAgree = helperAgree && afterDestMembership && !afterSourceMembership;

		var capLine =
			CapLogPrefix
			+ (dualAgree ? " agree" : " disagree")
			+ " scenario=" + scenario
			+ " beforeHelper=" + beforeHelperCoords
			+ " beforeHelperIndex=" + beforeHelperIndex
			+ " afterHelper=(" + ax + "," + az + ")"
			+ " afterHelperIndex=" + afterHelperIndex
			+ " destIndex=" + TryHexIndex(destination)
			+ " helperAgree=" + helperAgree
			+ " fieldObjectsDest=" + afterDestMembership
			+ " fieldObjectsSourceCleared=" + (!afterSourceMembership)
			+ " dualAgree=" + dualAgree
			+ ".";
		if (dualAgree)
			Plugin.LogSource?.LogInfo(capLine);
		else
			Plugin.LogSource?.LogWarning(capLine);

		resultJson = BuildResultJson(
			dualAgree,
			sourceKey,
			targetKey,
			beforeHelperCoords,
			beforeHelperIndex,
			"(" + ax + "," + az + ")",
			afterHelperIndex,
			beforeSourceMembership,
			beforeDestMembership,
			afterSourceMembership,
			afterDestMembership,
			helperAgree,
			dualAgree,
			null);
		// Patch scenario into JSON
		resultJson = resultJson.Replace("\"scenario\":\"adjacent_unit_shove\"", "\"scenario\":\"" + scenario + "\"");
		if (!dualAgree)
		{
			failReason = "dual readback disagree after bfdi commit";
			return false;
		}

		failReason = null;
		return true;
	}

	private static string BuildResultJson(
		bool ok,
		long sourceKey,
		long targetKey,
		string beforeHelper,
		string beforeHelperIndex,
		string afterHelper,
		string afterHelperIndex,
		bool beforeSourceMembership,
		bool beforeDestMembership,
		bool afterSourceMembership,
		bool afterDestMembership,
		bool helperAgree,
		bool dualAgree,
		string failure)
	{
		var sb = new StringBuilder(512);
		sb.Append('{');
		sb.Append("\"ok\":").Append(ok ? "true" : "false").Append(',');
		sb.Append("\"scenario\":\"adjacent_unit_shove\",");
		sb.Append("\"gate\":\"").Append(DescribeGateState()).Append("\",");
		sb.Append("\"sourceKey\":").Append(sourceKey.ToString(CultureInfo.InvariantCulture)).Append(',');
		sb.Append("\"targetKey\":").Append(targetKey.ToString(CultureInfo.InvariantCulture)).Append(',');
		sb.Append("\"beforeHelper\":\"").Append(Escape(beforeHelper)).Append("\",");
		sb.Append("\"beforeHelperIndex\":\"").Append(Escape(beforeHelperIndex)).Append("\",");
		sb.Append("\"afterHelper\":\"").Append(Escape(afterHelper)).Append("\",");
		sb.Append("\"afterHelperIndex\":\"").Append(Escape(afterHelperIndex)).Append("\",");
		sb.Append("\"beforeSourceFieldObjects\":").Append(beforeSourceMembership ? "true" : "false").Append(',');
		sb.Append("\"beforeDestFieldObjects\":").Append(beforeDestMembership ? "true" : "false").Append(',');
		sb.Append("\"afterSourceFieldObjects\":").Append(afterSourceMembership ? "true" : "false").Append(',');
		sb.Append("\"afterDestFieldObjects\":").Append(afterDestMembership ? "true" : "false").Append(',');
		sb.Append("\"helperAgree\":").Append(helperAgree ? "true" : "false").Append(',');
		sb.Append("\"dualAgree\":").Append(dualAgree ? "true" : "false");
		if (!string.IsNullOrWhiteSpace(failure))
			sb.Append(",\"failure\":\"").Append(Escape(failure)).Append('"');
		sb.Append('}');
		return sb.ToString();
	}

	private static string Escape(string value)
	{
		if (string.IsNullOrEmpty(value))
			return "";
		return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
	}

	private static bool TryReadUnitHex(object unit, out object hex)
	{
		return NativeCombatWriteGateway.TryReadExactMemberPublic(
			unit,
			GameSymbols.BattleEventLaws.BattleObjectHexMembers,
			out hex);
	}

	private static bool TryReadHexCoords(object hex, out int x, out int z)
	{
		x = 0;
		z = 0;
		return NativeCombatWriteGateway.TryReadIntMemberPublic(
			       hex,
			       GameSymbols.BattleEventLaws.HexXMembers,
			       out x)
		       && NativeCombatWriteGateway.TryReadIntMemberPublic(
			           hex,
			           GameSymbols.BattleEventLaws.HexZMembers,
			           out z);
	}

	private static string TryHexIndex(object hex)
	{
		if (hex == null)
			return "?";
		return NativeCombatWriteGateway.TryReadIntMemberPublic(
			       hex,
			       GameSymbols.BattleEventLaws.HexIndexMembers,
			       out var index)
			? index.ToString(CultureInfo.InvariantCulture)
			: "?";
	}

	private static bool TryFieldObjectsContains(object hex, object unit)
	{
		return NativeCombatWriteGateway.TryFieldObjectsContainsUnitPublic(hex, unit, out var contains, out _)
		       && contains;
	}

	private static object TryReadBattleLogic(object unit)
	{
		return NativeCombatWriteGateway.TryReadExactMemberPublic(
			       unit,
			       GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers,
			       out var logic)
			? logic
			: null;
	}

	private static int HexDistance(int ax, int az, int bx, int bz)
	{
		var dx = ax - bx;
		var dz = az - bz;
		return (Math.Abs(dx) + Math.Abs(dz) + Math.Abs(dx + dz)) / 2;
	}
}
