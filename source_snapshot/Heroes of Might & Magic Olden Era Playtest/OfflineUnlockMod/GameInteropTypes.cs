using System;

namespace OfflineUnlockMod;

internal static class GameInteropTypes
{
	private static Type _releaseAbilityManagerType;
	private static Type _releaseAbilityWrapperType;
	private static Type _releaseControlsAbilityViewType;

	internal static Type ReleaseAbilityManagerType =>
		_releaseAbilityManagerType ??= FindFirstType(
			"battle.selectedUnit.abilityManager",
			GameSymbols.SelectedUnitHud.AbilityManagerTypeNames);

	internal static Type ReleaseAbilityWrapperType =>
		_releaseAbilityWrapperType ??= FindFirstType(
			"battle.selectedUnit.abilityWrapper",
			GameSymbols.SelectedUnitHud.AbilityWrapperTypeNames);

	internal static Type ReleaseControlsAbilityViewType =>
		_releaseControlsAbilityViewType ??= FindFirstType(
			"battle.selectedUnit.controlsAbilityView",
			GameSymbols.SelectedUnitHud.ControlsAbilityViewTypeNames);

	private static Type FindFirstType(string id, string[] hints)
	{
		if (hints == null)
			return null;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = GameMember.FindType(id + "." + hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	internal static bool TypesMatch(Type actual, Type expected)
	{
		if (actual == null || expected == null)
			return actual == expected;
		if (actual == expected)
			return true;
		if (string.Equals(actual.FullName, expected.FullName, StringComparison.Ordinal)
		    || string.Equals(actual.Name, expected.Name, StringComparison.Ordinal))
			return true;
		var actualObfuscated = GameMember.ReadObfuscatedName(actual);
		var expectedObfuscated = GameMember.ReadObfuscatedName(expected);
		return !string.IsNullOrWhiteSpace(actualObfuscated)
		       && string.Equals(actualObfuscated, expectedObfuscated, StringComparison.Ordinal);
	}

	internal static string[] GetNativeTypeAliases(Type expectedType)
	{
		if (expectedType == null)
			return Array.Empty<string>();
		if (TypesMatch(expectedType, ReleaseAbilityManagerType))
			return GameSymbols.SelectedUnitHud.AbilityManagerTypeNames ?? Array.Empty<string>();
		if (TypesMatch(expectedType, ReleaseAbilityWrapperType))
			return GameSymbols.SelectedUnitHud.AbilityWrapperTypeNames ?? Array.Empty<string>();
		if (TypesMatch(expectedType, ReleaseControlsAbilityViewType))
			return GameSymbols.SelectedUnitHud.ControlsAbilityViewTypeNames ?? Array.Empty<string>();
		return Array.Empty<string>();
	}

	internal static bool IsReleaseAbilityArrayReturnType(Type returnType, Type wrapperType)
	{
		if (returnType == null || wrapperType == null)
			return false;
		if (returnType.IsArray)
			return TypesMatch(returnType.GetElementType(), wrapperType);
		if (!returnType.IsGenericType)
			return false;
		if (returnType.Name.StartsWith("Il2CppReferenceArray", StringComparison.Ordinal))
		{
			var args = returnType.GetGenericArguments();
			return args.Length == 1 && TypesMatch(args[0], wrapperType);
		}
		return false;
	}
}
