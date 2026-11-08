namespace OfflineUnlockMod;

/// <summary>
/// Write-only combat backend behind NativeCombatWriteGateway.
/// Named deliberately for write ownership; do not conflate with law-state backends.
/// </summary>
internal interface ICombatWriteBackend
{
	bool TryCommitPreparedDamage(ref int damage, PreparedDamageMutation mutation);

	bool TryWriteIntMember(object target, string memberId, int value, out string failReason);

	bool TryWriteObjectMember(object target, string memberId, object value, out string failReason);

	bool TryRecordDeferredIntent(string kind, object payload, out string failReason);

	bool TrySetOccupancy(object hexKey, object occupant, out string failReason);

	bool TryClearOccupancy(object hexKey, out string failReason);
}
