using System;
using System.Reflection;
using System.Runtime.CompilerServices;

namespace OfflineUnlockMod;

/// <summary>
/// Identity of the current adventure session: the native pointer of the static session
/// <c>Hex.Session.Data.Data</c> root (live Golden Era holder czr =
/// ObjectPublicAbstractSealedSecaMaDacaStObHaca1Unique.field_Private_Static_Data_0, native field
/// "cato"; names in GameSymbols.AdventureVisionLaws). Session-scoped static state stamps this key
/// when it is stored and drops entries whose key differs from the current one, so a new game or
/// loaded save does not inherit it. Source/static only: that load/new game replaces the Data
/// root (rather than mutating it in place) is not runtime-proven.
/// </summary>
internal static class Homm3SessionIdentity
{
	private const BindingFlags StaticFlags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;

	internal static bool TryResolveSessionDataKey(out long key, out string failReason)
	{
		key = 0;
		foreach (var typeName in GameSymbols.AdventureVisionLaws.SessionHolderTypeHints)
		{
			if (string.IsNullOrWhiteSpace(typeName))
				continue;
			var type = ModActions.GetHexType(typeName)
				?? ModActions.GetHexType("Hex.Session." + typeName)
				?? ModActions.GetHexType("Hex." + typeName);
			if (type == null)
				continue;
			try { RuntimeHelpers.RunClassConstructor(type.TypeHandle); }
			catch { /* Il2Cpp static init is best-effort; the member read below decides. */ }

			foreach (var memberName in GameSymbols.AdventureVisionLaws.SessionDataMembers)
			{
				if (!TryReadStatic(type, memberName, out var data) || data == null)
					continue;
				if (Homm3DirectStateIdentity.TryResolveKey(data, out key, out failReason) && key != 0)
					return true;
			}
		}
		key = 0;
		failReason = "session Data static root unresolved";
		return false;
	}

	private static bool TryReadStatic(Type type, string name, out object value)
	{
		value = null;
		if (string.IsNullOrWhiteSpace(name))
			return false;
		try
		{
			var property = type.GetProperty(name, StaticFlags);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				value = property.GetValue(null);
				return true;
			}
			var field = type.GetField(name, StaticFlags);
			if (field != null)
			{
				value = field.GetValue(null);
				return true;
			}
			var method = type.GetMethod(name, StaticFlags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType != typeof(void))
			{
				value = method.Invoke(null, null);
				return true;
			}
		}
		catch (Exception)
		{
			value = null;
		}
		return false;
	}
}
