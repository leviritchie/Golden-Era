using System;
using System.Runtime.CompilerServices;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Persistent Direct State identity for battle objects.
/// Live IL2CPP wrappers must key by native pointer (survives re-wrap).
/// Plain managed fixture objects use a tagged RuntimeHelpers identity only.
/// </summary>
internal static class Homm3DirectStateIdentity
{
	private const long ManagedIdentityTag = 1L << 62;

	internal static bool TryResolveKey(object target, out long key, out string failReason)
	{
		key = 0;
		if (target == null)
		{
			failReason = "direct-state identity target is null";
			return false;
		}

		if (target is Il2CppObjectBase native)
		{
			if (native.Pointer == IntPtr.Zero)
			{
				failReason = "direct-state IL2CPP identity pointer is null";
				return false;
			}
			key = native.Pointer.ToInt64();
			failReason = null;
			return true;
		}

		// Headless / model fixtures are plain managed objects without native pointers.
		var managed = RuntimeHelpers.GetHashCode(target);
		if (managed == 0)
			managed = 1;
		key = ManagedIdentityTag | (uint)managed;
		failReason = null;
		return true;
	}

	internal static long ResolveKeyOrZero(object target)
	{
		return TryResolveKey(target, out var key, out _) ? key : 0;
	}
}
