using System;
using System.Reflection;
using System.Runtime.InteropServices;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;

namespace OfflineUnlockMod;

/// <summary>
/// Production commit path is journaled <c>UnitData.bfdi</c> (Direct State card
/// <c>movement.commit.bfdi_v1</c>) mutating <c>fieldObjects</c> via <c>bcyn</c>/<c>bcyl</c>.
/// Legacy helper+<c>_cfqf</c> dual-write remains diagnostic-only and is never called from
/// <see cref="TryMoveUnitHex"/>. MovementPush stays gated in TryMove until focused live-positive.
/// </summary>
internal static class Homm3DirectStateUnitHexNative
{
	internal static bool TryMoveUnitHex(
		object unit,
		object fromHex,
		object toHex,
		out string failReason)
	{
		return TryMoveUnitHexViaBfdi(unit, toHex, out failReason);
	}

	/// <summary>
	/// Journaled one-invoke commit: <c>UnitData.bfdi(dest)</c>
	/// (<see cref="GameSymbols.DirectStateLaws.MovementCommitOwnerMembers"/>).
	/// </summary>
	internal static bool TryMoveUnitHexViaBfdi(object unit, object toHex, out string failReason)
	{
		if (unit == null || toHex == null)
		{
			failReason = "unit hex move requires unit and destination hex";
			return false;
		}
		if (unit is not Il2CppObjectBase)
		{
			failReason = "unit hex move requires an IL2CPP unit";
			return false;
		}

		if (!TryReadManagedMember(unit, GameSymbols.BattleEventLaws.UnitDataMembers, out var unitData)
		    || unitData == null)
		{
			failReason = "UnitData unavailable for journaled bfdi commit ("
			             + GameSymbols.DirectStateLaws.MovementCommitCardId + ")";
			return false;
		}

		var bfdi = ResolveInstanceMethod(
			unitData.GetType(),
			GameSymbols.DirectStateLaws.MovementCommitOwnerMembers,
			parameterCount: 1);
		if (bfdi == null)
		{
			failReason = "UnitData.bfdi MethodInfo unresolved ("
			             + GameSymbols.DirectStateLaws.MovementCommitCardId + ")";
			return false;
		}

		try
		{
			bfdi.Invoke(unitData, new[] { toHex });
		}
		catch (Exception ex)
		{
			var inner = (ex as TargetInvocationException)?.InnerException ?? ex;
			failReason = "UnitData.bfdi invoke failed: " + inner.GetType().Name + ": " + inner.Message;
			return false;
		}

		failReason = null;
		return true;
	}

	/// <summary>
	/// Diagnostic / legacy dual-write only. Do not call from production TryCommitUnitHexMove.
	/// Writes helper hex + <c>_cfqf</c> (lastCorpse — NOT movement occupancy).
	/// </summary>
	internal static bool TryMoveUnitHexLegacyDualWrite(
		object unit,
		object fromHex,
		object toHex,
		out string failReason)
	{
		if (unit == null || toHex == null)
		{
			failReason = "unit hex move requires unit and destination hex";
			return false;
		}
		if (unit is not Il2CppObjectBase)
		{
			failReason = "unit hex move requires an IL2CPP unit";
			return false;
		}

		if (!TryReadManagedMember(unit, GameSymbols.DirectStateLaws.FieldObjectPositionHelperMembers, out var helper)
		    || helper == null)
		{
			failReason = "unit position helper unavailable";
			return false;
		}

		if (!TryWriteNativeReference(helper, GameSymbols.DirectStateLaws.FieldObjectHexWriteMembers, toHex, out failReason))
			return false;

		if (fromHex != null
		    && TryReadManagedMember(fromHex, GameSymbols.BattleEventLaws.HexOccupantMembers, out var fromOccupant)
		    && fromOccupant != null
		    && SameNativeObject(fromOccupant, unit))
		{
			if (!TryWriteNativeReference(fromHex, GameSymbols.DirectStateLaws.HexOccupantWriteMembers, null, out failReason))
				return false;
		}

		if (!TryWriteNativeReference(toHex, GameSymbols.DirectStateLaws.HexOccupantWriteMembers, unit, out failReason))
			return false;

		failReason = null;
		return true;
	}

	private static MethodInfo ResolveInstanceMethod(Type type, string[] names, int parameterCount)
	{
		if (type == null || names == null)
			return null;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			MethodInfo[] methods;
			try
			{
				methods = current.GetMethods(flags);
			}
			catch
			{
				continue;
			}
			for (var i = 0; i < names.Length; i++)
			{
				var want = names[i];
				if (string.IsNullOrWhiteSpace(want))
					continue;
				for (var mi = 0; mi < methods.Length; mi++)
				{
					var method = methods[mi];
					if (!string.Equals(method.Name, want, StringComparison.Ordinal))
						continue;
					if (method.GetParameters().Length != parameterCount)
						continue;
					return method;
				}
			}
		}
		return null;
	}

	internal static bool TryValidateSurface(out string failReason)
	{
		var unitType = ResolveType(GameSymbols.BattleEventLaws.BattleUnitTypeHints);
		var hexType = ResolveType(GameSymbols.DirectStateLaws.BattleHexTypeHints);
		if (unitType == null || hexType == null)
		{
			failReason = "unit/hex types unavailable for movement surface";
			return false;
		}

		TryInitializeIl2CppType(unitType);
		TryInitializeIl2CppType(hexType);

		if (!TryReadManagedMemberType(unitType, GameSymbols.BattleEventLaws.UnitDataMembers, out var unitDataType)
		    || unitDataType == null)
		{
			failReason = "UnitData member unresolved for journaled bfdi surface";
			return false;
		}
		TryInitializeIl2CppType(unitDataType);
		if (ResolveInstanceMethod(unitDataType, GameSymbols.DirectStateLaws.MovementCommitOwnerMembers, 1) == null)
		{
			failReason = "UnitData.bfdi MethodInfo missing ("
			             + GameSymbols.DirectStateLaws.MovementCommitCardId + ")";
			return false;
		}

		if (!TypeHasNativeField(hexType, GameSymbols.DirectStateLaws.HexFieldObjectsMembers, out _))
		{
			// Prefer managed fieldObjects member presence when NativeFieldInfoPtr naming differs.
			if (!TypeHasManagedMember(hexType, GameSymbols.DirectStateLaws.HexFieldObjectsMembers))
			{
				failReason = "Hex.fieldObjects occupancy list surface missing";
				return false;
			}
		}

		failReason = null;
		return true;
	}

	private static bool TryReadManagedMemberType(Type ownerType, string[] names, out Type memberType)
	{
		memberType = null;
		if (ownerType == null || names == null)
			return false;
		for (var current = ownerType; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var prop = current.GetProperty(name, flags);
					if (prop != null)
					{
						memberType = prop.PropertyType;
						return memberType != null;
					}
					var field = current.GetField(name, flags);
					if (field != null)
					{
						memberType = field.FieldType;
						return memberType != null;
					}
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						memberType = method.ReturnType;
						return memberType != null;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static bool TypeHasManagedMember(Type ownerType, string[] names)
	{
		if (ownerType == null || names == null)
			return false;
		for (var current = ownerType; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags =
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					if (current.GetProperty(name, flags) != null || current.GetField(name, flags) != null)
						return true;
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static bool TryWriteNativeReference(object owner, string[] logicalNames, object value, out string failReason)
	{
		failReason = null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
		{
			failReason = "native reference write requires an IL2CPP owner";
			return false;
		}

		var ownerType = owner.GetType();
		TryInitializeIl2CppType(ownerType);
		for (var i = 0; i < logicalNames.Length; i++)
		{
			var logical = logicalNames[i];
			if (string.IsNullOrWhiteSpace(logical))
				continue;
			var fieldPtr = ResolveNativeFieldPointer(ownerType, logical);
			if (fieldPtr == IntPtr.Zero)
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var address = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
				var valuePtr = value is Il2CppObjectBase valueNative
					? IL2CPP.Il2CppObjectBaseToPtr(valueNative)
					: IntPtr.Zero;
				IL2CPP.il2cpp_gc_wbarrier_set_field(objectPtr, address, valuePtr);
				failReason = null;
				return true;
			}
			catch (Exception ex)
			{
				failReason = "native reference write failed (" + logical + "): "
				             + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}

		failReason = "native reference field unresolved: " + string.Join(",", logicalNames);
		return false;
	}

	private static bool TryReadManagedMember(object target, string[] names, out object value)
	{
		value = null;
		if (target == null || names == null)
			return false;
		for (var current = target.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						value = field.GetValue(target);
						return true;
					}
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						value = property.GetValue(target, null);
						return true;
					}
					// Live GE UnitData is often Method_Public_get_UnitData_0 / beyi(), not a field.
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						value = method.Invoke(target, null);
						return true;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static bool TypeHasNativeField(Type ownerType, string[] logicalNames, out string matched)
	{
		matched = null;
		if (ownerType == null || logicalNames == null)
			return false;
		for (var i = 0; i < logicalNames.Length; i++)
		{
			var logical = logicalNames[i];
			if (string.IsNullOrWhiteSpace(logical))
				continue;
			if (ResolveNativeFieldPointer(ownerType, logical) == IntPtr.Zero)
				continue;
			matched = logical;
			return true;
		}
		return false;
	}

	private static IntPtr ResolveNativeFieldPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		foreach (var nativeInfoName in ExpandNativeFieldInfoNames(logicalName))
		{
			for (var current = ownerType; current != null; current = current.BaseType)
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

	private static System.Collections.Generic.IEnumerable<string> ExpandNativeFieldInfoNames(string logicalName)
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

	private static Type ResolveType(string[] hints)
	{
		if (hints == null)
			return null;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = AccessToolsType(hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type AccessToolsType(string name)
	{
		try
		{
			return HarmonyLib.AccessTools.TypeByName(name);
		}
		catch
		{
			return null;
		}
	}

	private static bool SameNativeObject(object left, object right)
	{
		if (ReferenceEquals(left, right))
			return true;
		return left is Il2CppObjectBase a
		       && right is Il2CppObjectBase b
		       && a.Pointer != IntPtr.Zero
		       && a.Pointer == b.Pointer;
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
