using System;
using System.Collections.Generic;

namespace OfflineUnlockMod;

/// <summary>
/// Battle-local state table keyed by native IL2CPP identity (<see cref="Homm3DirectStateIdentity"/>),
/// replacing <c>ConditionalWeakTable&lt;object, T&gt;</c> keyed by the managed proxy. Separately
/// marshaled proxies of one native unit/side are different managed objects, so a store through one
/// proxy (e.g. a counterattack observation) and a read through another (e.g. DamageInfo.Caster)
/// silently missed. Native pointers can be reused after the native object dies, so owners must
/// <see cref="Clear"/> at battle cleanup. A target with no resolvable identity is refused
/// (logged once per table), never stored under a shared zero key.
/// Contract: tools/validate_native_hook_safety_contract.py.
/// </summary>
internal sealed class Homm3NativeKeyedTable<TValue> where TValue : class, new()
{
	private readonly Dictionary<long, TValue> _byKey = new();
	private readonly object _gate = new();
	private readonly string _name;
	private bool _loggedUnresolved;

	internal Homm3NativeKeyedTable(string name)
	{
		_name = name ?? "native-keyed table";
	}

	/// <summary>Returns the state for <paramref name="target"/>, creating it; null when the target has no native identity.</summary>
	internal TValue GetOrCreateValue(object target)
	{
		if (!TryResolve(target, out var key))
			return null;
		lock (_gate)
		{
			if (!_byKey.TryGetValue(key, out var value) || value == null)
			{
				value = new TValue();
				_byKey[key] = value;
			}
			return value;
		}
	}

	internal bool TryGetValue(object target, out TValue value)
	{
		value = null;
		if (!TryResolve(target, out var key))
			return false;
		lock (_gate)
			return _byKey.TryGetValue(key, out value) && value != null;
	}

	internal int Clear()
	{
		lock (_gate)
		{
			var count = _byKey.Count;
			_byKey.Clear();
			return count;
		}
	}

	private bool TryResolve(object target, out long key)
	{
		key = 0;
		if (target == null)
			return false;
		if (Homm3DirectStateIdentity.TryResolveKey(target, out key, out var failReason) && key != 0)
			return true;
		if (!_loggedUnresolved)
		{
			_loggedUnresolved = true;
			Plugin.LogSource?.LogWarning("HoMM3 " + _name + ": target " + target.GetType().FullName
				+ " has no native identity (" + (failReason ?? "zero key") + "); state refused. Logged once.");
		}
		return false;
	}
}

internal static class Homm3NativeIdentity
{
	/// <summary>Native-identity equality for IL2CPP proxies (two proxies of one native object are equal).</summary>
	internal static bool Same(object left, object right)
	{
		if (left == null || right == null)
			return left == null && right == null;
		if (ReferenceEquals(left, right))
			return true;
		var l = Homm3DirectStateIdentity.ResolveKeyOrZero(left);
		return l != 0 && l == Homm3DirectStateIdentity.ResolveKeyOrZero(right);
	}
}
