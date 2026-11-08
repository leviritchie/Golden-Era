using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace OfflineUnlockMod;

/// <summary>
/// M6 focused live-positive teleport/relocate diagnostic. Explicit flag-only path that
/// reaches <see cref="Homm3DirectStateAdapters.TryMove"/>(MovementTeleport) → journaled
/// <c>UnitData.bfdi</c> (same <see cref="NativeCombatWriteGateway.TryCommitUnitHexMove"/>
/// path as M3 / <c>movement.commit.bfdi_v1</c>) with CapLog dual-readback (helper hex +
/// <c>Hex.fieldObjects</c>) on a non-adjacent destination.
/// Production MovementTeleport ungates only after a proof ledger record cites CapLog agree.
/// </summary>
internal static class Homm3DirectStateM6BfdiTeleportDiagnostic
{
	internal const string DiagnosticFlag = "homm3_direct_state_m6_bfdi_teleport.flag";
	internal const string CapLogPrefix = "HoMM3 M6_BFDI_TELEPORT_DUAL_READBACK";
	internal const string RelocateCardId = GameSymbols.DirectStateLaws.MovementRelocateCardId;
	internal const string CommitCardId = GameSymbols.DirectStateLaws.MovementCommitCardId;

	/// <summary>
	/// Set true only after focused live-positive CapLog dual-readback agree is recorded.
	/// Keeps validators and gameplay gate synchronized.
	/// Proven 2026-07-20: non_adjacent_teleport via TryMove(MovementTeleport) →
	/// journaled UnitData.bfdi / Method_Public_set_Void_Hex_0 with helper hex +
	/// fieldObjects CapLog agree (proof_ledger/entries/ds_m6_movement_teleport_live_positive.json).
	/// </summary>
	internal const bool MovementTeleportLivePositiveProven = true;

	internal static bool IsDiagnosticPilotEnabled =>
		Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag);

	internal static bool IsMovementTeleportAllowed()
	{
		return MovementTeleportLivePositiveProven || IsDiagnosticPilotEnabled;
	}

	internal static string DescribeGateState()
	{
		if (MovementTeleportLivePositiveProven)
			return "ungated_live_positive_proven";
		if (IsDiagnosticPilotEnabled)
			return "diagnostic_pilot_flag";
		return "gated";
	}

	/// <summary>
	/// Relocate one live hexed registered battle unit onto an empty non-adjacent hex
	/// through the production MovementTeleport adapter path (explicitDestinationHex).
	/// </summary>
	internal static bool TryRunNonAdjacentTeleportRelocate(
		out string resultJson,
		out string failReason)
	{
		resultJson = null;
		failReason = null;
		if (!IsMovementTeleportAllowed())
		{
			failReason =
				"MovementTeleport still gated; enable "
				+ DiagnosticFlag
				+ " for M6 diagnostic or set MovementTeleportLivePositiveProven after CapLog agree";
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
				"need registered battle units for teleport relocate (count="
				+ (units?.Count ?? 0)
				+ "); enter combat first";
			return false;
		}

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

			if (!TryFindEmptyNonAdjacentHex(
				    unit,
				    sourceHex,
				    sx,
				    sz,
				    out var destHex,
				    out var destDistance,
				    out var findFailure))
			{
				failReason = findFailure ?? "no empty non-adjacent hex";
				continue;
			}

			var beforeSourceMembership = TryFieldObjectsContains(sourceHex, unit);
			var beforeDestMembership = TryFieldObjectsContains(destHex, unit);
			var beforeHelperIndex = TryHexIndex(sourceHex);
			var beforeHelperCoords = "(" + sx + "," + sz + ")";
			TryReadHexCoords(destHex, out var dx, out var dz);
			var scope = TryReadBattleLogic(unit) ?? unit;

			Plugin.LogSource?.LogInfo(
				CapLogPrefix
				+ " attempt scenario=non_adjacent_teleport"
				+ " unitKey=" + units[i].UnitKey
				+ " beforeHelper=" + beforeHelperCoords
				+ " beforeHelperIndex=" + beforeHelperIndex
				+ " beforeSourceFieldObjects=" + beforeSourceMembership
				+ " beforeDestFieldObjects=" + beforeDestMembership
				+ " destCoords=(" + dx + "," + dz + ")"
				+ " destIndex=" + TryHexIndex(destHex)
				+ " axialDistance=" + destDistance
				+ " commitCard=" + CommitCardId
				+ " relocateCard=" + RelocateCardId
				+ ".");

			if (!Homm3DirectStateAdapters.TryMove(
				    scope,
				    unit,
				    unit,
				    Homm3DirectStateOperation.MovementTeleport,
				    destHex,
				    out var destination,
				    out failReason))
			{
				Plugin.LogSource?.LogWarning(
					CapLogPrefix
					+ " reject scenario=non_adjacent_teleport reason="
					+ (failReason ?? "null"));
				return false;
			}

			return FinishDualReadback(
				"non_adjacent_teleport",
				units[i].UnitKey,
				units[i].UnitKey,
				unit,
				sourceHex,
				destination ?? destHex,
				beforeHelperCoords,
				beforeHelperIndex,
				beforeSourceMembership,
				beforeDestMembership,
				destDistance,
				out resultJson,
				out failReason);
		}

		failReason =
			"no teleport-relocatable unit with empty non-adjacent hex (inspected="
			+ inspected
			+ " withHex="
			+ withHex
			+ "; last="
			+ (failReason ?? "none")
			+ ")";
		return false;
	}

	private static bool TryFindEmptyNonAdjacentHex(
		object unit,
		object sourceHex,
		int sx,
		int sz,
		out object destHex,
		out int destDistance,
		out string failReason)
	{
		destHex = null;
		destDistance = 0;
		failReason = null;

		// BFS over native neighbour field links. Prefer axial distance >= 2 (teleport-style).
		var queue = new Queue<object>();
		var seen = new HashSet<long>();
		queue.Enqueue(sourceHex);
		seen.Add(HexIdentityKey(sourceHex, sx, sz));

		const int maxVisit = 96;
		var visited = 0;
		while (queue.Count > 0 && visited < maxVisit)
		{
			var current = queue.Dequeue();
			visited++;
			if (!Homm3DirectStateHexNeighbourNative.TryReadNeighbourSlots(
				    current,
				    out var neighbours,
				    out _)
			    || neighbours == null)
				continue;

			for (var n = 0; n < neighbours.Length; n++)
			{
				var candidate = neighbours[n];
				if (candidate == null)
					continue;
				if (!TryReadHexCoords(candidate, out var nx, out var nz))
					continue;
				var key = HexIdentityKey(candidate, nx, nz);
				if (!seen.Add(key))
					continue;
				queue.Enqueue(candidate);

				var dist = HexDistance(sx, sz, nx, nz);
				if (dist < 2)
					continue;
				if (TryFieldObjectsContains(candidate, unit))
					continue;
				if (!IsDestinationAcceptable(candidate, unit))
					continue;

				destHex = candidate;
				destDistance = dist;
				failReason = null;
				return true;
			}
		}

		failReason =
			"BFS found no empty non-adjacent hex (visited="
			+ visited
			+ " queued="
			+ queue.Count
			+ ")";
		return false;
	}

	private static bool IsDestinationAcceptable(object hex, object unit)
	{
		// Mirror NativeCombatWriteGateway.ValidateDestination without inventing a second path.
		if (!NativeCombatWriteGateway.TryReadExactMemberPublic(
			    hex,
			    GameSymbols.DirectStateLaws.HexBlockedMembers,
			    out var blockedObj))
			return false;
		if (blockedObj is bool blocked && blocked)
			return false;
		if (!NativeCombatWriteGateway.TryReadExactMemberPublic(
			    hex,
			    GameSymbols.BattleEventLaws.HexOccupantMembers,
			    out var occupant))
			return false;
		if (occupant == null || ReferenceEquals(occupant, unit))
			return true;
		return occupant is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase occNative
		       && unit is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase unitNative
		       && occNative.Pointer != IntPtr.Zero
		       && occNative.Pointer == unitNative.Pointer;
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
		int axialDistance,
		out string resultJson,
		out string failReason)
	{
		resultJson = null;
		if (!TryReadUnitHex(target, out var afterHex) || afterHex == null)
		{
			failReason = "post-teleport helper hex unavailable";
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
			+ " axialDistance=" + axialDistance
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
			scenario,
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
			axialDistance,
			null);
		if (!dualAgree)
		{
			failReason = "dual readback disagree after bfdi teleport commit";
			return false;
		}

		failReason = null;
		return true;
	}

	private static string BuildResultJson(
		bool ok,
		string scenario,
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
		int axialDistance,
		string failure)
	{
		var sb = new StringBuilder(640);
		sb.Append('{');
		sb.Append("\"ok\":").Append(ok ? "true" : "false").Append(',');
		sb.Append("\"scenario\":\"").Append(Escape(scenario)).Append("\",");
		sb.Append("\"gate\":\"").Append(DescribeGateState()).Append("\",");
		sb.Append("\"commitCard\":\"").Append(Escape(CommitCardId)).Append("\",");
		sb.Append("\"relocateCard\":\"").Append(Escape(RelocateCardId)).Append("\",");
		sb.Append("\"sourceKey\":").Append(sourceKey.ToString(CultureInfo.InvariantCulture)).Append(',');
		sb.Append("\"targetKey\":").Append(targetKey.ToString(CultureInfo.InvariantCulture)).Append(',');
		sb.Append("\"beforeHelper\":\"").Append(Escape(beforeHelper)).Append("\",");
		sb.Append("\"beforeHelperIndex\":\"").Append(Escape(beforeHelperIndex)).Append("\",");
		sb.Append("\"afterHelper\":\"").Append(Escape(afterHelper)).Append("\",");
		sb.Append("\"afterHelperIndex\":\"").Append(Escape(afterHelperIndex)).Append("\",");
		sb.Append("\"axialDistance\":").Append(axialDistance.ToString(CultureInfo.InvariantCulture)).Append(',');
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

	private static long HexIdentityKey(object hex, int x, int z)
	{
		if (NativeCombatWriteGateway.TryReadIntMemberPublic(
			    hex,
			    GameSymbols.BattleEventLaws.HexIndexMembers,
			    out var index))
			return ((long)index << 32) ^ unchecked((uint)(x * 397) ^ (uint)z);
		return ((long)x << 32) ^ unchecked((uint)z);
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
