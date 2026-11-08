using System;
using System.Threading;

namespace OfflineUnlockMod;

/// <summary>Thread-local native-owner scopes used only by the startup preview deferral hooks.</summary>
internal static class NativePreviewStartupScope
{
	internal sealed class Frame
	{
		internal readonly long OwnerKey;
		internal readonly bool IsDemand;
		internal readonly Frame Previous;
		internal readonly int ThreadId;
		internal int DeferredCount;

		internal Frame(long ownerKey, bool isDemand, Frame previous)
		{
			OwnerKey = ownerKey;
			IsDemand = isDemand;
			Previous = previous;
			ThreadId = Thread.CurrentThread.ManagedThreadId;
		}
	}

	[ThreadStatic]
	private static Frame _current;

	internal static bool IsActive => _current != null;

	internal static Frame EnterWarmup(long ownerKey)
	{
		ValidateOwnerKey(ownerKey);
		return _current = new Frame(ownerKey, isDemand: false, _current);
	}

	internal static Frame EnterDemand(long ownerKey)
	{
		ValidateOwnerKey(ownerKey);
		for (var frame = _current; frame != null; frame = frame.Previous)
		{
			if (frame.OwnerKey != ownerKey)
				continue;
			if (frame.IsDemand)
				return null;
			return _current = new Frame(ownerKey, isDemand: true, _current);
		}
		return null;
	}

	internal static bool TryDefer(long ownerKey)
	{
		ValidateOwnerKey(ownerKey);
		for (var frame = _current; frame != null; frame = frame.Previous)
		{
			if (frame.OwnerKey != ownerKey)
				continue;
			if (frame.IsDemand)
				return false;
			checked { frame.DeferredCount++; }
			return true;
		}
		return false;
	}

	internal static void Exit(Frame frame)
	{
		if (frame == null)
			return;
		if (frame.ThreadId != Thread.CurrentThread.ManagedThreadId)
			throw new InvalidOperationException("Native preview scope exited on a different thread.");
		if (!ReferenceEquals(_current, frame))
			throw new InvalidOperationException("Native preview scope exited out of order.");
		_current = frame.Previous;
	}

	private static void ValidateOwnerKey(long ownerKey)
	{
		if (ownerKey == 0)
			throw new ArgumentOutOfRangeException(nameof(ownerKey), "Native preview scope owner key must be nonzero.");
	}
}
