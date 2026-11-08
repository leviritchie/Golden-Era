using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;

namespace OfflineUnlockMod;

/// <summary>
/// Reads Hex.Session.Battle.Hex neighbour slots through IL2CPP native field offsets.
/// Never reflectively invoke the six generated Hex neighbour accessors (live AccessViolation).
/// </summary>
internal static class Homm3DirectStateHexNeighbourNative
{
	internal static bool TryReadNeighbourSlots(object hex, out object[] neighbours, out string failReason)
	{
		neighbours = null;
		if (hex == null)
		{
			failReason = "neighbour lookup requires a hex";
			return false;
		}
		if (hex is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
		{
			failReason = "neighbour lookup requires an IL2CPP hex";
			return false;
		}

		var names = GameSymbols.DirectStateLaws.HexNeighbourFieldMembers;
		if (names == null || names.Length != 6)
		{
			failReason = "HexNeighbourFieldMembers must list exactly six live interop slots";
			return false;
		}

		var ownerType = hex.GetType();
		TryInitializeIl2CppType(ownerType);
		var values = new object[names.Length];
		for (var i = 0; i < names.Length; i++)
		{
			if (!TryReadHexReferenceSlot(il2Cpp, ownerType, names[i], out values[i], out failReason))
				return false;
		}

		neighbours = values;
		failReason = null;
		return true;
	}

	private static bool TryReadHexReferenceSlot(
		Il2CppObjectBase owner,
		Type ownerType,
		string logicalName,
		out object value,
		out string failReason)
	{
		value = null;
		var fieldPtr = ResolveNativeFieldPointer(ownerType, logicalName);
		if (fieldPtr == IntPtr.Zero)
		{
			failReason = "native neighbour field pointer missing: " + logicalName;
			return false;
		}

		try
		{
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(owner);
			var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
			if (valuePtr == IntPtr.Zero)
			{
				failReason = null;
				return true;
			}

			var wrapped = WrapHexPointer(valuePtr, ownerType);
			if (wrapped == null)
			{
				failReason = "native neighbour Hex wrap failed: " + logicalName;
				return false;
			}

			value = wrapped;
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native neighbour read failed (" + logicalName + "): "
			             + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static object WrapHexPointer(IntPtr valuePtr, Type hexType)
	{
		if (valuePtr == IntPtr.Zero || hexType == null)
			return null;
		try
		{
			var ctor = hexType.GetConstructor(
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
				null,
				new[] { typeof(IntPtr) },
				null);
			if (ctor == null)
				return null;
			var constructed = ctor.Invoke(new object[] { valuePtr });
			return constructed != null && hexType.IsInstanceOfType(constructed) ? constructed : null;
		}
		catch
		{
			return null;
		}
	}

	private static IntPtr ResolveNativeFieldPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			foreach (var nativeInfoName in ExpandNativeFieldInfoNames(logicalName))
			{
				try
				{
					var field = current.GetField(nativeInfoName, flags);
					if (field == null || field.FieldType != typeof(IntPtr) || !field.IsStatic)
						continue;
					var ptr = (IntPtr)field.GetValue(null);
					if (ptr != IntPtr.Zero)
						return ptr;
				}
				catch
				{
				}
			}
		}
		return IntPtr.Zero;
	}

	private static IEnumerable<string> ExpandNativeFieldInfoNames(string logicalName)
	{
		yield return "NativeFieldInfoPtr_" + logicalName;
		if (logicalName.StartsWith("_", StringComparison.Ordinal)
		    && logicalName.EndsWith("_k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.Length - "_k__BackingField".Length - 1);
			if (!string.IsNullOrWhiteSpace(inner))
			{
				yield return "NativeFieldInfoPtr__" + inner + "_k__BackingField";
				yield return "NativeFieldInfoPtr_" + inner;
			}
		}
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			var storeType = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			storeType.TypeInitializer?.Invoke(null, null);
		}
		catch
		{
		}
	}
}
