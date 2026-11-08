using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Hex.Session.Battle;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3BattleVisualInterop
{
	internal static MethodInfo ResolveNativeSpawnObjectMethod() =>
		ResolveNativeSpawnObjectMethod(GameSymbols.BattleVisual.SpawnObject);

	internal static MethodInfo ResolveNativeSpawnObjectMethod(GameSymbols.MethodSymbol nameHints)
	{
		var methods = ResolveNativeSpawnObjectMethods(nameHints);
		return methods.Count > 0 ? methods[0] : null;
	}

	internal static List<MethodInfo> ResolveNativeSpawnObjectMethods() =>
		ResolveNativeSpawnObjectMethods(GameSymbols.BattleVisual.SpawnObject);

	internal static List<MethodInfo> ResolveNativeSpawnObjectMethods(GameSymbols.MethodSymbol nameHints)
	{
		var hints = nameHints;
		var factoryType = ResolveSpawnFactoryType();
		var sideType = ResolveBattleSideType();

		var exactMatches = new List<MethodInfo>();
		var shapeMatches = new List<MethodInfo>();
		foreach (var typeName in GameSymbols.BattleVisual.SpawnHelperTypeNames)
		{
			var spawnHelperType = ResolveHexType("battle.visual.spawnHelper." + typeName, typeName);
			if (spawnHelperType == null)
				continue;

			foreach (var method in spawnHelperType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
			{
				if (!MatchesSpawnObjectShape(method, factoryType, sideType))
					continue;
				if (NameMatches(method.Name, hints.NameHints))
					AddUnique(exactMatches, method);
				else
					AddUnique(shapeMatches, method);
			}
		}

		return exactMatches.Count > 0 ? exactMatches : shapeMatches;
	}

	private static void AddUnique(List<MethodInfo> methods, MethodInfo method)
	{
		if (methods == null || method == null)
			return;
		for (var i = 0; i < methods.Count; i++)
		{
			if (methods[i] == method)
				return;
		}
		methods.Add(method);
	}

	private static Type ResolveHexType(string registryId, string obfuscatedHint)
	{
		var asm = typeof(Unit).Assembly;
		if (asm == null)
			return null;
		if (!string.IsNullOrWhiteSpace(obfuscatedHint))
		{
			var direct = asm.GetType(obfuscatedHint, throwOnError: false);
			if (direct != null)
				return direct;
		}
		// Multi-hint callers probe several aliases; stay quiet on intermediate misses.
		return GameMember.FindType(registryId, obfuscatedHint, logMiss: false);
	}

	private static Type ResolveSpawnFactoryType()
	{
		foreach (var hint in GameSymbols.BattleVisual.SpawnFactoryTypeNames)
		{
			var type = ResolveHexType("battle.visual.spawnFactory." + hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type ResolveBattleSideType()
	{
		foreach (var hint in GameSymbols.BattleUnitInit.SideTypeHints)
		{
			var type = ResolveHexType("battle.unit.side." + hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static bool MatchesSpawnObjectShape(MethodInfo method, Type factoryType, Type sideType)
	{
		if (method == null || method.ReturnType != typeof(FieldObject))
			return false;
		var ps = method.GetParameters();
		if (ps.Length != 6 && ps.Length != 8)
			return false;
		if (!MatchesSpawnParameterType(ps[0].ParameterType, factoryType, GameSymbols.BattleVisual.SpawnFactoryTypeNames))
			return false;
		if (ps[1].ParameterType != typeof(Unit))
			return false;
		if (!MatchesSpawnParameterType(ps[2].ParameterType, sideType, GameSymbols.BattleUnitInit.SideTypeHints))
			return false;
		if (ps[3].ParameterType != typeof(int) || ps[4].ParameterType != typeof(string))
			return false;
		if (ps.Length == 6)
			return ps[5].ParameterType == typeof(bool);
		return ps[5].ParameterType == typeof(bool)
		       && ps[6].ParameterType == typeof(bool)
		       && ps[7].ParameterType == typeof(bool);
	}

	private static bool MatchesSpawnParameterType(Type actual, Type resolvedExpected, string[] hints)
	{
		if (actual == null)
			return false;
		if (resolvedExpected != null && GameInteropTypes.TypesMatch(actual, resolvedExpected))
			return true;
		if (hints == null)
			return false;
		foreach (var hint in hints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			if (string.Equals(actual.Name, hint, StringComparison.Ordinal)
			    || string.Equals(actual.FullName, hint, StringComparison.Ordinal))
				return true;
			var resolved = ResolveHexType("battle.spawnParameter." + hint, hint);
			if (resolved != null && GameInteropTypes.TypesMatch(actual, resolved))
				return true;
		}
		return false;
	}

	private static bool NameMatches(string candidate, string[] names)
	{
		if (string.IsNullOrWhiteSpace(candidate) || names == null)
			return false;
		for (var i = 0; i < names.Length; i++)
		{
			if (string.Equals(candidate, names[i], StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	internal static bool HasLogicalField(Type ownerType, params string[] logicalNames)
	{
		if (ownerType == null || logicalNames == null)
			return false;
		TryInitializeIl2CppType(ownerType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		foreach (var name in logicalNames)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var type = ownerType; type != null; type = type.BaseType)
			{
				if (type.GetField(name, flags) != null || type.GetProperty(name, flags) != null)
					return true;
			}
			if (ResolveFieldPointer(ownerType, name) != IntPtr.Zero)
				return true;
		}

		var drawerBaseType = ResolveDrawerSupplementalBaseType();
		if (drawerBaseType != null && drawerBaseType != ownerType)
		{
			TryInitializeIl2CppType(drawerBaseType);
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				if (ResolveFieldPointer(drawerBaseType, name) != IntPtr.Zero)
					return true;
			}
		}

		return false;
	}

	internal static T TryReadUnityField<T>(object owner, params string[] logicalNames)
		where T : UnityEngine.Object
	{
		if (owner == null || logicalNames == null)
			return null;

		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;

		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var fieldPtr = ResolveFieldPointer(type, name);
				if (fieldPtr == IntPtr.Zero)
					continue;
				try
				{
					var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
					var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
					if (valuePtr == IntPtr.Zero)
						continue;
					var value = Il2CppObjectPool.Get<T>(valuePtr);
					if (value)
						return value;
				}
				catch
				{
				}
			}
		}

		var drawerBaseType = ResolveDrawerSupplementalBaseType();
		if (drawerBaseType != null && drawerBaseType != owner.GetType())
		{
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var fieldPtr = ResolveFieldPointer(drawerBaseType, name);
				if (fieldPtr == IntPtr.Zero)
					continue;
				try
				{
					var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
					var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
					if (valuePtr == IntPtr.Zero)
						continue;
					var value = Il2CppObjectPool.Get<T>(valuePtr);
					if (value)
						return value;
				}
				catch
				{
				}
			}
		}

		return null;
	}

	internal static bool TryWriteUnityField(object owner, UnityEngine.Object value, params string[] logicalNames)
	{
		if (owner == null || value == null || logicalNames == null)
			return false;

		if (TryWriteManagedUnityField(owner, value, logicalNames))
			return true;

		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;

		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				if (TryWriteNativeField(il2Cpp, type, name, value))
					return true;
			}
		}

		var drawerBaseType = ResolveDrawerSupplementalBaseType();
		if (drawerBaseType != null && drawerBaseType != owner.GetType())
		{
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				if (TryWriteNativeField(il2Cpp, drawerBaseType, name, value))
					return true;
			}
		}

		return false;
	}

	private static bool TryWriteNativeField(Il2CppObjectBase il2Cpp, Type ownerType, string logicalName, UnityEngine.Object value)
	{
		var fieldPtr = ResolveFieldPointer(ownerType, logicalName);
		if (fieldPtr == IntPtr.Zero)
			return false;
		try
		{
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var targetAddress = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
			IL2CPP.il2cpp_gc_wbarrier_set_field(
				objectPtr,
				targetAddress,
				IL2CPP.Il2CppObjectBaseToPtr(value as Il2CppObjectBase));
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryWriteManagedUnityField(object owner, UnityEngine.Object value, params string[] logicalNames)
	{
		var targetType = value.GetType();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var prop = type.GetProperty(name, flags);
				if (prop != null
				    && prop.CanWrite
				    && prop.GetIndexParameters().Length == 0
				    && targetType.IsAssignableFrom(prop.PropertyType))
				{
					try
					{
						prop.SetValue(owner, value);
						return true;
					}
					catch
					{
					}
				}

				var field = type.GetField(name, flags);
				if (field != null && targetType.IsAssignableFrom(field.FieldType))
				{
					try
					{
						field.SetValue(owner, value);
						return true;
					}
					catch
					{
					}
				}
			}
		}

		return false;
	}

	internal static Type ResolveDrawerSupplementalBaseType()
	{
		var asm = typeof(Unit).Assembly;
		foreach (var hint in GameSymbols.BattleVisual.DrawerSupplementalBaseTypeNames)
		{
			var type = asm.GetType(hint, throwOnError: false);
			if (IsDrawerSupplementalBaseCandidate(type))
				return type;
			type = GameMember.FindType("battle.visual.drawerBase." + hint, hint);
			if (IsDrawerSupplementalBaseCandidate(type))
				return type;
		}
		return null;
	}

	private static bool IsDrawerSupplementalBaseCandidate(Type type)
	{
		if (type == null)
			return false;
		TryInitializeIl2CppType(type);
		return HasTypedUnityMember(type, typeof(GameObject), GameSymbols.BattleVisual.CurrentEczMovementGameObjectFields)
		       && HasTypedUnityMember(type, typeof(Transform), GameSymbols.BattleVisual.CurrentEczMovementTransformFields)
		       && HasTypedUnityMember(type, typeof(GameObject), GameSymbols.BattleVisual.CurrentEczOrientationGameObjectFields)
		       && HasTypedUnityMember(type, typeof(Transform), GameSymbols.BattleVisual.CurrentEczOrientationTransformFields);
	}

	private static bool HasTypedUnityMember(Type ownerType, Type expectedType, params string[] logicalNames)
	{
		if (ownerType == null || expectedType == null || logicalNames == null)
			return false;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var type = ownerType; type != null; type = type.BaseType)
		{
			foreach (var name in logicalNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var field = type.GetField(name, flags);
				if (field != null && expectedType.IsAssignableFrom(field.FieldType))
					return true;
				var property = type.GetProperty(name, flags);
				if (property != null
				    && property.GetIndexParameters().Length == 0
				    && expectedType.IsAssignableFrom(property.PropertyType))
					return true;
			}
		}
		return false;
	}

	private static IntPtr ResolveFieldPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		// A scope-refused slot is a sentinel, not a field: Il2CppInterop logs an Error per native
		// lookup of it (160 lines in one battle on 25509697, BattleVisual.EcdAnimatorFields).
		if (GameSymbolScope.IsSentinel(logicalName))
			return IntPtr.Zero;

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var type = ownerType; type != null; type = type.BaseType)
		{
			foreach (var candidate in ExpandNativeFieldCandidates(logicalName))
			{
				var managedField = type.GetField(candidate.NativeInfoName, flags);
				if (managedField != null && managedField.FieldType == typeof(IntPtr) && managedField.IsStatic)
				{
					try
					{
						var ptr = (IntPtr)managedField.GetValue(null);
						if (ptr != IntPtr.Zero)
							return ptr;
					}
					catch
					{
					}
				}

				var classPtr = GetNativeClassPtr(type);
				if (classPtr == IntPtr.Zero)
					continue;
				try
				{
					var fieldPtr = IL2CPP.GetIl2CppField(classPtr, candidate.Il2CppName);
					if (fieldPtr != IntPtr.Zero)
						return fieldPtr;
				}
				catch
				{
				}
			}
		}

		return IntPtr.Zero;
	}

	private static IEnumerable<(string Il2CppName, string NativeInfoName)> ExpandNativeFieldCandidates(string logicalName)
	{
		if (string.IsNullOrWhiteSpace(logicalName))
			yield break;

		yield return (logicalName, "NativeFieldInfoPtr_" + logicalName);

		if (logicalName.StartsWith("field_", StringComparison.Ordinal))
			yield return (logicalName, "NativeFieldInfoPtr_" + logicalName);

		if (logicalName.StartsWith("<", StringComparison.Ordinal) && logicalName.EndsWith(">k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.IndexOf('>', StringComparison.Ordinal) - 1);
			yield return (logicalName, "NativeFieldInfoPtr__" + inner + "_k__BackingField");
			yield return (inner, "NativeFieldInfoPtr_" + inner);
		}

		if (logicalName.StartsWith("_", StringComparison.Ordinal) && logicalName.EndsWith("_k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.Length - "_k__BackingField".Length - 1);
			yield return ("<" + inner + ">k__BackingField", "NativeFieldInfoPtr_<" + inner + ">k__BackingField");
			yield return (inner, "NativeFieldInfoPtr_" + inner);
		}
	}

	private static IntPtr GetNativeClassPtr(Type managedType)
	{
		if (managedType == null)
			return IntPtr.Zero;

		try
		{
			var storeType = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			var nativeClassPtrField = storeType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public);
			if (nativeClassPtrField?.FieldType == typeof(IntPtr))
			{
				var value = (IntPtr)nativeClassPtrField.GetValue(null);
				if (value != IntPtr.Zero)
					return value;
			}
		}
		catch
		{
		}

		try
		{
			var field = managedType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field?.FieldType == typeof(IntPtr))
				return (IntPtr)field.GetValue(null);
		}
		catch
		{
		}

		return IntPtr.Zero;
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			RuntimeHelpers.RunClassConstructor(managedType.TypeHandle);
		}
		catch
		{
		}
	}
}
