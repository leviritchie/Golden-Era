namespace OfflineUnlockMod;

/// <summary>
/// Shared fail-closed guard for future no-compromise custom law gameplay hooks.
/// It deliberately combines active law/rank resolution with packet proof gating
/// so hooks cannot accidentally consume law state while bypassing proof state.
/// </summary>
internal static class Homm3CustomLawRuntimeGuard
{
	internal struct CandidateLawContext
	{
		internal Homm3CustomFactionLawRuntime.ActiveLawState Law;
		internal string Packet;
		internal Homm3CustomLawPacketGate.PacketProofState ProofState;

		internal bool GameplayAllowed => Homm3CustomLawPacketGate.IsGameplayAllowed(Packet, out _);

		public override string ToString()
		{
			return Law
			       + " packet='"
			       + Packet
			       + "' proofStatus='"
			       + ProofState.ProofStatus
			       + "' gameplayAllowed="
			       + GameplayAllowed;
		}
	}

	internal struct AllowedLawContext
	{
		internal Homm3CustomFactionLawRuntime.ActiveLawState Law;
		internal string Packet;

		public override string ToString()
		{
			return Law + " packet='" + Packet + "'";
		}
	}

	internal static bool TryResolveAllowedActiveLaw(
		object sideOrLawOwner,
		int lawIndex,
		out AllowedLawContext context,
		out string failReason)
	{
		context = default;
		if (!TryResolveCandidateActiveLaw(sideOrLawOwner, lawIndex, out var candidate, out failReason))
			return false;
		if (!Homm3CustomLawPacketGate.IsGameplayAllowed(candidate.Packet, out failReason))
			return false;

		context = new AllowedLawContext
		{
			Law = candidate.Law,
			Packet = candidate.Packet,
		};
		failReason = null;
		return true;
	}

	internal static bool TryResolveCandidateActiveLaw(
		object sideOrLawOwner,
		int lawIndex,
		out CandidateLawContext context,
		out string failReason)
	{
		context = default;
		if (!Homm3CustomLawPacketGate.TryGetPacketForLawIndex(lawIndex, out var packet))
		{
			failReason = "law index has no no-compromise packet mapping";
			return false;
		}
		if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(sideOrLawOwner, lawIndex, out var law))
		{
			failReason = "active law/rank could not be resolved in this hook context for packet '" + packet + "': "
			             + Homm3CustomFactionLawRuntime.ExplainActiveKnownCustomLawResolution(sideOrLawOwner, lawIndex);
			return false;
		}
		if (!Homm3CustomLawPacketGate.TryGetProofState(packet, out var proofState))
		{
			failReason = "packet '" + packet + "' has no proof state";
			return false;
		}

		context = new CandidateLawContext
		{
			Law = law,
			Packet = packet,
			ProofState = proofState,
		};
		failReason = null;
		return true;
	}

	internal static bool TryResolveAllowedActiveLaw(
		object sideOrLawOwner,
		string expectedLawSid,
		out AllowedLawContext context,
		out string failReason)
	{
		context = default;
		if (!Homm3CustomFactionLawRuntime.TryParseKnownCustomLawId(expectedLawSid, out _, out var lawIndex, out _))
		{
			failReason = "law SID is not a known custom runtime law: '" + (expectedLawSid ?? "null") + "'";
			return false;
		}
		return TryResolveAllowedActiveLaw(sideOrLawOwner, lawIndex, out context, out failReason);
	}

	internal static bool TryResolveCandidateActiveLaw(
		object sideOrLawOwner,
		string expectedLawSid,
		out CandidateLawContext context,
		out string failReason)
	{
		context = default;
		if (!Homm3CustomFactionLawRuntime.TryParseKnownCustomLawId(expectedLawSid, out _, out var lawIndex, out _))
		{
			failReason = "law SID is not a known custom runtime law: '" + (expectedLawSid ?? "null") + "'";
			return false;
		}
		return TryResolveCandidateActiveLaw(sideOrLawOwner, lawIndex, out context, out failReason);
	}
}
