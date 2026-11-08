using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Production write backend: delegates to sealed live gateway paths.
/// </summary>
internal sealed class LiveCombatWriteBackend : ICombatWriteBackend
{
	internal static readonly LiveCombatWriteBackend Instance = new();

	private LiveCombatWriteBackend()
	{
	}

	public bool TryCommitPreparedDamage(ref int damage, PreparedDamageMutation mutation)
	{
		return NativeCombatWriteGateway.TryCommitPreparedDamageLive(ref damage, mutation);
	}

	public bool TryWriteIntMember(object target, string memberId, int value, out string failReason)
	{
		return NativeCombatWriteGateway.TryWriteIntMemberLive(target, memberId, value, out failReason);
	}

	public bool TryWriteObjectMember(object target, string memberId, object value, out string failReason)
	{
		return NativeCombatWriteGateway.TryWriteObjectMemberLive(target, memberId, value, out failReason);
	}

	public bool TryRecordDeferredIntent(string kind, object payload, out string failReason)
	{
		failReason = "live backend does not buffer deferred intents; use gateway invoke paths";
		return false;
	}

	public bool TrySetOccupancy(object hexKey, object occupant, out string failReason)
	{
		failReason = "live occupancy is owned by native hex commit paths";
		return false;
	}

	public bool TryClearOccupancy(object hexKey, out string failReason)
	{
		failReason = "live occupancy is owned by native hex commit paths";
		return false;
	}
}

/// <summary>
/// Headless model write backend for replay only. Stores scalars, collections,
/// occupancy, and deferred invocation intents without touching native combat.
/// </summary>
internal sealed class ModelCombatWriteBackend : ICombatWriteBackend
{
	private readonly Dictionary<string, int> _ints = new(StringComparer.Ordinal);
	private readonly Dictionary<string, object> _objects = new(StringComparer.Ordinal);
	private readonly Dictionary<string, List<object>> _lists = new(StringComparer.Ordinal);
	private readonly Dictionary<string, object> _occupancy = new(StringComparer.Ordinal);
	private readonly List<(string Kind, object Payload)> _deferred = new();

	internal IReadOnlyList<(string Kind, object Payload)> DeferredIntents => _deferred;

	internal int ReadInt(object target, string memberId, int fallback = 0)
	{
		return _ints.TryGetValue(Key(target, memberId), out var value) ? value : fallback;
	}

	internal bool TryGetOccupant(object hexKey, out object occupant)
	{
		return _occupancy.TryGetValue(Key(hexKey, "occupant"), out occupant);
	}

	internal int ListCount(object list)
	{
		return EnsureList(list).Count;
	}

	public bool TryCommitPreparedDamage(ref int damage, PreparedDamageMutation mutation)
	{
		if (!mutation.IsValid || damage != mutation.ExpectedDamage)
			return false;
		damage = mutation.NewDamage;
		_ints[Key("damage", "lastCommitted")] = damage;
		return true;
	}

	public bool TryWriteIntMember(object target, string memberId, int value, out string failReason)
	{
		if (target == null || string.IsNullOrWhiteSpace(memberId))
		{
			failReason = "model write int requires target and memberId";
			return false;
		}
		_ints[Key(target, memberId)] = value;
		failReason = null;
		return true;
	}

	public bool TryWriteObjectMember(object target, string memberId, object value, out string failReason)
	{
		if (target == null || string.IsNullOrWhiteSpace(memberId))
		{
			failReason = "model write object requires target and memberId";
			return false;
		}
		_objects[Key(target, memberId)] = value;
		failReason = null;
		return true;
	}

	public bool TryRecordDeferredIntent(string kind, object payload, out string failReason)
	{
		if (string.IsNullOrWhiteSpace(kind))
		{
			failReason = "deferred intent kind is required";
			return false;
		}
		_deferred.Add((kind, payload));
		failReason = null;
		return true;
	}

	public bool TrySetOccupancy(object hexKey, object occupant, out string failReason)
	{
		if (hexKey == null)
		{
			failReason = "occupancy hex key is null";
			return false;
		}
		var key = Key(hexKey, "occupant");
		if (_occupancy.TryGetValue(key, out var existing) && !ReferenceEquals(existing, occupant))
		{
			failReason = "occupancy blocked: hex already occupied";
			return false;
		}
		_occupancy[key] = occupant;
		failReason = null;
		return true;
	}

	public bool TryClearOccupancy(object hexKey, out string failReason)
	{
		if (hexKey == null)
		{
			failReason = "occupancy hex key is null";
			return false;
		}
		_occupancy.Remove(Key(hexKey, "occupant"));
		failReason = null;
		return true;
	}

	internal bool TryInsertListItem(object list, object item, int index, out string failReason)
	{
		var bucket = EnsureList(list);
		if (index < 0 || index > bucket.Count)
		{
			failReason = "model list insert index out of range";
			return false;
		}
		bucket.Insert(index, item);
		failReason = null;
		return true;
	}

	internal bool TryRemoveListItem(object list, object item, out string failReason)
	{
		var bucket = EnsureList(list);
		if (!bucket.Remove(item))
		{
			failReason = "model list remove missed item";
			return false;
		}
		failReason = null;
		return true;
	}

	internal bool TryReorderListItem(object list, object item, int newIndex, out string failReason)
	{
		var bucket = EnsureList(list);
		var current = bucket.IndexOf(item);
		if (current < 0)
		{
			failReason = "model list reorder missed item";
			return false;
		}
		if (newIndex < 0 || newIndex >= bucket.Count)
		{
			failReason = "model list reorder index out of range";
			return false;
		}
		bucket.RemoveAt(current);
		if (newIndex > current)
			newIndex--;
		bucket.Insert(newIndex, item);
		failReason = null;
		return true;
	}

	private List<object> EnsureList(object list)
	{
		var key = Key(list ?? "list", "items");
		if (!_lists.TryGetValue(key, out var bucket))
		{
			bucket = new List<object>();
			_lists[key] = bucket;
		}
		return bucket;
	}

	private static string Key(object target, string memberId)
	{
		return RuntimeHelpersIdentity(target) + ":" + (memberId ?? "");
	}

	private static string RuntimeHelpersIdentity(object target)
	{
		if (target == null)
			return "null";
		if (target is string text)
			return "s:" + text;
		return "o:" + System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(target)
			.ToString(System.Globalization.CultureInfo.InvariantCulture);
	}
}
